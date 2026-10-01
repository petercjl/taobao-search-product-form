import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "build_report_viewmodel.py"
SPEC = importlib.util.spec_from_file_location("build_report_viewmodel", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def bound_sample():
    loaded = {
        "visual": {
            "summary": {},
            "labels": [{"product_id": "1", "style_ids": ["PS-A"], "boundary_reason": None}],
            "prototypes": [{"style_id": "PS-A", "name": "完整商品款式", "product_ids": ["1"], "product_count": 1}],
            "interpretation": f"<!-- source_prototype_summary_sha256: {'c' * 64} -->\n\n本轮款式解读。",
        },
        "decision": {
            "evidence": {
                "sources": {"prototype_labels": {"sha256": "a" * 64}},
                "products": [{"product_id": "1", "visual_status": "tagged",
                              "product_style_ids": ["PS-A"], "product_style_boundary": None}],
                "candidates": [{"candidate_id": "c-1", "axis": "product_style"}],
            },
            "cards": {"schema_version": 2, "source_evidence_sha256": "b" * 64,
                      "cards": [{"candidate_id": "c-1"}]},
            "interpretation": f"<!-- source_evidence_sha256: {'b' * 64} -->\n\n本轮机会解读。",
        },
    }
    srcs = {"visual": {"labels": {"sha256": "a" * 64}, "prototypes": {"sha256": "c" * 64}},
            "decision": {"evidence": {"sha256": "b" * 64}}}
    return loaded, srcs


class ReportViewModelTests(unittest.TestCase):
    def test_report_bindings_accept_same_prototype_and_evidence_version(self):
        loaded, srcs = bound_sample()
        MODULE.check_report_bindings(loaded, srcs)
        self.assertEqual(loaded["visual"]["interpretation"], "本轮款式解读。")
        self.assertEqual(loaded["decision"]["interpretation"], "本轮机会解读。")

    def test_report_bindings_reject_old_cards_with_current_gallery(self):
        loaded, srcs = bound_sample()
        loaded["decision"]["cards"]["source_evidence_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "not bound to current comparison evidence"):
            MODULE.check_report_bindings(loaded, srcs)

    def test_report_bindings_reject_old_visual_interpretation(self):
        loaded, srcs = bound_sample()
        loaded["visual"]["interpretation"] = f"<!-- source_prototype_summary_sha256: {'f' * 64} -->\n旧稿。"
        with self.assertRaisesRegex(ValueError, "current source_prototype_summary_sha256"):
            MODULE.check_report_bindings(loaded, srcs)

    def test_report_bindings_reject_prototype_membership_mismatch(self):
        loaded, srcs = bound_sample()
        loaded["visual"]["prototypes"][0]["product_ids"] = ["2"]
        with self.assertRaisesRegex(ValueError, "summary membership disagrees"):
            MODULE.check_report_bindings(loaded, srcs)

    def test_unobserved_product_has_separate_gallery_group(self):
        product = {"visual_status": "not_observed", "form": None}
        self.assertEqual(MODULE.visual_group(product), "未识图")
        self.assertEqual(MODULE.visual_state(product["visual_status"]), "未识图（图片不可用）")

    def test_markdown_retains_sections_lists_and_tables(self):
        markdown = """# title

## 发现

**结论**在这里。

1. 第一项
2. 第二项

| 商品 | 数量 |
| --- | ---: |
| A | 2 |

## 边界

待验证。
"""
        blocks = MODULE.md_blocks(markdown)
        self.assertEqual([block["title"] for block in blocks], ["发现", "边界"])
        first = blocks[0]["blocks"]
        self.assertEqual(first[0]["type"], "actions")
        self.assertEqual(first[0]["items"][0]["title"], "结论")
        self.assertEqual(first[0]["items"][0]["text"], "在这里。")
        self.assertEqual([item["text"] for item in first[0]["items"][1:]], ["第一项", "第二项"])
        self.assertEqual(first[1]["rows"], [["A", "2"]])

    def test_table_uses_live_workbench_column_contract(self):
        block = MODULE.table("测试", [("id", "商品ID"), ("count", "数量")],
                             [{"id": "001", "count": 4}])
        self.assertEqual(block["columns"], ["商品ID", "数量"])
        self.assertEqual(block["rows"], [["001", 4]])

    def test_structured_conclusion_has_semantic_emphasis(self):
        block = MODULE.conclusion([
            ("判断", "先核验", "再决策", "positive"),
            ("边界", "尚无成本", "仅供研究", "warning"),
        ])
        self.assertEqual(block["items"][0]["segments"][0]["emphasis"], "strong")
        self.assertEqual(block["items"][1]["segments"][1]["emphasis"], "italic")
        self.assertEqual(block["items"][0]["segments"][0]["tone"], "positive")

    def test_numeric_format_preserves_integer_zeros(self):
        self.assertEqual(MODULE.rounded(7000, 0), "7,000")
        self.assertEqual(MODULE.rounded(0, 0), "0")
        self.assertEqual(MODULE.rounded(61.640, 2), "61.64")

    def test_long_case_prose_becomes_numbered_emphasized_points(self):
        body = ("本次广告位出现八次，涉及四款商品；自然位主力没有进入广告位。"
                "其中两款已显示较高付款人数，但这不能说明广告带来的效果。"
                "下一步要核对图片、实际规格和可购买价格，再决定是否研究供应商。")
        block = MODULE.prose_block("**商品布局。** " + body)
        self.assertEqual(block["type"], "actions")
        self.assertEqual(len(block["items"]), 1)
        self.assertEqual(block["items"][0]["title"], "商品布局")
        self.assertEqual(block["items"][0]["text"], body)
        self.assertEqual(block["items"][0]["label"], "商品布局")

    def test_long_markdown_sections_have_no_prose_wall(self):
        passage = "事实一。" * 45
        blocks = MODULE.md_blocks("## 案例\n\n" + passage + "\n\n" + passage)
        case = blocks[0]
        self.assertEqual(case["type"], "card")
        self.assertEqual(len(case["blocks"]), 1)
        self.assertEqual(case["blocks"][0]["type"], "actions")
        self.assertEqual(len(case["blocks"][0]["items"]), 2)
        self.assertEqual("".join(item["source_chunk"] for item in case["blocks"][0]["items"]), passage * 2)

    def test_numbered_points_keep_thousands_separators_together(self):
        source = "同店自然位有十三款，其中商品显示 2,000 人付款，另一个显示 7,466 人付款。"
        items = MODULE.point_items(source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_chunk"], source)
        self.assertIn("2,000", items[0]["text"])
        self.assertIn("7,466", items[0]["text"])

    def test_source_numbered_conclusions_remain_five_complete_points(self):
        conclusions = [
            "1. **市场通用语不是差异化。**不粘覆盖 1469 个商品，仍需比较实物结构与材料主张。",
            "2. **需核验具体形态。**聚油覆盖 85 个商品，其中高付款样本集中在品牌店铺；不能归因于词。",
            "3. **材质表述对应价格差。**纯钛中位数 379 元，钛陶瓷中位数 95 元；材料真伪待核实。",
            "4. **早餐锅值得看图。**标题组合有 209 个商品，但不能证明是同一实物锅型。",
            "5. **店铺词根布局是线索。**样本分布可用于选竞品，不能证明真实销售结构。",
        ]
        blocks = MODULE.md_blocks("## 主要发现\n\n" + "\n".join(conclusions))
        rows = blocks[0]["blocks"][0]["items"]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all("。" in row["source_chunk"] and row["text"] for row in rows))
        self.assertIn("材料真伪待核实", rows[2]["text"])


if __name__ == "__main__":
    unittest.main()
