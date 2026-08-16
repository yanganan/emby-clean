import unittest

from app.scanner import (
    apply_recommendations,
    decorate_item,
    legacy_library_rules,
    match_row,
    normalize_variant_key,
    refine_match_group_meta,
    version_rank,
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

    def test_western_release_date_matcher_keeps_full_code_and_identity(self):
        result = match_row(
            row(name="DorcelClub.15.01.01 Pornochic 1080p.strm"),
            "av",
        )
        self.assertEqual(result["matcher"], "western_release_date")
        self.assertEqual(result["confidence"], "medium")
        self.assertTrue(result["key"].startswith("western:dorcelclub:15.01.01:release:"))

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

    def test_release_date_code_does_not_merge_different_titles(self):
        first = match_row(
            row(
                name="WowGirls.19.01.01 Angels Fuck.strm",
                path="/media/欧美合集/Emmy Accel,Eva Elfie/WowGirls.19.01.01-4K Emmy Accel,Eva Elfie/WowGirls.19.01.01-4K.strm",
            ),
            "av",
        )
        second = match_row(
            row(
                name="WowGirls.19.01.01 Busty In A Love Session.strm",
                path="/media/欧美合集/Eva Elfie,Sybil/WowGirls.19.01.01-4K Eva Elfie,Sybil/WowGirls.19.01.01-4K.strm",
            ),
            "av",
        )
        self.assertEqual(first["matcher"], "western_release_date")
        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual(first["evidence"]["code_kind"], "release_date")

    def test_release_date_code_groups_same_title_and_performers(self):
        first = match_row(
            row(
                name="Blacked.19.04.15 Off Limits.strm",
                path="/media/欧美合集/Emma Starletto/Blacked.19.04.15-4K Emma Starletto/Blacked.19.04.15-4K.strm",
            ),
            "av",
        )
        second = match_row(
            row(
                name="Blacked.19.04.15 Off Limits.strm",
                path="/media/欧美合集/Emma Starletto/Blacked.19.04.15-C Emma Starletto/Blacked.19.04.15-C.strm",
            ),
            "av",
        )
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(first["confidence"], "medium")

    def test_release_date_code_ignores_4k_suffix_when_matching_variants(self):
        four_k = row(
            name="BeautyAngels.19.01.31-4K.strm",
            path="/media/欧美合集/Tiny Teen/BeautyAngels.19.01.31-4K Tiny Teen/BeautyAngels.19.01.31-4K.strm",
        )
        default = row(
            name="BeautyAngels.19.01.31.strm",
            path="/media/欧美合集/Tiny Teen/BeautyAngels.19.01.31 Tiny Teen/BeautyAngels.19.01.31.strm",
        )
        first = match_row(four_k, "av")
        second = match_row(default, "av")
        self.assertEqual(first["matcher"], "western_release_date")
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(first["evidence"]["scene_code"], "19.01.31")

    def test_western_filename_priority_prefers_4k_then_subtitle_then_poster(self):
        rows = [
            row(
                emby_id="4k-subtitle",
                name="BeautyAngels.19.01.31-4K-C.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31-4K-C Tiny Teen/BeautyAngels.19.01.31-4K-C.strm",
                has_poster=0,
            ),
            row(
                emby_id="4k",
                name="BeautyAngels.19.01.31-4K.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31-4K Tiny Teen/BeautyAngels.19.01.31-4K.strm",
                has_poster=0,
            ),
            row(
                emby_id="subtitle",
                name="BeautyAngels.19.01.31-C.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31-C Tiny Teen/BeautyAngels.19.01.31-C.strm",
                has_poster=0,
            ),
            row(
                emby_id="plain-poster",
                name="BeautyAngels.19.01.31.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31 Tiny Teen/BeautyAngels.19.01.31.strm",
                has_poster=1,
            ),
            row(
                emby_id="plain",
                name="BeautyAngels.19.01.31.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31 Tiny Teen/BeautyAngels.19.01.31-plain.strm",
                has_poster=0,
            ),
        ]
        items = [
            decorate_item(dict(item), "av", match_row(item, "av"))
            for item in rows
        ]
        self.assertGreater(version_rank(items[0]), version_rank(items[1]))
        self.assertGreater(version_rank(items[0]), version_rank(items[2]))
        self.assertGreater(version_rank(items[1]), version_rank(items[3]))
        self.assertGreater(version_rank(items[2]), version_rank(items[4]))
        self.assertGreater(version_rank(items[3]), version_rank(items[4]))

    def test_western_strm_filename_priority_can_select_4k_without_media_metadata(self):
        rows = [
            row(
                emby_id="4k",
                name="BeautyAngels.19.01.31-4K.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31-4K Tiny Teen/BeautyAngels.19.01.31-4K.strm",
                has_poster=0,
            ),
            row(
                emby_id="plain",
                name="BeautyAngels.19.01.31.strm",
                path="/media/Tiny Teen/BeautyAngels.19.01.31 Tiny Teen/BeautyAngels.19.01.31.strm",
                has_poster=0,
            ),
        ]
        items = [
            decorate_item(dict(item), "av", match_row(item, "av"))
            for item in rows
        ]
        apply_recommendations(
            items,
            "av",
            {},
            {
                "profile": "modern",
                "matcher": "western_release_date",
                "confidence": "high",
                "source_type": "strm",
            },
        )
        self.assertEqual(items[0]["recommend_action"], "keep")
        self.assertEqual(items[1]["recommend_action"], "delete")

    def test_release_date_code_separates_same_title_different_performers(self):
        first = match_row(
            row(
                name="Vixen.17.12.15 One Night Stand Sex Tape.strm",
                path="/media/欧美合集/バニー・茜・コルビー/Vixen.17.12.15-4K バニー・茜・コルビー/Vixen.17.12.15-4K.strm",
            ),
            "av",
        )
        second = match_row(
            row(
                name="Vixen.17.12.15 One Night Stand Sex Tape.strm",
                path="/media/欧美合集/Nadya Nabakova/Vixen.17.12.15 Nadya Nabakova/Vixen.17.12.15.strm",
            ),
            "av",
        )
        self.assertNotEqual(first["key"], second["key"])

    def test_release_date_group_confidence_requires_same_title_and_performers(self):
        items = [{"emby_id": "1"}, {"emby_id": "2"}]
        row_match_meta = {
            "1": {"evidence": {"title_signature": "off-limits", "performer_signature": "emma-starletto"}},
            "2": {"evidence": {"title_signature": "off-limits", "performer_signature": "emma-starletto"}},
        }
        meta = {"matcher": "western_release_date", "confidence": "medium", "evidence": {"scene_code": "19.04.15"}}
        refine_match_group_meta(meta, items, row_match_meta)
        self.assertEqual(meta["confidence"], "high")

        row_match_meta["2"]["evidence"]["title_signature"] = "translated-off-limits"
        refine_match_group_meta(meta, items, row_match_meta)
        self.assertEqual(meta["confidence"], "medium")
        self.assertEqual(len(meta["evidence"]["title_signatures"]), 2)


if __name__ == "__main__":
    unittest.main()
