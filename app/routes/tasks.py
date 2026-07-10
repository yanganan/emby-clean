"""Scheduled-task routes: CRUD operations and manual run trigger."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from .. import state
from ..models import TaskReq
from ..services.logging_service import log
from ..services.task_service import reload_task_schedules, scheduled_task_run
from ..store import connect, now_ts

router = APIRouter()


@router.get("/api/tasks")
async def tasks_get() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from tasks order by id desc").fetchall()
        return [dict(r) for r in rows]


@router.post("/api/tasks")
async def task_post(req: TaskReq) -> dict[str, Any]:
    with connect() as db:
        cur = db.execute(
            "insert into tasks(name,mode,cron,libraries,enabled,auto_delete,updated_at) values(?,?,?,?,?,?,?)",
            (req.name, req.mode, req.cron, req.libraries, int(req.enabled), int(req.auto_delete), now_ts()),
        )
        new_id = cur.lastrowid
    reload_task_schedules()
    log("TASK", f"创建任务 [{req.name}]：{req.cron}，自动删除={'开' if req.auto_delete else '关'}")
    return {"status": "ok", "id": new_id}


@router.put("/api/tasks/{tid}")
async def task_put(tid: int, req: TaskReq) -> dict[str, Any]:
    with connect() as db:
        db.execute(
            "update tasks set name=?,mode=?,cron=?,libraries=?,enabled=?,auto_delete=?,updated_at=? where id=?",
            (req.name, req.mode, req.cron, req.libraries, int(req.enabled), int(req.auto_delete), now_ts(), tid),
        )
    reload_task_schedules()
    log("TASK", f"更新任务 [{req.name}]")
    return {"status": "ok"}


@router.delete("/api/tasks/{row_id}")
async def task_del(row_id: int) -> dict[str, Any]:
    job_id = f"{state.TASK_SCHED_PREFIX}{row_id}"
    if state.scheduler.get_job(job_id):
        state.scheduler.remove_job(job_id)
    with connect() as db:
        db.execute("delete from tasks where id = ?", (row_id,))
    log("TASK", f"删除任务 #{row_id}")
    return {"status": "ok"}


@router.post("/api/tasks/{row_id}/run")
async def task_run_now(row_id: int) -> dict[str, Any]:
    """Run a task immediately."""
    asyncio.create_task(scheduled_task_run(row_id))
    return {"status": "ok", "message": "任务已触发"}
