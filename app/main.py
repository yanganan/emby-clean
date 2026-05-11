from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .emby import EmbyClient, EmbyError
from .scanner import item_from_emby, prune_missing, scan as run_scan, upsert_items
from .store import get_config, get_config_value, get_stat, init_db, now_ts, set_config_value, set_stat, connect


app = FastAPI(title="Emby Clean", version="1.0.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

LOGS: list[str] = []
SYNC_LOCK = asyncio.Lock()
DELETE_LOCK = asyncio.Lock()
DELETE_TASK: asyncio.Task | None = None
DELETE_CONFIRM_TIMEOUT = 90
DELETE_CONFIRM_INTERVAL = 3
DELETE_SETTLE_SECONDS = 5


class ConfigRequest(BaseModel):
    host: str | None = ""
    user: str | None = ""
    pwd: str | None = ""
    webhook: str | None = ""
    cron_sync: str | None = ""
    prefs: dict[str, Any] | None = None


class DeleteRequest(BaseModel):
    ids: list[str]


class RefreshRequest(BaseModel):
    ids: list[str]


class IgnoreRequest(BaseModel):
    ids: list[str] = []
    mode: str
    group_keys: list[str] = []


class TaskReq(BaseModel):
    name: str
    mode: str
    cron: str
    libraries: str
    enabled: bool


@app.on_event("startup")
async def startup() -> None:
    init_db()
    with connect() as db:
        db.execute("update delete_queue set status='pending', error=NULL where status='running'")
    log("SYSTEM", "服务就绪...")


def log(kind: str, msg: str) -> None:
    line = time.strftime(f"[%H:%M:%S] [{kind}] ") + msg
    LOGS.append(line)
    del LOGS[:-500]
    try:
        with connect() as db:
            db.execute("insert into logs(line,created_at) values(?,?)", (line, now_ts()))
            db.execute(
                "delete from logs where id not in (select id from logs order by id desc limit 1000)"
            )
    except Exception:
        pass


def client_from_db() -> EmbyClient:
    with connect() as db:
        cfg = get_config(db, include_secret=True)
    return EmbyClient(cfg.get("host", ""), cfg.get("access_token", ""), cfg.get("user_id", ""))


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text("utf-8")


@app.get("/api/health")
async def health_api() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/status")
async def status_api() -> dict[str, Any]:
    with connect() as db:
        cfg = get_config(db, include_secret=True)
        total = db.execute("select count(*) c from media_items").fetchone()["c"]
        connected = bool(cfg.get("host") and cfg.get("access_token"))
        last_log_row = db.execute("select line from logs order by id desc limit 1").fetchone()
        return {
            "local_cache": total,
            "media_cache": db.execute("select count(*) c from media_items where is_media = 1").fetchone()["c"],
            "library_expected": db.execute("select coalesce(sum(item_count),0) c from libraries").fetchone()["c"],
            "library_api_total": db.execute("select coalesce(sum(api_count),0) c from libraries").fetchone()["c"],
            "cleaned_count": str(get_stat(db, "cleaned_count", 0)),
            "saved_space": str(get_stat(db, "saved_space", 0)),
            "is_syncing": SYNC_LOCK.locked(),
            "is_deleting": is_delete_worker_running(),
            "delete_current": db.execute("select count(*) c from delete_queue where status='done'").fetchone()["c"],
            "delete_total": db.execute("select count(*) c from delete_queue where status in ('pending','running','done')").fetchone()["c"],
            "delete_pending": db.execute("select count(*) c from delete_queue where status='pending'").fetchone()["c"],
            "delete_running": db.execute("select count(*) c from delete_queue where status='running'").fetchone()["c"],
            "sync_lib": get_stat(db, "sync_lib", ""),
            "sync_current": get_stat(db, "sync_current", 0),
            "sync_expected": get_stat(db, "sync_expected", 0),
            "sync_total": get_stat(db, "sync_total", 0),
            "last_sync_at": get_stat(db, "last_sync_at", 0),
            "connected": connected,
            "server_name": get_stat(db, "server_name", ""),
            "server_id": get_stat(db, "server_id", ""),
            "server_ver": get_stat(db, "server_ver", ""),
            "user_name": get_stat(db, "user_name", cfg.get("user", "")),
            "sync_cron": cfg.get("cron_sync", ""),
            "last_log": LOGS[-1] if LOGS else (last_log_row["line"] if last_log_row else ""),
            "status_checked_at": now_ts(),
        }


@app.get("/api/config")
async def cfg_get() -> dict[str, Any]:
    with connect() as db:
        return get_config(db, include_secret=False)


@app.post("/api/config")
async def cfg_post(req: ConfigRequest) -> dict[str, Any]:
    host = (req.host or "").rstrip("/")
    user = req.user or ""
    pwd = req.pwd or ""
    with connect() as db:
        old_pwd = get_config_value(db, "pwd", "")
    if host and user and pwd:
        try:
            session = await EmbyClient(host).authenticate(user, pwd)
        except EmbyError as exc:
            raise HTTPException(400, str(exc)) from exc
        with connect() as db:
            set_config_value(db, "access_token", session.access_token)
            set_config_value(db, "user_id", session.user_id)
            set_stat(db, "server_id", session.server_id)
            set_stat(db, "server_name", session.server_name)
            set_stat(db, "server_ver", session.server_version)
            set_stat(db, "user_name", session.user_name)
    elif host and user and old_pwd:
        pwd = old_pwd

    with connect() as db:
        set_config_value(db, "host", host)
        set_config_value(db, "user", user)
        if pwd:
            set_config_value(db, "pwd", pwd)
        set_config_value(db, "webhook", req.webhook or "")
        set_config_value(db, "cron_sync", req.cron_sync or "")
        if req.prefs is not None:
            set_config_value(db, "prefs", req.prefs)
    log("CONFIG", "配置已保存")
    return {"status": "ok"}


@app.get("/api/libraries")
async def libs_g() -> list[dict[str, Any]]:
    with connect() as db:
        cached = db.execute("select * from libraries order by name").fetchall()
    if cached:
        return [
            {
                "Id": r["id"],
                "Name": r["name"],
                "CollectionType": r["collection_type"],
                "ParentId": r["parent_id"],
                "ItemCount": r["item_count"],
                "CachedCount": db_count_library(r["id"]),
                "ApiCount": r["api_count"],
            }
            for r in cached
        ]
    try:
        return await client_from_db().libraries()
    except EmbyError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sync")
async def sync_p() -> dict[str, Any]:
    if SYNC_LOCK.locked():
        return {"status": "busy"}
    asyncio.create_task(sync_metadata())
    return {"status": "ok"}


def db_count_library(library_id: str) -> int:
    with connect() as db:
        return db.execute(
            "select count(*) c from media_items where library_id = ? and is_media = 1",
            (library_id,),
        ).fetchone()["c"]


async def sync_metadata(library_ids: list[str] | None = None) -> None:
    async with SYNC_LOCK:
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
            log("SYNC", f"同步完成：API {len(seen)} 条，媒体缓存 {media_total} 条，清理失效缓存 {removed} 条，耗时 {int((time.time()-started)*1000)}ms")
        except Exception as exc:
            with connect() as db:
                set_stat(db, "sync_lib", "")
            log("ERROR", f"同步失败：{exc}")


@app.get("/api/scan")
async def scan_api(
    mode: str,
    lib: str = "",
    param_s: str = "100",
    param_d: str = "0",
    duration_scope: str = "dir",
    duration_precision: str = "second",
) -> list[dict[str, Any]]:
    with connect() as db:
        prefs = get_config(db).get("prefs", {})
        libs = [x for x in lib.split(",") if x]
        data = run_scan(
            db,
            mode,
            libs,
            {
                "param_s": param_s,
                "param_d": param_d,
                "duration_scope": duration_scope,
                "duration_precision": duration_precision,
            },
            prefs,
        )
    log("SCAN", f"{mode} 命中 {sum(len(g['items']) for g in data)} 条 / {len(data)} 组")
    return data


@app.post("/api/delete")
async def dele_post(req: DeleteRequest) -> dict[str, Any]:
    queued = 0
    skipped = 0
    ids = list(dict.fromkeys(req.ids))
    if not ids:
        return {"status": "ok", "queued": 0, "skipped": 0, "message": "没有可加入队列的条目"}
    placeholders = ",".join("?" for _ in ids)
    with connect() as db:
        rows = db.execute(
            f"select emby_id,name,size,path from media_items where emby_id in ({placeholders})",
            ids,
        ).fetchall()
        known = {row["emby_id"] for row in rows}
        queued_existing = {
            row["emby_id"]
            for row in db.execute(
                f"select emby_id from delete_queue where status in ('pending','running') and emby_id in ({placeholders})",
                ids,
            ).fetchall()
        }
        for row in rows:
            if row["emby_id"] in queued_existing:
                skipped += 1
                continue
            db.execute(
                """
                insert into delete_queue(emby_id,name,path,size,status,created_at)
                values(?,?,?,?,?,?)
                """,
                (row["emby_id"], row["name"], row["path"], row["size"] or 0, "pending", now_ts()),
            )
            queued += 1
        skipped += len([item_id for item_id in ids if item_id not in known])
    log("DELETE", f"加入删除队列：新增 {queued} 条，跳过 {skipped} 条")
    ensure_delete_worker()
    return {"status": "queued", "queued": queued, "skipped": skipped, "message": f"已加入删除队列 {queued} 条"}


def is_delete_worker_running() -> bool:
    return DELETE_TASK is not None and not DELETE_TASK.done()


def ensure_delete_worker() -> None:
    global DELETE_TASK
    if not is_delete_worker_running():
        DELETE_TASK = asyncio.create_task(delete_worker())


async def delete_worker() -> None:
    async with DELETE_LOCK:
        client = client_from_db()
        deleted = 0
        failed = 0
        saved = 0
        log("DELETE", "删除队列 worker 已启动")
        while True:
            with connect() as db:
                row = db.execute(
                    "select * from delete_queue where status='pending' order by id asc limit 1"
                ).fetchone()
                if not row:
                    db.execute("delete from delete_queue where status='done'")
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
                    raise EmbyError(f"等待 {DELETE_CONFIRM_TIMEOUT}s 后仍可查询到条目，暂不删除本地缓存")
                log("DELETE", f"[队列#{row['id']}] 已确认 Emby 条目消失，等待文件系统收敛 {DELETE_SETTLE_SECONDS}s")
                await asyncio.sleep(DELETE_SETTLE_SECONDS)
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
                        "update delete_queue set status='failed', error=?, finished_at=? where id=?",
                        (str(exc), now_ts(), row["id"]),
                    )
                log("ERROR", f"[队列#{row['id']}] 删除 {row['emby_id']} 失败：{exc}")
            await asyncio.sleep(DELETE_CONFIRM_INTERVAL)
        log("DELETE", f"删除队列完成：成功 {deleted} 条，失败 {failed} 条，释放 {saved} bytes")


@app.get("/api/delete-queue")
async def delete_queue_get() -> dict[str, Any]:
        with connect() as db:
            rows = db.execute(
                "select id,emby_id,name,status,error,created_at,started_at,finished_at from delete_queue order by id asc limit 200"
            ).fetchall()
            counts = {
                row["status"]: row["c"]
                for row in db.execute("select status,count(*) c from delete_queue group by status").fetchall()
            }
        return {"running": is_delete_worker_running(), "counts": counts, "items": [dict(row) for row in rows]}


async def wait_item_deleted(client: EmbyClient, item_id: str) -> bool:
    deadline = time.time() + DELETE_CONFIRM_TIMEOUT
    while time.time() < deadline:
        if not await client.item_exists(item_id):
            return True
        await asyncio.sleep(DELETE_CONFIRM_INTERVAL)
    return False


@app.get("/emby-image/{item_id}")
async def emby_image(item_id: str) -> Response:
    client = client_from_db()
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.get(
                f"{client.host}/Items/{item_id}/Images/Primary",
                headers={"X-Emby-Token": client.token},
                params={"maxHeight": 220, "quality": 85},
            )
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, "image unavailable")
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/refresh")
async def refresh_p(req: RefreshRequest) -> dict[str, Any]:
    client = client_from_db()
    ok = 0
    for item_id in req.ids:
        try:
            await client.refresh_item(item_id)
            ok += 1
        except Exception as exc:
            log("ERROR", f"刷新 {item_id} 失败：{exc}")
    log("REFRESH", f"刷新指令已发送 {ok} 条")
    return {"status": "ok", "count": ok}


@app.get("/api/ignore")
async def ignore_get(limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "select * from ignore_items order by id desc limit ? offset ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/ignore")
async def ignore_post(req: IgnoreRequest) -> dict[str, Any]:
    with connect() as db:
        for item_id in req.ids:
            row = db.execute("select name,path from media_items where emby_id = ?", (item_id,)).fetchone()
            db.execute(
                "insert into ignore_items(emby_id,mode,scope,name,path,created_at) values(?,?,?,?,?,?)",
                (item_id, req.mode, "item", row["name"] if row else "", row["path"] if row else "", now_ts()),
            )
        for key in req.group_keys:
            db.execute(
                "insert into ignore_items(group_key,mode,scope,created_at) values(?,?,?,?)",
                (key, req.mode, "group", now_ts()),
            )
    log("IGNORE", f"{req.mode} 忽略 {len(req.ids) + len(req.group_keys)} 条")
    return {"status": "ok"}


@app.delete("/api/ignore/{row_id}")
async def ignore_del(row_id: int) -> dict[str, Any]:
    with connect() as db:
        db.execute("delete from ignore_items where id = ?", (row_id,))
    return {"status": "ok"}


@app.get("/api/tasks")
async def tasks_get() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from tasks order by id desc").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/tasks")
async def task_post(req: TaskReq) -> dict[str, Any]:
    with connect() as db:
        cur = db.execute(
            "insert into tasks(name,mode,cron,libraries,enabled,updated_at) values(?,?,?,?,?,?)",
            (req.name, req.mode, req.cron, req.libraries, int(req.enabled), now_ts()),
        )
        return {"status": "ok", "id": cur.lastrowid}


@app.put("/api/tasks/{tid}")
async def task_put(tid: int, req: TaskReq) -> dict[str, Any]:
    with connect() as db:
        db.execute(
            "update tasks set name=?,mode=?,cron=?,libraries=?,enabled=?,updated_at=? where id=?",
            (req.name, req.mode, req.cron, req.libraries, int(req.enabled), now_ts(), tid),
        )
    return {"status": "ok"}


@app.delete("/api/tasks/{row_id}")
async def task_del(row_id: int) -> dict[str, Any]:
    with connect() as db:
        db.execute("delete from tasks where id = ?", (row_id,))
    return {"status": "ok"}


@app.post("/api/tasks/{row_id}/run")
async def task_run_now(row_id: int) -> dict[str, Any]:
    with connect() as db:
        task = db.execute("select * from tasks where id = ?", (row_id,)).fetchone()
    if not task:
        raise HTTPException(404, "task not found")
    started = time.time()
    await sync_metadata([x for x in task["libraries"].split(",") if x])
    data = await scan_api(task["mode"], task["libraries"])
    duration = int((time.time() - started) * 1000)
    found = sum(len(g["items"]) for g in data)
    message = f"命中 {found} 条"
    with connect() as db:
        db.execute(
            "update tasks set last_status=?,last_found=?,last_duration_ms=?,last_message=?,updated_at=? where id=?",
            ("ok", found, duration, message, now_ts(), row_id),
        )
    return {"status": "ok", "found": found, "last_message": message}


@app.get("/api/logs")
async def logs_g() -> list[str]:
    with connect() as db:
        rows = db.execute("select line from logs order by id desc limit 500").fetchall()
    return [r["line"] for r in rows] or list(reversed(LOGS))


@app.post("/api/logs/clear")
async def logs_c() -> dict[str, Any]:
    LOGS.clear()
    with connect() as db:
        db.execute("delete from logs")
    return {"status": "ok"}


@app.post("/api/test_webhook")
async def tw_p() -> dict[str, Any]:
    with connect() as db:
        webhook = get_config(db).get("webhook")
    if not webhook:
        return {"status": "skip", "message": "未配置 webhook"}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(webhook, json={"title": "Emby Clean", "text": "Webhook 测试"})
    return {"status": "ok"}
