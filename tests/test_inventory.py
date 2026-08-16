import tempfile
import unittest
import sqlite3
import json
from pathlib import Path

from app.inventory import inspect_source, sha256_file
from app.scanner import scan


class InventoryTests(unittest.TestCase):
    def test_strm_source_is_normalized_without_network_access(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "movie.strm"
            path.write_text("HTTP://Example.com/video?id=2#fragment\n", encoding="utf-8")
            result = inspect_source(str(path))
        self.assertEqual(result["source_type"], "strm")
        self.assertEqual(result["source_ref"], "http://example.com/video?id=2")
        self.assertEqual(result["status"], "readable")

    def test_unmounted_strm_is_unavailable_not_missing_media(self):
        result = inspect_source("/path/that/is/not/mounted/movie.strm")
        self.assertEqual(result["source_type"], "strm")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "mount_or_path_unavailable")

    def test_local_file_hash_is_exact_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "movie.bin"
            path.write_bytes(b"emby-clean-test")
            first = sha256_file(path)
            second = sha256_file(path)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_image_mode_reports_same_emby_image_tag_as_review_group(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            create table media_items (
              emby_id text primary key, library_id text, library_name text, name text,
              sort_name text, path text, parent_id text, series_id text, series_name text,
              item_type text, size integer, runtime_ticks integer, duration_seconds real,
              width integer, height integer, resolution integer, has_poster integer,
              primary_image_tag text, image_url text, date_created text, is_media integer,
              provider_key text, tags text, codec text, container text, bitrate integer,
              audio_codec text, audio_channels integer, has_subtitle integer,
              subtitle_lang text, frame_rate real, bit_depth integer, raw_json text,
              updated_at integer, source_type text, source_ref text, source_status text,
              source_reason text, source_size integer, source_mtime real,
              source_sha256 text, image_hash text
            );
            create table ignore_items (emby_id text, group_key text, mode text, scope text);
            """
        )
        columns = [row[1] for row in db.execute("pragma table_info(media_items)").fetchall()]
        base = {column: 0 for column in columns}
        base.update({
            "library_id": "western", "library_name": "欧美", "item_type": "Movie",
            "is_media": 1, "primary_image_tag": "same-image", "tags": "[]", "raw_json": "{}",
            "source_type": "strm", "source_status": "unknown", "image_hash": "same-image",
        })
        for item_id in ("a", "b"):
            db.execute(
                "insert into media_items(" + ",".join(columns) + ") values(" + ",".join("?" for _ in columns) + ")",
                [item_id if column == "emby_id" else base[column] for column in columns],
            )
        result = scan(db, "image", [], {}, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["items"]), 2)
        self.assertEqual(result[0]["group_meta"]["matcher"], "image_exact_tag")


if __name__ == "__main__":
    unittest.main()
