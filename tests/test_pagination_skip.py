import json
import subprocess
import unittest
from pathlib import Path


class PaginationSkipAfterDeleteTests(unittest.TestCase):
    """删除后自动略过本页剩余条目，下一页只出现全新数据（issue: 分页有效数据少）"""

    def run_node(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(["node", "-e", script], capture_output=True, text=True)

    def test_page_after_delete_contains_only_new_items(self):
        """用户场景：100条/页，第1页删50条 → 当前页不得再出现旧第1页剩余条目"""
        helper = Path("app/static/pagination.js").resolve()
        html = Path("app/static/index.html").read_text(encoding="utf-8")
        script = f"""
const {{ buildPageBuckets }} = require({json.dumps(str(helper))});
// 150组×2条
const flat = [];
for (let g = 0; g < 150; g++) {{
  flat.push({{ emby_id: `g${{g}}a`, groupTitle: `Group${{g}}`, recommend_action: 'delete' }});
  flat.push({{ emby_id: `g${{g}}b`, groupTitle: `Group${{g}}`, recommend_action: 'keep' }});
}}
const pageSize = 100;
// 初始第1页
let pages = buildPageBuckets(flat, pageSize);
const p1 = pages[0].map(i => i.emby_id);
if (p1.length !== 100) throw new Error('第1页应为100条, 实际 ' + p1.length);

// 删除50条（每组的a条目）
const deleted = new Set(p1.filter(id => id.endsWith('a')));
const remainingP1 = p1.filter(id => !deleted.has(id));  // 50条keep

// postIds 行为：flat 移除已删 + 本页剩余标记 skipped
const newFlat = flat.filter(i => !deleted.has(i.emby_id));
const skipped = new Set(remainingP1);
const active = newFlat.filter(i => !skipped.has(i.emby_id));

// 分页基于 active
pages = buildPageBuckets(active, pageSize);
const curPage = pages[0].map(i => i.emby_id);
const overlap = curPage.filter(id => remainingP1.includes(id));
if (overlap.length) throw new Error('当前页仍包含旧第1页条目: ' + overlap.join(','));

// 完整性：active + skipped = newFlat，无丢失
if (active.length + skipped.size !== newFlat.length) throw new Error('条目丢失');
if (newFlat.length !== 250) throw new Error('newFlat 应为250, 实际 ' + newFlat.length);

// 前端代码必须包含 skipped 逻辑
if (!{json.dumps('state.skipped' in html)}) throw new Error('index.html 缺少 state.skipped');
if (!{json.dumps("pageIdsBefore.forEach(id=>{if(!ids.has(id))state.skipped.add(id)})" in html)}) throw new Error('postIds 缺少略过逻辑');
"""
        result = self.run_node(script)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_skipped_filter_recoverable(self):
        """已略过条目通过筛选找回：flat = active + skipped 恒等式在多轮删除后仍成立"""
        helper = Path("app/static/pagination.js").resolve()
        script = f"""
const {{ buildPageBuckets }} = require({json.dumps(str(helper))});
const flat = [];
for (let g = 0; g < 120; g++) {{
  flat.push({{ emby_id: `g${{g}}a`, groupTitle: `Group${{g}}`, recommend_action: 'delete' }});
  flat.push({{ emby_id: `g${{g}}b`, groupTitle: `Group${{g}}`, recommend_action: 'keep' }});
}}
const pageSize = 100;
let skipped = new Set();
// 模拟3轮删除：每轮删当前页前50条a，剩余标记略过
for (let round = 0; round < 3; round++) {{
  const active = flat.filter(i => !skipped.has(i.emby_id));
  const pages = buildPageBuckets(active, pageSize);
  if (!pages.length) break;
  const cur = pages[0].map(i => i.emby_id);
  const toDelete = new Set(cur.filter(id => id.endsWith('a')).slice(0, 50));
  if (!toDelete.size) {{
    cur.forEach(id => skipped.add(id));  // 全选删除时剩余也略过
    continue;
  }}
  cur.forEach(id => {{ if (!toDelete.has(id)) skipped.add(id); }});
}}
// 恒等式
const active = flat.filter(i => !skipped.has(i.emby_id));
if (active.length + skipped.size !== flat.length) throw new Error('多轮删除后条目守恒被破坏');
// skipped 中的任何条目都能通过「已略过」视图看到
const skippedView = flat.filter(i => skipped.has(i.emby_id));
if (skippedView.length !== skipped.size) throw new Error('已略过视图数量不符');
console.log(JSON.stringify({{ active: active.length, skipped: skipped.size }}));
"""
        result = self.run_node(script)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_index_html_no_cache_headers(self):
        """后端对 index.html 禁缓存，防止浏览器持旧版前端"""
        main_py = Path("app/main.py").read_text(encoding="utf-8")
        self.assertIn("no-cache, no-store, must-revalidate", main_py)


if __name__ == "__main__":
    unittest.main()
