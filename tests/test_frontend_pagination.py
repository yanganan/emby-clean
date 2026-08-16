import json
import subprocess
import unittest
from pathlib import Path


class FrontendPaginationTests(unittest.TestCase):
    def test_group_boundary_pages_do_not_overlap(self):
        helper = Path("app/static/pagination.js").resolve()
        script = f"""
const {{ buildPageBuckets }} = require({json.dumps(str(helper))});
const items = Array.from({{length: 12}}, (_, index) => ({{
  id: String(index), groupTitle: index < 5 ? 'A' : (index < 8 ? 'B' : 'C')
}}));
const pages = buildPageBuckets(items, 5);
const ids = pages.map(page => page.map(item => item.id));
if (JSON.stringify(ids) !== JSON.stringify([['0','1','2','3','4'], ['5','6','7'], ['8','9','10','11']])) {{
  throw new Error(JSON.stringify(ids));
}}
const flat = pages.flat().map(item => item.id);
if (new Set(flat).size !== items.length) throw new Error('page overlap');
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_result_page_handles_rejected_delete_without_removing_rows(self):
        html = Path("app/static/index.html").read_text(encoding="utf-8")
        self.assertIn("d.status==='rejected'", html)
        self.assertIn("应用不会删除 STRM 或远程源文件", html)
        self.assertIn("EmbyCleanPagination", html)
        self.assertIn("i.tag_4k?'4K'", html)


if __name__ == "__main__":
    unittest.main()
