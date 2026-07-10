"""WebSocket endpoint for real-time log streaming and status pushes."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import state
from ..store import connect, get_config, get_stat

router = APIRouter()

# Track connected WebSocket clients
_clients: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    try:
        # Send initial snapshot
        await ws.send_json({"type": "connected", "data": _build_status()})
        # Keep connection alive; client doesn't send messages
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


def _build_status() -> dict[str, Any]:
    """Build a lightweight status snapshot for WebSocket push."""
    try:
        with connect() as db:
            cfg = get_config(db, include_secret=True)
            return {
                "connected": bool(cfg.get("host") and cfg.get("access_token")),
                "is_syncing": state.SYNC_LOCK.locked(),
                "sync_lib": get_stat(db, "sync_lib", ""),
                "sync_current": get_stat(db, "sync_current", 0),
                "sync_expected": get_stat(db, "sync_expected", 0),
                "sync_total": get_stat(db, "sync_total", 0),
                "is_deleting": state.DELETE_TASK is not None and not state.DELETE_TASK.done(),
                "delete_current": get_stat(db, "delete_current", 0),
                "delete_total": get_stat(db, "delete_total", 0),
                "delete_failed": db.execute(
                    "select count(*) c from delete_queue where status='failed'"
                ).fetchone()["c"],
                "cleaned_count": str(get_stat(db, "cleaned_count", 0)),
                "saved_space": str(get_stat(db, "saved_space", 0)),
                "media_cache": db.execute(
                    "select count(*) c from media_items where is_media=1"
                ).fetchone()["c"],
                "last_log": state.LOGS[-1] if state.LOGS else "",
            }
    except Exception:
        return {}


async def broadcast_log(line: str) -> None:
    """Push a new log line to all connected WebSocket clients."""
    if not _clients:
        return
    msg = json.dumps({"type": "log", "data": line})
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


async def broadcast_status() -> None:
    """Push a status update to all connected WebSocket clients."""
    if not _clients:
        return
    status = _build_status()
    msg = json.dumps({"type": "status", "data": status})
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)
