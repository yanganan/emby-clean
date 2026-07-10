"""Emby client construction and session persistence."""
from __future__ import annotations

import asyncio

from ..emby import EmbyClient, EmbyError
from ..store import connect, get_config, get_config_value, set_config_value, set_stat
from .logging_service import log


def _persist_token(token: str, user_id: str) -> None:
    """Persist a re-authenticated token to DB (called from EmbyClient callback)."""
    try:
        with connect() as db:
            set_config_value(db, "access_token", token)
            set_config_value(db, "user_id", user_id)
    except Exception:
        pass


def client_from_db() -> EmbyClient:
    with connect() as db:
        cfg = get_config(db, include_secret=True)
    return EmbyClient(
        cfg.get("host", ""),
        cfg.get("access_token", ""),
        cfg.get("user_id", ""),
        username=cfg.get("user", ""),
        password=cfg.get("pwd", ""),
        auto_reauth=True,
        on_reauth=_persist_token,
    )


def save_session_to_db(session) -> None:
    """Persist re-authenticated session credentials to DB."""
    with connect() as db:
        set_config_value(db, "access_token", session.access_token)
        set_config_value(db, "user_id", session.user_id)
        set_stat(db, "server_id", session.server_id)
        set_stat(db, "server_name", session.server_name)
        set_stat(db, "server_ver", session.server_version)
        set_stat(db, "user_name", session.user_name)


async def startup_reauth() -> None:
    """On startup, verify token validity and re-authenticate if expired."""
    await asyncio.sleep(2)
    try:
        client = client_from_db()
        if not client.host:
            return
        with connect() as db:
            stored_user = get_config_value(db, "user", "")
            stored_pwd = get_config_value(db, "pwd", "")
        if stored_user and stored_pwd:
            try:
                info = await client.system_info()
                log("SYSTEM", f"连接正常：{info.get('ServerName','')} v{info.get('Version','')}")
                return
            except EmbyError as exc:
                if "401" in str(exc) or "认证" in str(exc):
                    log("SYSTEM", "Token 已过期，尝试自动重新认证...")
                    session = await EmbyClient(
                        client.host,
                        username=stored_user,
                        password=stored_pwd,
                    ).authenticate()
                    with connect() as db:
                        set_config_value(db, "access_token", session.access_token)
                        set_config_value(db, "user_id", session.user_id)
                        set_stat(db, "server_id", session.server_id)
                        set_stat(db, "server_name", session.server_name)
                        set_stat(db, "server_ver", session.server_version)
                        set_stat(db, "user_name", session.user_name)
                    log("SYSTEM", f"自动重新认证成功：{session.server_name}")
                else:
                    log("ERROR", f"启动连接检查失败：{exc}")
    except Exception as exc:
        log("ERROR", f"启动认证检查异常：{exc}")
