"""Library listing and metadata-sync trigger routes."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import state
from ..emby import EmbyError
from ..services.emby_service import client_from_db
from ..services.sync_service import sync_metadata
from ..store import connect

router = APIRouter()


def db_count_library(library_id: str) -> int:
    with connect() as db:
        return db.execute(
            "select count(*) c from media_items where library_id = ? and is_media = 1",
            (library_id,),
        ).fetchone()["c"]


@router.get("/api/libraries")
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
                "ImageId": r["id"],
            }
            for r in cached
        ]
    try:
        return await client_from_db().libraries()
    except EmbyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/sync")
async def sync_p() -> dict[str, Any]:
    if state.SYNC_LOCK.locked():
        return {"status": "busy"}
    asyncio.create_task(sync_metadata())
    return {"status": "ok"}
