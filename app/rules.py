"""Library-aware matching rules for non-legacy media libraries.

Japanese and FC2 matching remains in :mod:`app.scanner` for compatibility.
This module deliberately returns evidence instead of only a string key so the
caller can apply confidence and deletion safety gates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


KNOWN_EXTENSIONS = re.compile(r"\.(?:strm|mp4|mkv|avi|mov|wmv|ts|m4v|webm)$", re.I)
QUALITY_WORDS = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|8k|uhd|fhd|hd|web[-_. ]?dl|bluray|bdrip|hdrip|x265|x264|hevc|h264|10bit|aac|ddp|remux)\b",
    re.I,
)
VARIANT_WORDS = re.compile(
    r"(?i)(?:^|[\s._-])(?:c|uc|u|uncensored|chinese|subtitle|sub|字幕|中字|无码|無碼|流出|泄露|leak|cd\d+|part\d+|disc\d+)(?=$|[\s._-])"
)
SCENE_CODE = re.compile(r"(?<!\d)(\d{2,4}(?:[._-]\d{1,4}){2,3})(?!\d)")
RELEASE_DATE_CODE = re.compile(r"^(?:\d{2}|\d{4})\.(?:0[1-9]|1[0-2])\.(?:0[1-9]|[12]\d|3[01])$")
LEADING_NUMBER = re.compile(r"^\s*(\d{1,5})(?=[\s._-]|$)")
GENERIC_CONTEXT = {
    "media", "video", "videos", "movie", "movies", "tv", "series", "shows",
    "strm", "1080p", "2160p", "4k", "同步文件夹", "欧美合集", "正式", "不正式",
}


def value(row: Any, key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def legacy_library_rules(row: Any) -> bool:
    """Keep the proven Japanese/FC2 matcher path unchanged."""
    name = str(value(row, "library_name", "")).strip().lower()
    return "日本" in name or name == "fc2" or name.startswith("fc2 ")


def strip_known_extension(text: str) -> str:
    text = str(text or "")
    return KNOWN_EXTENSIONS.sub("", text)


def normalize_variant_key(text: str) -> str:
    """Normalize a title without treating arbitrary dots as a file extension."""
    text = strip_known_extension(text)
    text = QUALITY_WORDS.sub(" ", text)
    text = VARIANT_WORDS.sub(" ", text)
    text = re.sub(
        r"(?i)[\[\(【（][^\]\)】）]*(?:4k|1080p|720p|uc|中字|字幕|无码|流出|泄露)[^\]\)】）]*[\]\)】）]",
        " ",
        text,
    )
    text = re.sub(r"(?i)(?:[-_.\s]+(?:c|uc|u|4k|1080p|720p|cd\d+|part\d+|disc\d+))+$", " ", text)
    return re.sub(r"[\W_]+", " ", text, flags=re.U).strip().lower()


def normalize_site(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "").strip().lower())
    text = re.sub(r"[\\/]+", " ", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip(" ._-" )


def path_context(path: str) -> str:
    parts = [p for p in Path(str(path or "")).parent.parts if p]
    for part in reversed(parts):
        normalized = normalize_site(part)
        if normalized and normalized not in GENERIC_CONTEXT and not normalized.isdigit():
            if any(ch.isalpha() for ch in normalized):
                return normalized
    return ""


def canonical_source_target(path: str) -> str:
    """Read a local STRM target when the media mount is available."""
    if not str(path or "").lower().endswith(".strm"):
        return ""
    try:
        target = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, UnicodeError):
        return ""
    if not target or not re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I):
        return ""
    parsed = urlsplit(target)
    # Keep content-affecting query parameters; only remove fragments and sort
    # query pairs so equivalent URL text produces the same key.
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, ""))


def source_type(row: Any) -> str:
    path = str(value(row, "path", ""))
    if path.lower().endswith(".strm"):
        return "strm"
    if path:
        return "local_file"
    return "unknown"


def _suffix_after_code(text: str, raw_code: str) -> str:
    """Return the text after a scene code, accepting dot/underscore/hyphen separators."""
    pattern = re.escape(str(raw_code or "")).replace(r"\.", r"[._-]")
    match = re.search(pattern, str(text or ""), re.I)
    return str(text or "")[match.end():] if match else ""


def _scene_identity_component(text: str) -> str:
    return re.sub(r"\s+", "-", str(text or "").strip()) or "unknown"


def _release_date_match(row: Any, stem: str, site: str, raw_code: str, code: str) -> dict[str, Any]:
    """Use title + performer context when dotted numbers are release dates.

    Many western libraries use ``YY.MM.DD`` in the filename. It is a release
    date, not a unique scene id, so site + date alone can merge unrelated
    scenes. Performer context comes from the scene directory and prevents
    same-title releases with different performers from becoming duplicates.
    """
    title_signature = normalize_variant_key(_suffix_after_code(stem, raw_code))
    scene_dir = Path(str(value(row, "path", ""))).parent.name
    performer_signature = normalize_variant_key(_suffix_after_code(scene_dir, raw_code))
    if performer_signature == normalize_site(site):
        performer_signature = ""
    if not title_signature and not performer_signature:
        return {
            "key": "",
            "matcher": "western_release_date_unidentified",
            "confidence": "none",
            "evidence": {"site": site, "scene_code": code, "code_kind": "release_date"},
            "source_type": source_type(row),
        }
    confidence = "medium"
    identity_kind = "performer" if performer_signature else "title"
    identity = performer_signature or title_signature
    key = f"western:{site}:{code}:release:{identity_kind}:{_scene_identity_component(identity)}"
    return {
        "key": key,
        "matcher": "western_release_date",
        "confidence": confidence,
        "evidence": {
            "site": site,
            "scene_code": code,
            "code_kind": "release_date",
            "title_signature": title_signature,
            "performer_signature": performer_signature,
            "name": str(value(row, "name", "")),
        },
        "source_type": source_type(row),
    }


def western_match(row: Any, mode: str = "smart") -> dict[str, Any]:
    """Return a structured match result for non-legacy libraries."""
    name = str(value(row, "name", ""))
    path = str(value(row, "path", ""))
    stem = strip_known_extension(Path(name or path).name)
    source = source_type(row)
    target = canonical_source_target(path)
    if target:
        return {
            "key": f"western:strm:{target}",
            "matcher": "strm_exact_target",
            "confidence": "exact",
            "evidence": {"source_target": target},
            "source_type": source,
        }

    scene_match = SCENE_CODE.search(stem)
    if scene_match:
        prefix = stem[: scene_match.start()].rstrip(" ._-")
        site_match = re.search(r"([A-Za-z][A-Za-z0-9]*|[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*)$", prefix)
        site = normalize_site(site_match.group(1) if site_match else path_context(path))
        if site:
            raw_code = scene_match.group(1)
            code = re.sub(r"[-_]", ".", raw_code)
            if RELEASE_DATE_CODE.fullmatch(code):
                return _release_date_match(row, stem, site, raw_code, code)
            return {
                "key": f"western:{site}:{code}",
                "matcher": "western_scene_code",
                "confidence": "high",
                "evidence": {"site": site, "scene_code": code, "name": name},
                "source_type": source,
            }

    leading = LEADING_NUMBER.match(stem)
    context = path_context(path)
    if leading and context:
        code = leading.group(1)
        return {
            "key": f"western:{context}:{code}",
            "matcher": "western_context_number",
            "confidence": "high",
            "evidence": {"context": context, "scene_code": code, "name": name},
            "source_type": source,
        }

    if mode == "smart":
        title = normalize_variant_key(stem)
        if context and len(title) >= 5:
            return {
                "key": f"western:title:{context}:{title}",
                "matcher": "western_title_context",
                "confidence": "medium",
                "evidence": {"context": context, "normalized_title": title, "name": name},
                "source_type": source,
            }
    return {
        "key": "",
        "matcher": "none",
        "confidence": "none",
        "evidence": {},
        "source_type": source,
    }
