import unittest
from pathlib import Path


class FrontendStructureTests(unittest.TestCase):
    def test_frontend_exposes_new_review_modes_and_safety_controls(self):
        html = Path("app/static/index.html").read_text(encoding="utf-8")
        for token in ("media_health", "strm_health", "source_dupe", "content_dupe", "match_confidence", "dry_run:false", "pref_allow_auto_delete", "hero", "brand-kicker", "section-label", "data-mode"):
            self.assertIn(token, html)


if __name__ == "__main__":
    unittest.main()
