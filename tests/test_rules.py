import unittest

from app.scanner import (
    apply_recommendations,
    legacy_library_rules,
    match_row,
    normalize_variant_key,
)


def row(**values):
    defaults = {
        "library_name": "欧美",
        "library_id": "western",
        "name": "",
        "sort_name": "",
        "series_name": "",
        "path": "",
        "provider_key": "",
        "item_type": "Movie",
        "is_media": 1,
        "size": 0,
        "resolution": 0,
        "duration_seconds": 0,
        "bitrate": 0,
        "has_poster": 1,
    }
    defaults.update(values)
    return defaults


class DuplicateRuleTests(unittest.TestCase):
    def test_variant_normalization_keeps_full_dotted_scene_code(self):
        normalized = normalize_variant_key("DorcelClub.15.01.01 Pornochic 1080p.strm")
        self.assertIn("dorcelclub 15 01 01", normalized)

    def test_western_scene_matcher_uses_full_code(self):
        result = match_row(
            row(name="DorcelClub.15.01.01 Pornochic 1080p.strm"),
            "av",
        )
        self.assertEqual(result["matcher"], "western_scene_code")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["key"], "western:dorcelclub:15.01.01")

    def test_short_number_requires_site_context(self):
        result = match_row(
            row(name="02 Scene 1080p.strm", path="/media/DudCast.com/02 Scene 1080p.strm"),
            "av",
        )
        self.assertEqual(result["matcher"], "western_context_number")
        self.assertEqual(result["key"], "western:dudcast.com:02")

    def test_generic_metadata_id_is_not_a_western_scene_number(self):
        result = match_row(row(name="TMDBID-33238"), "av")
        self.assertEqual(result["key"], "")

    def test_japanese_library_keeps_legacy_rule_path(self):
        japanese = row(library_name="日本系列", name="ABF-364 [C].strm")
        self.assertTrue(legacy_library_rules(japanese))
        result = match_row(japanese, "av")
        self.assertEqual(result["matcher"], "legacy_av")
        self.assertEqual(result["key"], "ABF-364")

    def test_western_strm_without_quality_metadata_is_review_only(self):
        items = [
            {"emby_id": "1", "size": 0, "resolution": 0, "duration": 0, "source_type": "strm"},
            {"emby_id": "2", "size": 0, "resolution": 0, "duration": 0, "source_type": "strm"},
        ]
        apply_recommendations(
            items,
            "smart",
            {},
            {"profile": "modern", "confidence": "high", "source_type": "strm"},
        )
        self.assertEqual({item["recommend_action"] for item in items}, {"review"})


if __name__ == "__main__":
    unittest.main()
