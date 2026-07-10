"""Shared mutable state and constants for the Emby Clean application.

Centralising these here avoids circular imports between routes and services
while keeping a single source of truth for locks, the scheduler, and the
in-memory log buffer.
"""
from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# In-memory log ring buffer (mirrors the DB ``logs`` table for quick access)
LOGS: list[str] = []

# Serialisation locks so sync / delete never run concurrently with themselves
SYNC_LOCK = asyncio.Lock()
DELETE_LOCK = asyncio.Lock()

# The currently-running delete-worker task (or ``None`` when idle)
DELETE_TASK: asyncio.Task | None = None

# Delete-worker tuning constants
DELETE_CONFIRM_TIMEOUT = 90
DELETE_CONFIRM_INTERVAL = 3
DELETE_SETTLE_SECONDS = 5

# Scheduler job-id prefixes
SYNC_JOB_ID = "sync_media_libraries"
TASK_SCHED_PREFIX = "task_"

# The shared APScheduler instance (started/stopped from ``main.startup``)
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
