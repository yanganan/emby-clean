"""Metadata synchronisation: pulling library data from Emby into the local DB."""
from __future__ import annotations

import json
import time
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from .. import state
from ..scanner import item_from_emby, prune_missing, upsert_items
from ..store import connect, get_config, now_ts, set_stat
from .emby_service import client_from_db
from .logging_service import log, notify


def configure_sync_schedule(cron_expr: str | None) -> None:
    if state.scheduler.get_job(state.SYNC_JOB_ID):
        state.scheduler.remove_job(state.SYNC_JOB_ID)
    expr = (cron_expr or "").strip()
    if not expr:
        return
    try:
        trigger = CronTrigger.from_crontab(expr, timezone="Asia/Shanghai")
        state.scheduler.add_job(
            scheduled_sync_metadata,
            trigger,
            id=state.SYNC_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        log("CONFIG", f"已启用媒体库自动同步：{expr}")
    except ValueError as exc:
        log("ERROR", f"自动同步定时表达式无效：{expr}，{exc}")


async def scheduled_sync_metadata() -> None:
    if state.SYNC_LOCK.locked():
        log("SYNC", "自动同步跳过：已有同步任务运行中")
        return
    log("SYNC", "自动同步触发")
    await sync_metadata()


async def sync_metadata(library_ids: list[str] | None = None) -> None:
    async with state.SYNC_LOCK:
        started = time.time()
        client = client_from_db()
        try:
            libs = await client.libraries()
            if library_ids:
                lib_set = set(library_ids)
                libs = [lib for lib in libs if str(lib.get("Id")) in lib_set]
            library_map = {str(x.get("Id")): x.get("Name", "") for x in libs}
            with connect() as db:
                set_stat(db, "sync_current", 0)
                set_stat(db, "sync_total", 0)
                set_stat(db, "sync_lib", "准备同步")
                for lib in libs:
                    db.execute(
                        """
                        insert into libraries(id,name,collection_type,parent_id,raw_json,item_count,api_count,updated_at)
                        values(?,?,?,?,?,?,?,?)
                        on conflict(id) do update set
                          name=excluded.name,
                          collection_type=excluded.collection_type,
                          parent_id=excluded.parent_id,
                          raw_json=excluded.raw_json,
                          api_count=excluded.api_count,
                          updated_at=excluded.updated_at
                        """,
                        (
                            str(lib.get("Id")),
                            lib.get("Name") or "",
                            lib.get("CollectionType") or "",
                            str(lib.get("ParentId") or ""),
                            json.dumps(lib, ensure_ascii=False),
                            int(lib.get("ItemCount") or 0),
                            int(lib.get("ItemCount") or 0),
                            now_ts(),
                        ),
                    )
            seen: set[str] = set()
            total_seen = 0
            total_expected = 0
            log("SYNC", f">>> 同步启动：{len(libs)} 个媒体库")
            for lib in libs:
                lib_id = str(lib.get("Id"))
                lib_name = lib.get("Name") or lib_id
                batch: list[dict[str, Any]] = []
                lib_seen = 0
                expected = 0
                with connect() as db:
                    set_stat(db, "sync_lib", lib_name)
                    set_stat(db, "sync_current", 0)
                    set_stat(db, "sync_expected", 0)
                log("SYNC", f"开始索引 [{lib_name}]")
                start_index = 0
                page_size = 500
                while True:
                    page = await client.items_page(lib_id, start_index, page_size, "")
                    raw_items = page.get("Items", [])
                    expected = int(page.get("TotalRecordCount") or expected or 0)
                    total_expected += expected if start_index == 0 else 0
                    with connect() as db:
                        set_stat(db, "sync_expected", expected)
                    for raw in raw_items:
                        item = item_from_emby(raw, library_map, lib_id, lib_name)
                        if item["emby_id"]:
                            seen.add(item["emby_id"])
                            batch.append(item)
                            lib_seen += 1
                            total_seen += 1
                        if len(batch) >= 300:
                            with connect() as db:
                                upsert_items(db, batch)
                                set_stat(db, "sync_current", lib_seen)
                                set_stat(db, "sync_total", total_seen)
                            batch.clear()
                    start_index += len(raw_items)
                    if lib_seen and (lib_seen % 1000 == 0 or start_index >= expected):
                        media_seen = sum(1 for item in batch if item.get("is_media"))
                        log("SYNC", f"索引 [{lib_name}]: {lib_seen} / {expected}，待写入媒体 {media_seen}")
                    if not raw_items or start_index >= expected:
                        break
                with connect() as db:
                    upsert_items(db, batch)
                    media_count = db.execute("select count(*) c from media_items where library_id=? and is_media=1", (lib_id,)).fetchone()["c"]
                    db.execute("update libraries set item_count=?, api_count=?, updated_at=? where id=?", (media_count, expected, now_ts(), lib_id))
                    set_stat(db, "sync_current", lib_seen)
                    set_stat(db, "sync_total", total_seen)
                log("SYNC", f"完成 [{lib_name}]: API {lib_seen} 条，媒体缓存 {media_count} 条")
            with connect() as db:
                removed = prune_missing(db, seen, library_ids)
                set_stat(db, "last_sync_at", now_ts())
                set_stat(db, "sync_lib", "")
                set_stat(db, "sync_current", 0)
                set_stat(db, "sync_expected", 0)
                media_total = db.execute("select count(*) c from media_items where is_media=1").fetchone()["c"]
                set_stat(db, "library_expected", total_expected)
            duration_ms = int((time.time() - started) * 1000)
            log("SYNC", f"同步完成：API {len(seen)} 条，媒体缓存 {media_total} 条，清理失效缓存 {removed} 条，耗时 {duration_ms}ms")
            await notify("元数据同步完成", f"缓存 {media_total} 条，清理失效 {removed} 条，耗时 {duration_ms}ms")
        except Exception as exc:
            with connect() as db:
                set_stat(db, "sync_lib", "")
            log("ERROR", f"同步失败：{exc}")
            await notify("元数据同步失败", str(exc))
