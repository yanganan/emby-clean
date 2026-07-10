"""Logging and webhook-notification helpers."""
from __future__ import annotations

import time

import httpx

from .. import state
from ..store import connect, get_config_value, now_ts


def log(kind: str, msg: str) -> None:
    line = time.strftime(f"[%H:%M:%S] [{kind}] ") + msg
    state.LOGS.append(line)
    del state.LOGS[:-500]
    try:
        with connect() as db:
            db.execute("insert into logs(line,created_at) values(?,?)", (line, now_ts()))
            # Only trim when logs table exceeds 1500 rows (amortized, not every call)
            count = db.execute("select count(*) c from logs").fetchone()["c"]
            if count > 1500:
                db.execute(
                    "delete from logs where id not in (select id from logs order by id desc limit 1000)"
                )
    except Exception:
        pass
    # Broadcast to WebSocket clients (fire-and-forget)
    _ws_broadcast_log(line)


def _ws_broadcast_log(line: str) -> None:
    """Try to push log line to WebSocket clients. Non-blocking, best-effort."""
    try:
        from ..routes.ws import broadcast_log
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_log(line))
    except Exception:
        pass


# Late import to avoid circular deps
import asyncio  # noqa: E402


async def notify(title: str, text: str) -> None:
    """Send a webhook notification if configured."""
    with connect() as db:
        webhook = get_config_value(db, "webhook", "")
    if not webhook:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook, json={"title": f"Emby Clean · {title}", "text": text})
    except Exception as exc:
        log("ERROR", f"Webhook 推送失败：{exc}")
