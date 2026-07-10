"""Pydantic request models used across the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ConfigRequest(BaseModel):
    host: str | None = ""
    user: str | None = ""
    pwd: str | None = ""
    webhook: str | None = ""
    cron_sync: str | None = ""
    prefs: dict[str, Any] | None = None


class DeleteRequest(BaseModel):
    ids: list[str]


class RefreshRequest(BaseModel):
    ids: list[str]


class IgnoreRequest(BaseModel):
    ids: list[str] = []
    mode: str
    group_keys: list[str] = []


class TaskReq(BaseModel):
    name: str
    mode: str
    cron: str
    libraries: str
    enabled: bool = True
    auto_delete: bool = False
