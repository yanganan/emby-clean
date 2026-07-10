"""Emby Clean — FastAPI application entry point.

This module creates the :data:`app` object that uvicorn loads via
``app.main:app``.  All business logic lives in :mod:`app.services` and
all HTTP handlers live in :mod:`app.routes`; this file wires them together
and manages application lifecycle (startup / shutdown).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import state
from .routes import (
    basic,
    config,
    delete,
    images,
    ignore,
    libraries,
    logs,
    refresh,
    scan,
    tasks,
)
from .services.delete_service import is_delete_worker_running
from .services.emby_service import startup_reauth
from .services.logging_service import log
from .services.sync_service import configure_sync_schedule
from .services.task_service import reload_task_schedules
from .store import (
    connect,
    get_config,
    init_db,
    is_data_volume_mounted,
    restore_config,
)

app = FastAPI(title="Emby Clean", version="2.0.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# -- Register all API routers -----------------------------------------------
for _router in (
    basic.router,
    config.router,
    libraries.router,
    scan.router,
    delete.router,
    images.router,
    refresh.router,
    ignore.router,
    tasks.router,
    logs.router,
):
    app.include_router(_router)


# -- Lifecycle ---------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    init_db()

    # Check if /data is a mounted volume — warn if not
    if not is_data_volume_mounted():
        log("WARNING", "⚠️ 数据目录未挂载持久卷！容器重建后数据将丢失。请使用 -v ./data:/data 挂载卷。")
    else:
        log("SYSTEM", "数据目录已挂载持久卷 ✓")

    # Try to restore config from backup if DB is empty
    if restore_config():
        log("SYSTEM", "检测到空数据库，已从备份文件恢复配置。")
    else:
        log("SYSTEM", "配置检查完成。")

    with connect() as db:
        db.execute("update delete_queue set status='pending', error=NULL where status='running'")
        cron_sync = get_config(db).get("cron_sync", "")
    if not state.scheduler.running:
        state.scheduler.start()
    configure_sync_schedule(cron_sync)
    reload_task_schedules()
    log("SYSTEM", "服务就绪 (v2.0)...")
    # Proactively re-authenticate on startup if credentials are available
    asyncio.create_task(startup_reauth())


@app.on_event("shutdown")
async def shutdown() -> None:
    """Graceful shutdown: stop scheduler and wait for delete worker."""
    log("SYSTEM", "正在关闭服务...")
    if state.scheduler.running:
        state.scheduler.shutdown(wait=False)
    # Wait briefly for delete worker to finish current item
    if is_delete_worker_running():
        log("SYSTEM", "等待删除队列完成当前操作...")
        try:
            await asyncio.wait_for(state.DELETE_TASK, timeout=30)  # type: ignore[arg-type]
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log("SYSTEM", "删除队列超时，强制关闭")
    log("SYSTEM", "服务已关闭")
