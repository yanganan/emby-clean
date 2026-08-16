from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from .fingerprints import fingerprint_media
from .inventory import inspect_source
from .rules import (
    legacy_library_rules,
    normalize_variant_key as normalize_rule_key,
    western_match,
)
from .store import now_ts


AV_PATTERNS = [
    re.compile(r"\b(FC2)[-\s_]*(PPV)?[-\s_]*(\d{5,8})\b", re.I),
    re.compile(r"\b([A-Z]{2,6})[-\s_]*(\d{2,6})\b", re.I),
    re.compile(r"\b(\d{6}[-_]\d{2,4})\b", re.I),
]
QUALITY_WORDS = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|8k|uhd|fhd|hd|web[-_. ]?dl|bluray|bdrip|hdrip|x265|x264|hevc|h264|10bit|aac|ddp|remux)\b",
    re.I,
)
VARIANT_WORDS = re.compile(
    r"(?i)(?:^|[\s._-])(?:c|uc|u|uncensored|chinese|subtitle|sub|字幕|中字|无码|無碼|流出|泄露|leak|cd\d+|part\d+|disc\d+)(?=$|[\s._-])"
)
TAG_C_RE = re.compile(r"(?i)(?:^|[\s._-])c(?=$|[\s._-])")
TAG_UC_RE = re.compile(r"(?i)(?:^|[\s._-])uc(?=$|[\s._-])")


def item_from_emby(
    raw: dict[str, Any],
    library_map: dict[str, str],
    forced_library_id: str = "",
    forced_library_name: str = "",
) -> dict[str, Any]:
    sources = raw.get("MediaSources") or []
    source = sources[0] if sources else {}
    path = raw.get("Path") or source.get("Path") or ""
    streams = raw.get("MediaStreams") or source.get("MediaStreams") or []
    video = next((s for s in streams if s.get("Type") == "Video"), {})
    audio = next((s for s in streams if s.get("Type") == "Audio"), {})
    subtitle = next((s for s in streams if s.get("Type") == "Subtitle"), None)
    size = int(source.get("Size") or raw.get("Size") or 0)
    runtime_ticks = int(raw.get("RunTimeTicks") or source.get("RunTimeTicks") or 0)
    duration_seconds = runtime_ticks / 10_000_000 if runtime_ticks else 0
    width = int(video.get("Width") or 0)
    height = int(video.get("Height") or 0)
    parent_id = str(raw.get("ParentId") or "")
    library_id = str(forced_library_id or raw.get("TopParentId") or raw.get("SeasonId") or parent_id)
    provider_ids = raw.get("ProviderIds") or {}
    provider_key = "|".join(f"{k}:{v}" for k, v in sorted(provider_ids.items()) if v)
    tags = raw.get("Tags") or []
    image_tag = (raw.get("ImageTags") or {}).get("Primary") or ""
    emby_id = str(raw.get("Id"))
    is_media = 1 if (path or source.get("Path") or sources) and raw.get("Type") not in {"CollectionFolder", "UserView", "Folder"} else 0
    return {
        "emby_id": emby_id,
        "library_id": library_id,
        "library_name": forced_library_name or library_map.get(library_id, ""),
        "name": raw.get("Name") or "",
        "sort_name": raw.get("SortName") or raw.get("Name") or "",
        "path": path,
        "source_type": "strm" if path.lower().endswith(".strm") else ("local_file" if path else "unknown"),
        "source_ref": path,
        "source_status": "unknown",
        "source_reason": "",
        "source_size": size,
        "source_mtime": 0,
        "source_sha256": "",
        "image_hash": image_tag,
        "parent_id": parent_id,
        "series_id": str(raw.get("SeriesId") or ""),
        "series_name": raw.get("SeriesName") or "",
        "item_type": raw.get("Type") or "",
        "size": size,
        "runtime_ticks": runtime_ticks,
        "duration_seconds": duration_seconds,
        "width": width,
        "height": height,
        "resolution": height,
        "has_poster": 1 if image_tag else 0,
        "primary_image_tag": image_tag,
        "image_url": f"/emby-image/{emby_id}" if image_tag else "",
        "date_created": raw.get("DateCreated") or "",
        "is_media": is_media,
        "provider_key": provider_key,
        "tags": json.dumps(tags, ensure_ascii=False),
        "codec": video.get("Codec") or source.get("Codec") or "",
        "container": source.get("Container") or "",
        "bitrate": int(source.get("Bitrate") or 0),
        "audio_codec": audio.get("Codec") or "",
        "audio_channels": int(audio.get("Channels") or 0),
        "has_subtitle": 1 if subtitle else 0,
        "subtitle_lang": subtitle.get("Language") or "" if subtitle else "",
        "frame_rate": float(video.get("RealFrameRate") or video.get("AverageFrameRate") or 0),
        "bit_depth": int(video.get("BitDepth") or 0),
        "raw_json": json.dumps(raw, ensure_ascii=False),
        "updated_at": now_ts(),
    }


def upsert_items(db: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    keys = list(items[0].keys())
    cols = ",".join(keys)
    placeholders = ",".join("?" for _ in keys)
    updates = ",".join(f"{k}=excluded.{k}" for k in keys if k != "emby_id")
    sql = f"insert into media_items({cols}) values({placeholders}) on conflict(emby_id) do update set {updates}"
    db.executemany(sql, [tuple(item[k] for k in keys) for item in items])


def prune_missing(db: sqlite3.Connection, seen_ids: set[str], library_ids: list[str] | None = None) -> int:
    if not seen_ids:
        return 0
    if library_ids:
        placeholders = ",".join("?" for _ in library_ids)
        rows = db.execute(f"select emby_id from media_items where library_id in ({placeholders})", library_ids).fetchall()
    else:
        rows = db.execute("select emby_id from media_items").fetchall()
    missing = [r["emby_id"] for r in rows if r["emby_id"] not in seen_ids]
    if missing:
        db.executemany("delete from media_items where emby_id = ?", [(x,) for x in missing])
    return len(missing)


def scan(db: sqlite3.Connection, mode: str, libs: list[str], params: dict[str, str], prefs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = load_items(db, libs)
    ignored_items, ignored_groups = load_ignored(db, mode)

    # New "report" modes that don't need the is_media filter or grouping
    if mode in {"nometa", "nosub", "emptylib"}:
        return _scan_report(db, mode, libs, rows, ignored_items)
    if mode in {"image", "media_health", "strm_health", "source_dupe", "content_dupe"}:
        return _scan_integrity(db, mode, libs, rows, ignored_items)

    rows = [r for r in rows if r["emby_id"] not in ignored_items and r["is_media"]]
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    group_meta: dict[str, dict[str, Any]] = {}
    row_match_meta: dict[str, dict[str, Any]] = {}

    if mode == "av":
        for row in rows:
            match = match_row(row, mode)
            key = match["key"]
            if key:
                grouped[key].append(row)
                row_match_meta[row["emby_id"]] = match
                group_meta.setdefault(key, match_group_meta(match))
    elif mode == "smart":
        for row in rows:
            match = match_row(row, mode)
            key = match["key"]
            if key:
                grouped[key].append(row)
                row_match_meta[row["emby_id"]] = match
                group_meta.setdefault(key, match_group_meta(match))
    elif mode == "size":
        for row in rows:
            if row["size"]:
                grouped[str(row["size"])].append(row)
    elif mode == "duration":
        scope = params.get("duration_scope") or prefs.get("duration_scope", "dir")
        precision = params.get("duration_precision") or prefs.get("duration_precision", "second")
        for row in rows:
            if not row["duration_seconds"]:
                continue
            duration = round(float(row["duration_seconds"]), 2 if precision == "centisecond" else 0)
            parent = row["parent_id"] if scope == "library" else str(Path(row["path"] or "").parent)
            key = f"{parent}|{duration}"
            grouped[key].append(row)
            group_meta[key] = {
                "duration": duration,
                "duration_scope": scope,
                "duration_scope_label": "全库" if scope == "library" else "同目录",
                "duration_precision": precision,
                "duration_precision_label": "百分秒" if precision == "centisecond" else "整秒",
            }
    elif mode == "noposter":
        for row in rows:
            if not row["has_poster"]:
                grouped[f"noposter:{row['emby_id']}"].append(row)
    elif mode == "tiny":
        max_mb = float(params.get("param_s") or 100)
        for row in rows:
            if row["size"] and row["size"] <= max_mb * 1024 * 1024:
                grouped[f"tiny:{row['emby_id']}"].append(row)

    result = []
    for key, items in grouped.items():
        if key in ignored_groups:
            continue
        if mode in {"av", "smart", "size", "duration"} and len(items) < 2:
            continue
        normalized = [decorate_item(dict(item), mode, row_match_meta.get(item["emby_id"])) for item in items]
        apply_recommendations(normalized, mode, prefs, group_meta.get(key, {}))
        title = group_title(mode, key, normalized, group_meta.get(key, {}))
        result.append(
            {
                "title": title,
                "group_key": key,
                "ignore_scope": "group" if mode == "duration" else "item",
                "group_meta": group_meta.get(key, {}),
                "items": normalized,
                "summary": {
                    "keep": sum(1 for i in normalized if i.get("recommend_action") == "keep"),
                    "delete": sum(1 for i in normalized if i.get("recommend_action") == "delete"),
                    "review": sum(1 for i in normalized if i.get("recommend_action") == "review"),
                    "total": len(normalized),
                },
            }
        )
    result.sort(key=lambda g: (-len(g["items"]), g["title"]))
    return result


def _scan_report(
    db: sqlite3.Connection,
    mode: str,
    libs: list[str],
    rows: list[sqlite3.Row],
    ignored_items: set[str],
) -> list[dict[str, Any]]:
    """Report-style scans: each hit is its own group (1 item per group).

    - ``nometa``: media items missing provider IDs (no metadata provider)
    - ``nosub``: media items missing subtitles (no subtitle stream)
    - ``emptylib``: libraries with 0 media items
    """
    if mode == "emptylib":
        # Query libraries table for zero-count libs
        lib_rows = db.execute("select id, name, collection_type, item_count from libraries").fetchall()
        result = []
        for lib in lib_rows:
            media_count = db.execute(
                "select count(*) c from media_items where library_id=? and is_media=1",
                (lib["id"],),
            ).fetchone()["c"]
            if media_count == 0:
                item = {
                    "emby_id": lib["id"],
                    "name": lib["name"],
                    "library_id": lib["id"],
                    "library_name": lib["name"],
                    "path": "",
                    "item_type": "Library",
                    "size": 0,
                    "resolution": 0,
                    "duration": 0,
                    "has_poster": False,
                    "tag_c": False,
                    "tag_uc": False,
                    "tag_u": False,
                    "tag_crack": False,
                    "tag_leak": False,
                    "version_rank": 0,
                    "display_path": "",
                    "mode": mode,
                    "recommend_action": "",
                    "recommend_reason": "空媒体库，建议检查",
                }
                result.append({
                    "title": f"空媒体库：{lib['name']}",
                    "group_key": f"emptylib:{lib['id']}",
                    "ignore_scope": "group",
                    "group_meta": {"collection_type": lib["collection_type"]},
                    "items": [item],
                    "summary": {"keep": 0, "delete": 0, "review": 1, "total": 1},
                })
        return result

    # nometa / nosub: filter media items
    filtered = [r for r in rows if r["emby_id"] not in ignored_items and r["is_media"]]
    if libs:
        lib_set = set(libs)
        filtered = [r for r in filtered if r["library_id"] in lib_set]

    result = []
    for row in filtered:
        raw = row["raw_json"] if "raw_json" in row.keys() else ""
        hit = False
        reason = ""

        if mode == "nometa":
            provider_key = row["provider_key"] if "provider_key" in row.keys() else ""
            if not provider_key:
                hit = True
                reason = "缺少外部元数据 Provider ID（无 TMDB/IMDB 等）"

        elif mode == "nosub":
            # Check raw_json for subtitle streams
            try:
                data = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, TypeError):
                data = {}
            streams = data.get("MediaStreams") or []
            has_sub = any(s.get("Type") == "Subtitle" for s in streams)
            if not has_sub:
                hit = True
                reason = "无字幕轨道"

        if hit:
            item = decorate_item(dict(row), mode)
            item["recommend_action"] = ""
            item["recommend_reason"] = reason
            result.append({
                "title": reason,
                "group_key": f"{mode}:{row['emby_id']}",
                "ignore_scope": "item",
                "group_meta": {},
                "items": [item],
                "summary": {"keep": 0, "delete": 0, "review": 1, "total": 1},
            })

    result.sort(key=lambda g: g["title"])
    return result


def _scan_integrity(
    db: sqlite3.Connection,
    mode: str,
    libs: list[str],
    rows: list[sqlite3.Row],
    ignored_items: set[str],
) -> list[dict[str, Any]]:
    """Run read-only source, media and image checks.

    An unavailable mount is reported as an unavailable source, never as a
    missing/deletable media item.
    """
    filtered = [r for r in rows if r["emby_id"] not in ignored_items and r["is_media"]]
    if libs:
        lib_set = set(libs)
        filtered = [r for r in filtered if r["library_id"] in lib_set]
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    meta: dict[str, dict[str, Any]] = {}

    for row in filtered:
        key = ""
        reason = ""
        evidence: dict[str, Any] = {}
        matcher = mode
        if mode == "image":
            image_tag = row["primary_image_tag"] or ""
            if not image_tag:
                key = f"image:missing:{row['emby_id']}"
                reason = "缺失封面"
                matcher = "image_missing"
            else:
                key = f"image:tag:{image_tag}"
                evidence = {"primary_image_tag": image_tag}
                matcher = "image_exact_tag"
        elif mode == "media_health":
            missing = []
            if not row["path"]:
                missing.append("路径")
            if not row["size"]:
                missing.append("大小")
            if not row["duration_seconds"]:
                missing.append("时长")
            if not row["resolution"]:
                missing.append("分辨率")
            if missing:
                key = f"media_health:{row['emby_id']}"
                reason = "缺失媒体字段：" + "、".join(missing)
                evidence = {"missing_fields": missing}
                matcher = "media_metadata_health"
        elif mode == "content_dupe":
            fingerprint = fingerprint_media(row["path"] or "", row["item_type"] or "")
            if fingerprint["status"] == "ready":
                key = f"content:{fingerprint['algorithm']}:{fingerprint['value']}"
                evidence = {"algorithm": fingerprint["algorithm"], "fingerprint": fingerprint["value"]}
                matcher = "content_fingerprint"
                db.execute(
                    """
                    insert into fingerprints(emby_id,kind,algorithm,value,source_ref,source_mtime,source_size,status,created_at,updated_at)
                    values(?,?,?,?,?,?,?,?,?,?)
                    on conflict(emby_id,kind,algorithm) do update set
                      value=excluded.value,source_ref=excluded.source_ref,source_mtime=excluded.source_mtime,
                      source_size=excluded.source_size,status=excluded.status,updated_at=excluded.updated_at
                    """,
                    (row["emby_id"], "content", fingerprint["algorithm"], fingerprint["value"], row["path"] or "", 0, row["size"] or 0, "ready", now_ts(), now_ts()),
                )
            else:
                key = f"content_health:{row['emby_id']}"
                reason = "内容指纹不可用：" + fingerprint["reason"]
                evidence = {"status": fingerprint["status"], "reason": fingerprint["reason"]}
                matcher = "content_fingerprint_health"
        else:
            inventory = inspect_source(row["path"] or "")
            db.execute(
                """
                update media_items
                set source_type=?,source_ref=?,source_status=?,source_reason=?,source_size=?,source_mtime=?
                where emby_id=?
                """,
                (
                    inventory["source_type"], inventory["source_ref"], inventory["status"],
                    inventory["reason"], inventory["size"], inventory["mtime"], row["emby_id"],
                ),
            )
            if inventory["status"] != "readable":
                if mode == "strm_health" or inventory["source_type"] == "strm":
                    key = f"strm_health:{row['emby_id']}"
                    reason = "STRM/源路径不可用：" + (inventory["reason"] or inventory["status"])
                    evidence = {"status": inventory["status"], "reason": inventory["reason"]}
                    matcher = "strm_source_health"
            elif mode == "source_dupe" and inventory["source_ref"]:
                key = f"source:{inventory['source_ref']}"
                evidence = {"source_ref": inventory["source_ref"]}
                matcher = "source_exact_reference"
                db.execute(
                    """
                    insert into fingerprints(emby_id,kind,algorithm,value,source_ref,source_mtime,source_size,status,created_at,updated_at)
                    values(?,?,?,?,?,?,?,?,?,?)
                    on conflict(emby_id,kind,algorithm) do update set
                      value=excluded.value,source_ref=excluded.source_ref,source_mtime=excluded.source_mtime,
                      source_size=excluded.source_size,status=excluded.status,updated_at=excluded.updated_at
                    """,
                    (row["emby_id"], "source", "canonical_ref", inventory["source_ref"], inventory["source_ref"], inventory["mtime"], inventory["size"], "ready", now_ts(), now_ts()),
                )
        if key:
            grouped[key].append(row)
            meta.setdefault(
                key,
                {
                    "matcher": matcher,
                    "confidence": "exact" if matcher in {"image_exact_tag", "source_exact_reference"} else "review",
                    "evidence": evidence,
                },
            )

    result = []
    for key, items in grouped.items():
        if mode in {"image", "source_dupe", "content_dupe"} and len(items) < 2 and not key.startswith(("image:missing:", "strm_health:", "content_health:")):
            continue
        normalized = []
        for raw in items:
            item = decorate_item(dict(raw), mode)
            item["recommend_action"] = "review"
            item["recommend_reason"] = (
                "发现重复封面/源引用/内容指纹，需确认是否为同一媒体"
                if len(items) > 1 else "".join(meta.get(key, {}).get("evidence", {}).get("missing_fields", [])) or "需要检查"
            )
            normalized.append(item)
        result.append(
            {
                "title": integrity_group_title(mode, key, normalized, meta.get(key, {})),
                "group_key": key,
                "ignore_scope": "item",
                "group_meta": meta.get(key, {}),
                "items": normalized,
                "summary": {"keep": 0, "delete": 0, "review": len(normalized), "total": len(normalized)},
            }
        )
    result.sort(key=lambda group: (group["title"], group["group_key"]))
    return result


def integrity_group_title(mode: str, key: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    if mode == "image" and key.startswith("image:missing:"):
        return "缺失封面"
    if mode == "media_health":
        return "媒体字段缺失"
    if mode == "strm_health":
        return "STRM/源路径不可用（不等于资源缺失）"
    if mode == "source_dupe":
        return "相同源引用"
    if mode == "content_dupe":
        return "相同内容指纹"
    return key


def load_items(db: sqlite3.Connection, libs: list[str]) -> list[sqlite3.Row]:
    if libs:
        placeholders = ",".join("?" for _ in libs)
        return db.execute(
            f"select rowid as id,* from media_items where library_id in ({placeholders}) or parent_id in ({placeholders})",
            libs + libs,
        ).fetchall()
    return db.execute("select rowid as id,* from media_items").fetchall()


def load_ignored(db: sqlite3.Connection, mode: str) -> tuple[set[str], set[str]]:
    rows = db.execute("select emby_id, group_key, mode, scope from ignore_items where mode in (?, 'global')", (mode,)).fetchall()
    return {r["emby_id"] for r in rows if r["emby_id"]}, {r["group_key"] for r in rows if r["group_key"]}


def av_key(row: sqlite3.Row) -> str:
    text = f"{row['name']} {row['path']}"
    for pattern in AV_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parts = [p for p in match.groups() if p]
        if parts and parts[0].isdigit():
            return parts[0].upper().replace("_", "-")
        if parts and parts[0].upper() == "FC2" and len(parts) >= 2:
            number = parts[-1]
            return f"FC2-PPV-{number}" if len(parts) == 3 else f"FC2-{number}"
        return "-".join(parts).upper().replace("_", "-")
    return ""


def match_row(row: Any, mode: str) -> dict[str, Any]:
    """Return a compatibility-aware match result for one media row."""
    if legacy_library_rules(row):
        key = av_key(row) if mode == "av" else _legacy_smart_key(row)
        return {
            "key": key,
            "matcher": "legacy_av" if mode == "av" else "legacy_smart",
            "confidence": "legacy",
            "evidence": {"library_name": row["library_name"] if "library_name" in row.keys() else ""},
            "source_type": "strm" if str(row["path"] or "").lower().endswith(".strm") else "local_file",
            "profile": "legacy",
        }
    result = western_match(row, mode)
    result["profile"] = "modern"
    return result


def match_group_meta(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "matcher": match.get("matcher", "none"),
        "confidence": match.get("confidence", "none"),
        "evidence": match.get("evidence", {}),
        "source_type": match.get("source_type", "unknown"),
        "profile": match.get("profile", "modern"),
    }


def smart_key(row: sqlite3.Row) -> str:
    return match_row(row, "smart")["key"]


def _legacy_smart_key(row: Any) -> str:
    if row["provider_key"]:
        return "provider:" + row["provider_key"]
    name = row["series_name"] or row["sort_name"] or row["name"]
    return normalize_rule_key(name)


def normalize_variant_key(text: str) -> str:
    return normalize_rule_key(text)


def decorate_item(item: dict[str, Any], mode: str, match: dict[str, Any] | None = None) -> dict[str, Any]:
    tags = json.loads(item.get("tags") or "[]")
    name_path = f"{item.get('name','')} {item.get('path','')}".lower()
    item["tag_c"] = bool(TAG_C_RE.search(name_path)) or "[c]" in name_path or "中文字幕" in name_path or any(str(t).lower() in {"c", "中字", "中文字幕"} for t in tags)
    item["tag_uc"] = bool(TAG_UC_RE.search(name_path)) or "[uc]" in name_path or "uncensored" in name_path or any(str(t).lower() in {"uc", "uncensored"} for t in tags)
    item["tag_u"] = "[u]" in name_path or any(str(t).lower() == "u" for t in tags)
    item["tag_crack"] = any(x in name_path for x in ["破解", "crack", "破解版"])
    item["tag_leak"] = any(x in name_path for x in ["流出", "泄露", "leak"])
    item["version_rank"] = version_rank(item)
    item["has_poster"] = bool(item.get("has_poster"))
    item["size"] = int(item.get("size") or 0)
    item["resolution"] = int(item.get("resolution") or 0)
    item["duration"] = float(item.get("duration_seconds") or 0)
    item["display_path"] = str(Path(item.get("path") or "").parent) + "/" if item.get("path") else ""
    item["mode"] = mode
    if match:
        item["match_matcher"] = match.get("matcher", "none")
        item["match_confidence"] = match.get("confidence", "none")
        item["match_evidence"] = match.get("evidence", {})
        item["source_type"] = match.get("source_type", "unknown")
    # Preserve media info fields for frontend display
    item.pop("raw_json", None)
    item.pop("tags", None)
    return item


def apply_recommendations(
    items: list[dict[str, Any]],
    mode: str,
    prefs: dict[str, Any],
    group_meta: dict[str, Any] | None = None,
) -> None:
    group_meta = group_meta or {}
    if group_meta.get("profile") == "modern":
        confidence = group_meta.get("confidence", "none")
        if confidence not in {"exact", "high"}:
            for item in items:
                item["recommend_action"] = "review"
                item["recommend_reason"] = "中/低置信度候选，仅建议人工复核"
            return
        has_quality = any(
            (item.get("resolution") or 0) or (item.get("size") or 0) or (item.get("duration") or 0)
            for item in items
        )
        if not has_quality and group_meta.get("source_type") == "strm" and confidence != "exact":
            for item in items:
                item["recommend_action"] = "review"
                item["recommend_reason"] = "STRM 缺少大小/时长/分辨率，无法安全选优"
            return
        keep_id = pick_quality(items)
        for item in items:
            if item["emby_id"] == keep_id:
                item["recommend_action"] = "keep"
                item["recommend_reason"] = "按可用媒体质量与来源信息建议保留"
            else:
                item["recommend_action"] = "delete"
                item["recommend_reason"] = "同一高置信度媒体候选组"
        return
    keep_id = ""
    if mode == "av":
        keep_id = pick_best_version(items)
    elif mode == "smart":
        keep_id = pick_resolution(items, highest=prefs.get("smart_keep", "reso_max") != "reso_min")
    elif mode == "size":
        keep_id = pick_by_name_path(items, prefs.get("size_keep", "path_long"))
    elif mode == "duration":
        keep_id = pick_largest(items) if prefs.get("duration_keep") == "max" else pick_smallest(items)
    if not keep_id and items:
        keep_id = pick_largest(items)
    for item in items:
        if mode == "av" and item.get("tag_leak"):
            item["recommend_action"] = "review"
            item["recommend_reason"] = "命中“流出/泄露”，不自动勾选，请人工确认"
            continue
        if keep_id and item["emby_id"] == keep_id:
            item["recommend_action"] = "keep"
            item["recommend_reason"] = "按优先级建议保留：破解-C > C > 破解 > 无标签"
        else:
            item["recommend_action"] = "delete" if mode in {"av", "smart", "size", "duration"} else ""
            item["recommend_reason"] = "同组重复项" if item["recommend_action"] == "delete" else ""


def version_rank(item: dict[str, Any]) -> int:
    if item.get("tag_crack") and item.get("tag_c"):
        return 4
    if item.get("tag_c"):
        return 3
    if item.get("tag_crack"):
        return 2
    return 1


def pick_best_version(items: list[dict[str, Any]]) -> str:
    candidates = [item for item in items if not item.get("tag_leak")]
    if not candidates:
        return ""
    return max(
        candidates,
        key=lambda i: (
            i.get("version_rank") or 0,
            i.get("resolution") or 0,
            i.get("size") or 0,
            i.get("date_created") or "",
        ),
    )["emby_id"]


def pick_by_tag(items: list[dict[str, Any]], rule: str) -> str:
    key = {"tag_uc": "tag_uc", "tag_c": "tag_c", "tag_raw": ""}.get(rule, "tag_uc")
    if not key:
        raw = [i for i in items if not i["tag_c"] and not i["tag_uc"] and not i["tag_u"]]
        return pick_largest(raw)
    return pick_largest([i for i in items if i.get(key)])


def pick_largest(items: list[dict[str, Any]]) -> str:
    return max(items, key=lambda i: i.get("size") or 0)["emby_id"] if items else ""


def pick_smallest(items: list[dict[str, Any]]) -> str:
    return min(items, key=lambda i: i.get("size") or 0)["emby_id"] if items else ""


def pick_resolution(items: list[dict[str, Any]], highest: bool = True) -> str:
    fn = max if highest else min
    return fn(items, key=lambda i: (i.get("resolution") or 0, i.get("size") or 0))["emby_id"] if items else ""


def pick_quality(items: list[dict[str, Any]]) -> str:
    """Pick a best candidate without treating missing metadata as quality."""
    return max(
        items,
        key=lambda i: (
            i.get("resolution") or 0,
            i.get("bitrate") or 0,
            i.get("duration") or 0,
            i.get("size") or 0,
            len(i.get("path") or ""),
        ),
    )["emby_id"] if items else ""


def pick_by_name_path(items: list[dict[str, Any]], rule: str) -> str:
    field = "name" if "name" in rule else "path"
    fn = max if "long" in rule else min
    return fn(items, key=lambda i: len(i.get(field) or ""))["emby_id"] if items else ""


def group_title(mode: str, key: str, items: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    if mode == "duration":
        return f"时长重复：{meta.get('duration')} 秒 · {meta.get('duration_scope_label', '')}"
    if mode == "size":
        return f"同大小：{human_bytes(items[0].get('size') or 0)}"
    if mode == "noposter":
        return "缺失封面"
    if mode == "tiny":
        return "极小文件"
    return key.replace("FC2-PPV-", "PPV-") if key.startswith("FC2-PPV-") else key


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(value or 0)
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024
        idx += 1
    return f"{n:.1f} {units[idx]}" if idx else f"{int(n)} B"
