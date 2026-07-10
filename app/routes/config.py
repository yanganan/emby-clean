"""Configuration routes: get/set config, export/import, backup/restore."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..emby import EmbyClient, EmbyError
from ..models import ConfigRequest
from ..services.logging_service import log
from ..services.sync_service import configure_sync_schedule
from ..services.task_service import reload_task_schedules
from ..store import (
    backup_config,
    export_config,
    get_config,
    get_config_value,
    import_config,
    restore_config,
    set_config_value,
    set_stat,
    connect,
)

router = APIRouter()


@router.get("/api/config")
async def cfg_get() -> dict[str, Any]:
    with connect() as db:
        return get_config(db, include_secret=False)


@router.post("/api/config")
async def cfg_post(req: ConfigRequest) -> dict[str, Any]:
    host = (req.host or "").rstrip("/")
    user = req.user or ""
    pwd = req.pwd or ""
    with connect() as db:
        old_pwd = get_config_value(db, "pwd", "")
    if host and user and pwd:
        try:
            session = await EmbyClient(host).authenticate(user, pwd)
        except EmbyError as exc:
            raise HTTPException(400, str(exc)) from exc
        with connect() as db:
            set_config_value(db, "access_token", session.access_token)
            set_config_value(db, "user_id", session.user_id)
            set_stat(db, "server_id", session.server_id)
            set_stat(db, "server_name", session.server_name)
            set_stat(db, "server_ver", session.server_version)
            set_stat(db, "user_name", session.user_name)
    elif host and user and old_pwd:
        pwd = old_pwd

    with connect() as db:
        set_config_value(db, "host", host)
        set_config_value(db, "user", user)
        if pwd:
            set_config_value(db, "pwd", pwd)
        set_config_value(db, "webhook", req.webhook or "")
        set_config_value(db, "cron_sync", req.cron_sync or "")
        if req.prefs is not None:
            set_config_value(db, "prefs", req.prefs)
    configure_sync_schedule(req.cron_sync or "")
    backup_config()  # auto-backup to JSON file
    log("CONFIG", "配置已保存")
    return {"status": "ok"}


@router.get("/api/config/export")
async def cfg_export() -> dict[str, Any]:
    """Export all config + stats + tasks as JSON (for download/backup)."""
    return export_config()


@router.post("/api/config/import")
async def cfg_import(payload: dict[str, Any]) -> dict[str, Any]:
    """Import config from JSON payload. Overwrites existing config."""
    success = import_config(payload)
    if not success:
        raise HTTPException(400, "导入失败：数据格式无效或缺少配置")
    # Re-configure schedules after import
    with connect() as db:
        cron_sync = get_config(db).get("cron_sync", "")
    configure_sync_schedule(cron_sync)
    reload_task_schedules()
    log("CONFIG", "配置已从导入文件恢复")
    return {"status": "ok"}
