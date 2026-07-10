"""Scheduled-task management: registering and running periodic scan/delete tasks."""
from __future__ import annotations

import asyncio
import time

from apscheduler.triggers.cron import CronTrigger

from .. import state
from ..scanner import scan as run_scan
from ..store import connect, get_config, now_ts
from .delete_service import queue_deletes
from .logging_service import log, notify
from .sync_service import sync_metadata


def reload_task_schedules() -> None:
    """Register all enabled tasks into the APScheduler."""
    # Remove old task jobs
    with connect() as db:
        jobs = state.scheduler.get_jobs()
        for job in jobs:
            if job.id.startswith(state.TASK_SCHED_PREFIX):
                state.scheduler.remove_job(job.id)
        # Re-register enabled tasks
        rows = db.execute("select * from tasks where enabled=1").fetchall()
    for row in rows:
        task_id = row["id"]
        cron = row["cron"]
        if not cron.strip():
            continue
        try:
            trigger = CronTrigger.from_crontab(cron, timezone="Asia/Shanghai")
            state.scheduler.add_job(
                scheduled_task_run,
                trigger,
                id=f"{state.TASK_SCHED_PREFIX}{task_id}",
                args=[task_id],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            log("TASK", f"定时任务 [{row['name']}] 已注册：{cron}")
        except ValueError as exc:
            log("ERROR", f"任务 [{row['name']}] cron 无效：{cron}，{exc}")


async def scheduled_task_run(task_id: int) -> None:
    """Execute a scheduled task: sync + scan, optionally auto-delete."""
    with connect() as db:
        task = db.execute("select * from tasks where id=?", (task_id,)).fetchone()
    if not task or not task["enabled"]:
        return
    task_name = task["name"]
    mode = task["mode"]
    libs = [x for x in task["libraries"].split(",") if x]
    auto_delete = bool(task["auto_delete"])
    started = time.time()
    log("TASK", f"[{task_name}] 定时触发：模式={mode}，自动删除={auto_delete}")

    try:
        # 1. Sync metadata for specified libraries
        if libs:
            await sync_metadata(libs)
        else:
            await sync_metadata()

        # 2. Scan
        with connect() as db:
            prefs = get_config(db).get("prefs", {})
            data = run_scan(db, mode, libs, {"param_s": "100", "param_d": "0"}, prefs)

        found = sum(len(g["items"]) for g in data)
        deleted_count = 0

        # 3. Auto-delete if enabled (only items marked "delete")
        if auto_delete and found:
            delete_ids = []
            for group in data:
                for item in group["items"]:
                    if item.get("recommend_action") == "delete":
                        delete_ids.append(item["emby_id"])
            if delete_ids:
                queued = queue_deletes(delete_ids)
                deleted_count = queued
                log("TASK", f"[{task_name}] 自动入队删除 {queued} 条")

        duration = int((time.time() - started) * 1000)
        message = f"命中 {found} 条" + (f"，已入队删除 {deleted_count} 条" if auto_delete else "")
        with connect() as db:
            db.execute(
                "update tasks set last_status=?,last_found=?,last_deleted=?,last_duration_ms=?,last_message=?,updated_at=? where id=?",
                ("ok", found, deleted_count, duration, message, now_ts(), task_id),
            )

        # 4. Notify via webhook
        await notify(
            f"定时任务：{task_name}",
            f"模式：{mode}\n命中：{found} 条\n自动删除：{deleted_count} 条\n耗时：{duration}ms",
        )
        log("TASK", f"[{task_name}] 完成：{message}")
    except Exception as exc:
        with connect() as db:
            db.execute(
                "update tasks set last_status=?,last_message=?,updated_at=? where id=?",
                ("error", str(exc), now_ts(), task_id),
            )
        log("ERROR", f"[{task_name}] 执行失败：{exc}")
        await notify(f"定时任务失败：{task_name}", str(exc))
