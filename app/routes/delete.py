"""Delete-queue routes: enqueue, list, retry, clear."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..models import DeleteRequest
from ..services.delete_service import (
    ensure_delete_worker,
    is_delete_worker_running,
    queue_deletes,
)
from ..services.logging_service import log
from ..store import connect

router = APIRouter()


@router.post("/api/delete")
async def dele_post(req: DeleteRequest) -> dict[str, Any]:
    queued = queue_deletes(req.ids)
    skipped = len(req.ids) - queued
    log("DELETE", f"加入删除队列：新增 {queued} 条，跳过 {skipped} 条")
    return {"status": "queued", "queued": queued, "skipped": skipped, "message": f"已加入删除队列 {queued} 条"}


@router.get("/api/delete-queue")
async def delete_queue_get() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            "select id,emby_id,name,status,error,retry_count,created_at,started_at,finished_at from delete_queue order by id asc limit 200"
        ).fetchall()
        counts = {
            row["status"]: row["c"]
            for row in db.execute("select status,count(*) c from delete_queue group by status").fetchall()
        }
    return {"running": is_delete_worker_running(), "counts": counts, "items": [dict(row) for row in rows]}


@router.post("/api/delete-queue/retry")
async def delete_retry() -> dict[str, Any]:
    """Reset all failed queue items to pending for re-processing."""
    with connect() as db:
        count = db.execute(
            "update delete_queue set status='pending', error=NULL where status='failed'"
        ).rowcount
    if count:
        ensure_delete_worker()
    log("DELETE", f"手动重试 {count} 条失败记录")
    return {"status": "ok", "retried": count}


@router.post("/api/delete-queue/clear")
async def delete_clear() -> dict[str, Any]:
    """Clear all done/failed items from the queue."""
    with connect() as db:
        count = db.execute(
            "delete from delete_queue where status in ('done','failed')"
        ).rowcount
    return {"status": "ok", "cleared": count}
