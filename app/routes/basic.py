"""Basic routes: index page, health check, and system status."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .. import state
from ..services.delete_service import is_delete_worker_running
from ..store import connect, get_config, get_stat, now_ts

router = APIRouter()

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (_STATIC_DIR / "index.html").read_text("utf-8")


@router.get("/api/health")
async def health_api() -> dict[str, Any]:
    return {"ok": True, "version": "2.0.0"}


@router.get("/api/status")
async def status_api() -> dict[str, Any]:
    with connect() as db:
        cfg = get_config(db, include_secret=True)
        total = db.execute("select count(*) c from media_items").fetchone()["c"]
        connected = bool(cfg.get("host") and cfg.get("access_token"))
        last_log_row = db.execute("select line from logs order by id desc limit 1").fetchone()

        # Library storage stats
        lib_stats = db.execute(
            """
            select library_id, library_name,
                   count(*) as item_count,
                   coalesce(sum(size),0) as total_size,
                   sum(case when has_poster=0 then 1 else 0 end) as no_poster,
                   sum(case when duration_seconds=0 then 1 else 0 end) as no_duration
            from media_items where is_media=1
            group by library_id
            order by total_size desc
            """
        ).fetchall()

        return {
            "local_cache": total,
            "media_cache": db.execute("select count(*) c from media_items where is_media = 1").fetchone()["c"],
            "library_expected": db.execute("select coalesce(sum(item_count),0) c from libraries").fetchone()["c"],
            "library_api_total": db.execute("select coalesce(sum(api_count),0) c from libraries").fetchone()["c"],
            "cleaned_count": str(get_stat(db, "cleaned_count", 0)),
            "saved_space": str(get_stat(db, "saved_space", 0)),
            "is_syncing": state.SYNC_LOCK.locked(),
            "is_deleting": is_delete_worker_running(),
            "delete_current": db.execute("select count(*) c from delete_queue where status='done'").fetchone()["c"],
            "delete_total": db.execute("select count(*) c from delete_queue where status in ('pending','running','done')").fetchone()["c"],
            "delete_pending": db.execute("select count(*) c from delete_queue where status='pending'").fetchone()["c"],
            "delete_running": db.execute("select count(*) c from delete_queue where status='running'").fetchone()["c"],
            "delete_failed": db.execute("select count(*) c from delete_queue where status='failed'").fetchone()["c"],
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
            "last_log": state.LOGS[-1] if state.LOGS else (last_log_row["line"] if last_log_row else ""),
            "status_checked_at": now_ts(),
            "library_stats": [
                {
                    "library_id": r["library_id"],
                    "library_name": r["library_name"],
                    "item_count": r["item_count"],
                    "total_size": r["total_size"],
                    "no_poster": r["no_poster"],
                    "no_duration": r["no_duration"],
                }
                for r in lib_stats
            ],
            "total_storage": sum(r["total_size"] for r in lib_stats),
        }
