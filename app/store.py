from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


DATA_DIR = Path(os.getenv("EMBY_CLEAN_DATA", "./data")).resolve()
DB_PATH = DATA_DIR / "emby_clean.db"
BACKUP_PATH = DATA_DIR / "config_backup.json"

# Config keys that are safe to backup/restore
_BACKUP_CONFIG_KEYS = ["host", "user", "pwd", "access_token", "user_id", "webhook", "cron_sync", "prefs"]
_BACKUP_STAT_KEYS = ["server_id", "server_name", "server_ver", "user_name", "cleaned_count", "saved_space"]


DEFAULT_PREFS = {
    "av_keep_priority": "tag_uc",
    "size_keep": "path_long",
    "duration_keep": "min",
    "duration_scope": "dir",
    "duration_precision": "second",
    "smart_keep": "reso_max",
    "confirm_batch": "true",
    "auto_refresh_library": True,
    "delete_retry_max": 3,
    "delete_retry_delay": 10,
}


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            create table if not exists config (
              key text primary key,
              value text not null
            );

            create table if not exists media_items (
              emby_id text primary key,
              library_id text,
              library_name text,
              name text,
              sort_name text,
              path text,
              parent_id text,
              series_id text,
              series_name text,
              item_type text,
              size integer default 0,
              runtime_ticks integer default 0,
              duration_seconds real default 0,
              width integer default 0,
              height integer default 0,
              resolution integer default 0,
              has_poster integer default 0,
              primary_image_tag text,
              image_url text,
              date_created text,
              is_media integer default 0,
              provider_key text,
              tags text,
              codec text,
              container text,
              bitrate integer default 0,
              audio_codec text,
              audio_channels integer default 0,
              has_subtitle integer default 0,
              subtitle_lang text,
              frame_rate real default 0,
              bit_depth integer default 0,
              raw_json text,
              updated_at integer
            );

            create table if not exists libraries (
              id text primary key,
              name text not null,
              collection_type text,
              parent_id text,
              raw_json text,
              item_count integer default 0,
              api_count integer default 0,
              updated_at integer
            );

            create table if not exists logs (
              id integer primary key autoincrement,
              line text not null,
              created_at integer not null
            );

            create table if not exists delete_queue (
              id integer primary key autoincrement,
              emby_id text not null,
              name text,
              path text,
              size integer default 0,
              status text not null default 'pending',
              error text,
              retry_count integer default 0,
              created_at integer not null,
              started_at integer,
              finished_at integer
            );

            create table if not exists ignore_items (
              id integer primary key autoincrement,
              emby_id text,
              group_key text,
              mode text not null,
              scope text not null default 'item',
              name text,
              path text,
              created_at integer not null
            );

            create table if not exists tasks (
              id integer primary key autoincrement,
              name text not null,
              mode text not null,
              cron text not null,
              libraries text not null default '',
              enabled integer not null default 1,
              auto_delete integer not null default 0,
              last_status text,
              last_found integer default 0,
              last_deleted integer default 0,
              last_duration_ms integer default 0,
              last_message text,
              updated_at integer
            );

            create table if not exists kv_stats (
              key text primary key,
              value text not null
            );
            """
        )
        ensure_column(db, "media_items", "date_created", "text")
        ensure_column(db, "media_items", "primary_image_tag", "text")
        ensure_column(db, "media_items", "image_url", "text")
        ensure_column(db, "media_items", "is_media", "integer default 0")
        ensure_column(db, "media_items", "codec", "text")
        ensure_column(db, "media_items", "container", "text")
        ensure_column(db, "media_items", "bitrate", "integer default 0")
        ensure_column(db, "media_items", "audio_codec", "text")
        ensure_column(db, "media_items", "audio_channels", "integer default 0")
        ensure_column(db, "media_items", "has_subtitle", "integer default 0")
        ensure_column(db, "media_items", "subtitle_lang", "text")
        ensure_column(db, "media_items", "frame_rate", "real default 0")
        ensure_column(db, "media_items", "bit_depth", "integer default 0")
        ensure_column(db, "libraries", "api_count", "integer default 0")
        ensure_column(db, "delete_queue", "retry_count", "integer default 0")
        ensure_column(db, "tasks", "auto_delete", "integer not null default 0")
        ensure_column(db, "tasks", "last_deleted", "integer default 0")
        db.execute("update libraries set api_count = item_count where coalesce(api_count,0) = 0")
        db.execute(
            """
            update media_items
            set is_media = 1
            where coalesce(is_media,0) = 0
              and item_type in ('Movie','Episode','Video')
            """
        )
        db.execute(
            """
            update media_items
            set image_url = '/emby-image/' || emby_id
            where coalesce(image_url,'') = ''
              and coalesce(has_poster,0) = 1
            """
        )
        if get_config_value(db, "prefs") is None:
            set_config_value(db, "prefs", DEFAULT_PREFS)


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def get_config_value(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("select value from config where key = ?", (key,)).fetchone()
    return decode(row["value"], default) if row else default


def set_config_value(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        "insert into config(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
        (key, encode(value)),
    )


def get_config(db: sqlite3.Connection, include_secret: bool = False) -> dict[str, Any]:
    cfg = {
        "host": get_config_value(db, "host", ""),
        "user": get_config_value(db, "user", ""),
        "webhook": get_config_value(db, "webhook", ""),
        "cron_sync": get_config_value(db, "cron_sync", ""),
        "prefs": {**DEFAULT_PREFS, **(get_config_value(db, "prefs", {}) or {})},
    }
    if include_secret:
        cfg["pwd"] = get_config_value(db, "pwd", "")
        cfg["access_token"] = get_config_value(db, "access_token", "")
        cfg["user_id"] = get_config_value(db, "user_id", "")
    return cfg


def set_stat(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        "insert into kv_stats(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
        (key, encode(value)),
    )


def get_stat(db: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = db.execute("select value from kv_stats where key = ?", (key,)).fetchone()
    return decode(row["value"], default) if row else default


def now_ts() -> int:
    return int(time.time())


def ensure_column(db: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    rows = db.execute(f"pragma table_info({table})").fetchall()
    if column not in {r["name"] for r in rows}:
        db.execute(f"alter table {table} add column {column} {ddl}")


# ---------------------------------------------------------------------------
#  Config backup / restore (JSON file at DATA_DIR/config_backup.json)
#  Purpose: survive DB loss when container is recreated without volume mount.
#  The backup file lives in the same /data directory, so it persists as long
#  as the volume is mounted.  It also gives users a portable export they can
#  download and re-import after a fresh deployment.
# ---------------------------------------------------------------------------

def backup_config() -> bool:
    """Export config + stats + tasks to BACKUP_PATH. Returns True on success."""
    try:
        with connect() as db:
            payload: dict[str, Any] = {"version": 1, "exported_at": now_ts()}
            # Config key-values
            config: dict[str, Any] = {}
            for key in _BACKUP_CONFIG_KEYS:
                val = get_config_value(db, key)
                if val is not None:
                    config[key] = val
            payload["config"] = config
            # Stats
            stats: dict[str, Any] = {}
            for key in _BACKUP_STAT_KEYS:
                val = get_stat(db, key)
                if val is not None:
                    stats[key] = val
            payload["stats"] = stats
            # Tasks
            task_rows = db.execute("select * from tasks order by id").fetchall()
            payload["tasks"] = [dict(r) for r in task_rows]
        BACKUP_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def restore_config() -> bool:
    """Import config from BACKUP_PATH if the DB has no config. Returns True on success."""
    if not BACKUP_PATH.exists():
        return False
    try:
        payload = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
        config = payload.get("config", {})
        if not config:
            return False
        with connect() as db:
            # Only restore if DB has no host configured (fresh / data-lost)
            existing_host = get_config_value(db, "host", "")
            if existing_host:
                return False  # DB already has config, don't overwrite
            for key, val in config.items():
                set_config_value(db, key, val)
            # Restore stats
            for key, val in payload.get("stats", {}).items():
                set_stat(db, key, val)
            # Restore tasks
            for task in payload.get("tasks", []):
                task.pop("id", None)  # let autoincrement assign new id
                db.execute(
                    """
                    insert into tasks(name,mode,cron,libraries,enabled,auto_delete,
                                      last_status,last_found,last_deleted,last_duration_ms,
                                      last_message,updated_at)
                    values(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        task.get("name", ""),
                        task.get("mode", ""),
                        task.get("cron", ""),
                        task.get("libraries", ""),
                        int(task.get("enabled", 1)),
                        int(task.get("auto_delete", 0)),
                        task.get("last_status"),
                        int(task.get("last_found", 0)),
                        int(task.get("last_deleted", 0)),
                        int(task.get("last_duration_ms", 0)),
                        task.get("last_message"),
                        task.get("updated_at"),
                    ),
                )
        return True
    except Exception:
        return False


def export_config() -> dict[str, Any]:
    """Export all config + stats + tasks as a dict (for API download)."""
    with connect() as db:
        config: dict[str, Any] = {}
        for key in _BACKUP_CONFIG_KEYS:
            val = get_config_value(db, key)
            if val is not None:
                config[key] = val
        stats: dict[str, Any] = {}
        for key in _BACKUP_STAT_KEYS:
            val = get_stat(db, key)
            if val is not None:
                stats[key] = val
        task_rows = db.execute("select * from tasks order by id").fetchall()
        tasks = [dict(r) for r in task_rows]
    return {
        "version": 1,
        "exported_at": now_ts(),
        "config": config,
        "stats": stats,
        "tasks": tasks,
    }


def import_config(payload: dict[str, Any]) -> bool:
    """Import config from a dict (from API upload). Returns True on success."""
    try:
        config = payload.get("config", {})
        if not config:
            return False
        with connect() as db:
            for key, val in config.items():
                if key in _BACKUP_CONFIG_KEYS:
                    set_config_value(db, key, val)
            for key, val in payload.get("stats", {}).items():
                if key in _BACKUP_STAT_KEYS:
                    set_stat(db, key, val)
            # Replace all tasks
            db.execute("delete from tasks")
            for task in payload.get("tasks", []):
                task.pop("id", None)
                db.execute(
                    """
                    insert into tasks(name,mode,cron,libraries,enabled,auto_delete,
                                      last_status,last_found,last_deleted,last_duration_ms,
                                      last_message,updated_at)
                    values(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        task.get("name", ""),
                        task.get("mode", ""),
                        task.get("cron", ""),
                        task.get("libraries", ""),
                        int(task.get("enabled", 1)),
                        int(task.get("auto_delete", 0)),
                        task.get("last_status"),
                        int(task.get("last_found", 0)),
                        int(task.get("last_deleted", 0)),
                        int(task.get("last_duration_ms", 0)),
                        task.get("last_message"),
                        task.get("updated_at"),
                    ),
                )
        backup_config()  # update backup file
        return True
    except Exception:
        return False


def is_data_volume_mounted() -> bool:
    """Check if DATA_DIR is a mounted volume (Linux only). Returns True if mounted or undeterminable."""
    try:
        mounts = Path("/proc/mounts").read_text(encoding="utf-8")
        data_str = str(DATA_DIR)
        for line in mounts.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == data_str:
                return True
        # Also check if any parent is a mount point (e.g. /data mounted, DATA_DIR is /data)
        # This handles cases where DATA_DIR itself isn't directly in /proc/mounts
        # but a parent directory is
        return False
    except Exception:
        return True  # Can't determine, assume mounted (non-Linux or no /proc)
