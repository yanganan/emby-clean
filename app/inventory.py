"""Read-only source and media inventory helpers.

The helpers never delete or modify media. An unavailable path is represented
explicitly so a temporary FNOS/FUSE mount issue cannot become a delete signal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .rules import canonical_source_target


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_source(path: str) -> dict[str, Any]:
    """Inspect a local path or STRM stub without probing the remote URL."""
    raw_path = str(path or "")
    source_type = "strm" if raw_path.lower().endswith(".strm") else "local_file"
    if not raw_path:
        return {
            "source_type": "unknown",
            "source_ref": "",
            "status": "unavailable",
            "reason": "missing_path",
            "size": 0,
            "mtime": 0,
        }
    local = Path(raw_path)
    try:
        stat = local.stat()
    except OSError:
        return {
            "source_type": source_type,
            "source_ref": "",
            "status": "unavailable",
            "reason": "mount_or_path_unavailable",
            "size": 0,
            "mtime": 0,
        }
    if not local.is_file():
        return {
            "source_type": source_type,
            "source_ref": "",
            "status": "unavailable",
            "reason": "not_a_file",
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    if source_type == "strm":
        target = canonical_source_target(raw_path)
        if not target:
            return {
                "source_type": source_type,
                "source_ref": "",
                "status": "invalid",
                "reason": "invalid_strm_target",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        return {
            "source_type": source_type,
            "source_ref": target,
            "status": "readable",
            "reason": "",
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    return {
        "source_type": source_type,
        "source_ref": raw_path,
        "status": "readable",
        "reason": "",
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }
