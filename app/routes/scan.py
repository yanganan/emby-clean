"""Scan routes: duplicate / anomaly detection across media libraries."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..scanner import scan as run_scan
from ..services.logging_service import log
from ..store import connect, get_config

router = APIRouter()


@router.get("/api/scan")
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
        deleting_ids = {
            row["emby_id"]
            for row in db.execute(
                "select emby_id from delete_queue where status in ('pending','running','done')"
            ).fetchall()
        }
        if deleting_ids:
            filtered = []
            removed = 0
            for group in data:
                items = [item for item in group["items"] if item.get("emby_id") not in deleting_ids]
                removed += len(group["items"]) - len(items)
                if len(items) > 1 or (mode in {"noposter", "tiny", "nometa", "nosub", "emptylib"} and items):
                    filtered.append({**group, "items": items})
            data = filtered
            if removed:
                log("SCAN", f"已排除删除队列中的条目 {removed} 条")
    log("SCAN", f"{mode} 命中 {sum(len(g['items']) for g in data)} 条 / {len(data)} 组")
    return data
