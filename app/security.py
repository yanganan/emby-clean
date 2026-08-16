"""Security and destructive-action policy helpers."""

from __future__ import annotations

import hmac


def api_key_is_valid(provided: str, configured: str) -> bool:
    if not provided or not configured:
        return False
    return hmac.compare_digest(str(provided), str(configured))


def delete_request_decision(
    *,
    confirm: bool,
    dry_run: bool,
    source_type: str,
    object_type: str = "emby_item",
) -> dict[str, str]:
    if dry_run or not confirm:
        return {"status": "dry_run", "reason": "需要显式 confirm=true 且 dry_run=false"}
    if source_type in {"strm", "remote_reference"}:
        return {"status": "rejected", "reason": "远程/STRM 源文件禁止隐式删除"}
    if object_type != "emby_item":
        return {"status": "rejected", "reason": "当前只允许显式处理 Emby 条目"}
    return {"status": "approved", "reason": "已通过显式确认"}
