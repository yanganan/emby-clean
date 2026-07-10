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
