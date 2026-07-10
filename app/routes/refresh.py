"""Refresh routes: trigger Emby item / library metadata refresh."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..emby import EmbyError
from ..models import RefreshRequest
from ..services.emby_service import client_from_db
from ..services.logging_service import log

router = APIRouter()


@router.post("/api/refresh")
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


@router.post("/api/refresh-library")
async def refresh_library_api() -> dict[str, Any]:
    """Trigger a full Emby library refresh/scan."""
    client = client_from_db()
    try:
        await client.refresh_library()
        log("REFRESH", "全库刷新指令已发送")
        return {"status": "ok"}
    except EmbyError as exc:
        raise HTTPException(400, str(exc)) from exc
