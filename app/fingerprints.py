"""Optional content fingerprints with explicit unavailable states."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .inventory import sha256_file

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts", ".webm"}


def average_image_hash(path: str | Path) -> str:
    try:
        from PIL import Image
    except ImportError:
        return ""
    try:
        image = Image.open(path).convert("L").resize((8, 8))
        pixels = list(image.getdata())
    except Exception:
        return ""
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def video_sample_hash(path: str | Path) -> str:
    """Hash sampled decoded frames when ffmpeg is available."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ""
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-v", "error", "-i", str(path),
                "-vf", "select='not(mod(n,300))',scale=16:16",
                "-frames:v", "5", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
            ],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0 or not proc.stdout:
        return ""
    return hashlib.sha256(proc.stdout).hexdigest()


def fingerprint_media(path: str, item_type: str = "") -> dict[str, Any]:
    raw_path = str(path or "")
    if not raw_path or raw_path.lower().endswith(".strm") or not Path(raw_path).is_file():
        return {"status": "unavailable", "reason": "path_unavailable", "algorithm": "", "value": ""}
    suffix = Path(raw_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        value = average_image_hash(raw_path)
        if value:
            return {"status": "ready", "reason": "", "algorithm": "ahash", "value": value}
    if suffix in VIDEO_EXTENSIONS or item_type in {"Movie", "Episode", "Video"}:
        value = video_sample_hash(raw_path)
        if value:
            return {"status": "ready", "reason": "", "algorithm": "video_sample_sha256", "value": value}
    try:
        return {"status": "ready", "reason": "", "algorithm": "sha256", "value": sha256_file(raw_path)}
    except OSError:
        return {"status": "unavailable", "reason": "read_failed", "algorithm": "", "value": ""}
