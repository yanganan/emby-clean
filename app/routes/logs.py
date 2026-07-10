"""Log routes: list / clear logs and test webhook delivery."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter

from .. import state
from ..store import connect, get_config

router = APIRouter()


@router.get("/api/logs")
async def logs_g() -> list[str]:
    with connect() as db:
        rows = db.execute("select line from logs order by id desc limit 500").fetchall()
    return [r["line"] for r in rows] or list(reversed(state.LOGS))


@router.post("/api/logs/clear")
async def logs_c() -> dict[str, Any]:
    state.LOGS.clear()
    with connect() as db:
        db.execute("delete from logs")
    return {"status": "ok"}


@router.post("/api/test_webhook")
async def tw_p() -> dict[str, Any]:
    with connect() as db:
        webhook = get_config(db).get("webhook")
    if not webhook:
        return {"status": "skip", "message": "未配置 webhook"}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(webhook, json={"title": "Emby Clean", "text": "Webhook 测试"})
    return {"status": "ok"}
