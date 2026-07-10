"""Ignore-list routes: manage items excluded from scan recommendations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..models import IgnoreRequest
from ..services.logging_service import log
from ..store import connect, now_ts

router = APIRouter()


@router.get("/api/ignore")
async def ignore_get(limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "select * from ignore_items order by id desc limit ? offset ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/api/ignore")
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


@router.delete("/api/ignore/{row_id}")
async def ignore_del(row_id: int) -> dict[str, Any]:
    with connect() as db:
        db.execute("delete from ignore_items where id = ?", (row_id,))
    return {"status": "ok"}
