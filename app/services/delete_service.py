"""Delete-queue worker: processes pending deletions against the Emby API."""
from __future__ import annotations

import asyncio
import time

from .. import state
from ..emby import EmbyClient, EmbyError
from ..store import connect, get_config, get_stat, now_ts, set_stat
from .emby_service import client_from_db
from .logging_service import log, notify


def is_delete_worker_running() -> bool:
    return state.DELETE_TASK is not None and not state.DELETE_TASK.done()


def ensure_delete_worker() -> None:
    if not is_delete_worker_running():
        state.DELETE_TASK = asyncio.create_task(delete_worker())


async def delete_worker() -> None:
    async with state.DELETE_LOCK:
        client = client_from_db()
        deleted = 0
        failed = 0
        saved = 0
        log("DELETE", "删除队列 worker 已启动")
        while True:
            with connect() as db:
                # Re-queue failed items that haven't exceeded retry limit
                prefs = get_config(db).get("prefs", {})
                max_retries = int(prefs.get("delete_retry_max", 3))
                db.execute(
                    """
                    update delete_queue set status='pending', error=NULL
                    where status='failed' and retry_count < ?
                    """,
                    (max_retries,),
                )
                row = db.execute(
                    "select * from delete_queue where status='pending' order by id asc limit 1"
                ).fetchone()
                if not row:
                    db.execute("delete from delete_queue where status='done'")
                    db.execute(
                        "delete from delete_queue where status='failed' and retry_count >= ?",
                        (max_retries,),
                    )
                    set_stat(db, "delete_current", 0)
                    set_stat(db, "delete_total", 0)
                    break
                db.execute(
                    "update delete_queue set status='running', started_at=?, error=NULL where id=?",
                    (now_ts(), row["id"]),
                )
                total = db.execute(
                    "select count(*) c from delete_queue where status in ('pending','running')"
                ).fetchone()["c"]
                set_stat(db, "delete_total", total)
            try:
                log("DELETE", f"[队列#{row['id']}] 发起删除：{row['name'] or row['emby_id']}")
                await client.delete(row["emby_id"])
                log("DELETE", f"[队列#{row['id']}] Emby 已接收删除，等待媒体库确认消失...")
                confirmed = await wait_item_deleted(client, row["emby_id"])
                if not confirmed:
                    raise EmbyError(f"等待 {state.DELETE_CONFIRM_TIMEOUT}s 后仍可查询到条目，暂不删除本地缓存")
                log("DELETE", f"[队列#{row['id']}] 已确认 Emby 条目消失，等待文件系统收敛 {state.DELETE_SETTLE_SECONDS}s")
                await asyncio.sleep(state.DELETE_SETTLE_SECONDS)
                deleted += 1
                saved += int(row["size"] or 0)
                with connect() as db:
                    db.execute("delete from media_items where emby_id = ?", (row["emby_id"],))
                    db.execute(
                        "update delete_queue set status='done', finished_at=? where id=?",
                        (now_ts(), row["id"]),
                    )
                    set_stat(db, "cleaned_count", int(get_stat(db, "cleaned_count", 0)) + 1)
                    set_stat(db, "saved_space", int(get_stat(db, "saved_space", 0)) + int(row["size"] or 0))
                log("DELETE", f"[队列#{row['id']}] 删除完成")
            except Exception as exc:
                failed += 1
                with connect() as db:
                    db.execute(
                        """
                        update delete_queue set status='failed', error=?, finished_at=?,
                          retry_count = coalesce(retry_count,0) + 1
                        where id=?
                        """,
                        (str(exc), now_ts(), row["id"]),
                    )
                log("ERROR", f"[队列#{row['id']}] 删除 {row['emby_id']} 失败 (重试 {row['retry_count'] + 1}/{max_retries})：{exc}")
            await asyncio.sleep(state.DELETE_CONFIRM_INTERVAL)

        # Auto-refresh Emby library after batch deletion
        if deleted > 0:
            prefs_auto = True
            with connect() as db:
                prefs_auto = get_config(db).get("prefs", {}).get("auto_refresh_library", True)
            if prefs_auto:
                log("DELETE", f"批量删除完成，触发 Emby 库扫描...")
                try:
                    await client.refresh_library()
                    log("DELETE", "Emby 库刷新指令已发送")
                except EmbyError as exc:
                    log("ERROR", f"Emby 库刷新失败：{exc}")

        log("DELETE", f"删除队列完成：成功 {deleted} 条，失败 {failed} 条，释放 {saved} bytes")
        if deleted > 0:
            await notify(
                "删除完成",
                f"成功删除 {deleted} 条\n释放空间 {saved:,} bytes\n失败 {failed} 条",
            )


async def wait_item_deleted(client: EmbyClient, item_id: str) -> bool:
    deadline = time.time() + state.DELETE_CONFIRM_TIMEOUT
    while time.time() < deadline:
        if not await client.item_exists(item_id):
            return True
        await asyncio.sleep(state.DELETE_CONFIRM_INTERVAL)
    return False


def queue_deletes(ids: list[str]) -> int:
    """Queue items for deletion. Returns count of newly queued."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    queued = 0
    with connect() as db:
        rows = db.execute(
            f"select emby_id,name,size,path from media_items where emby_id in ({placeholders})",
            ids,
        ).fetchall()
        queued_existing = {
            row["emby_id"]
            for row in db.execute(
                f"select emby_id from delete_queue where status in ('pending','running') and emby_id in ({placeholders})",
                ids,
            ).fetchall()
        }
        for row in rows:
            if row["emby_id"] in queued_existing:
                continue
            db.execute(
                """
                insert into delete_queue(emby_id,name,path,size,status,created_at)
                values(?,?,?,?,?,?)
                """,
                (row["emby_id"], row["name"], row["path"], row["size"] or 0, "pending", now_ts()),
            )
            queued += 1
    if queued:
        ensure_delete_worker()
    return queued
