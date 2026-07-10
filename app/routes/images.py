"""Emby image proxy routes: serve poster and library images through the backend."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..services.emby_service import client_from_db

router = APIRouter()


@router.get("/emby-image/{item_id}")
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/emby-lib-image/{item_id}")
async def emby_lib_image(item_id: str) -> Response:
    """Proxy library/collection primary images at larger size."""
    client = client_from_db()
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            # Try Primary image first, then Backdrop as fallback
            resp = await http.get(
                f"{client.host}/Items/{item_id}/Images/Primary",
                headers={"X-Emby-Token": client.token},
                params={"maxHeight": 300, "quality": 80},
            )
            if resp.status_code >= 400:
                # Fallback to Backdrop
                resp = await http.get(
                    f"{client.host}/Items/{item_id}/Images/Backdrop",
                    headers={"X-Emby-Token": client.token},
                    params={"maxHeight": 300, "quality": 80},
                )
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, "image unavailable")
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
