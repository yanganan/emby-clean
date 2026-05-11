from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


DATA_DIR = Path(os.getenv("EMBY_CLEAN_DATA", "./data")).resolve()
DB_PATH = DATA_DIR / "emby_clean.db"


DEFAULT_PREFS = {
    "av_keep_priority": "tag_uc",
    "size_keep": "path_long",
    "duration_keep": "min",
    "duration_scope": "dir",
    "duration_precision": "second",
    "smart_keep": "reso_max",
    "confirm_batch": "true",
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
              last_status text,
              last_found integer default 0,
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
        ensure_column(db, "libraries", "api_count", "integer default 0")
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
def connect() -> Iterable[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
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
