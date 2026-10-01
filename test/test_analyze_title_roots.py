"""Contract checks for the natural-position title-root module."""

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "analyze_title_roots.py"
SPEC = importlib.util.spec_from_file_location("analyze_title_roots", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def frame():
    return pd.DataFrame([
        {"商品ID": "p1", "商品名称": "纯钛无涂层平底锅不粘不粘煎蛋24cm", "商品图片链接": "https://example.test/a.jpg", "现价": 300, "付款人数": 100, "店铺名称": "甲店", "占位类型": "自然位"},
        {"商品ID": "p2", "商品名称": "钛陶瓷早餐锅不沾煎蛋", "商品图片链接": "https://example.test/b.jpg", "现价": 80, "付款人数": 400, "店铺名称": "乙店", "占位类型": "自然位"},
    ])


class TitleRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lexicon = MODULE.load_lexicon(MODULE.DEFAULT_LEXICON)

    def test_roots_retain_product_identity_alias_and_repeated_surface(self):
        result = MODULE.analyze_frame(frame(), self.lexicon)
        rows = {(row["product_id"], row["facet"], row["root"]): row for row in result["product_roots"]}
        self.assertEqual(result["quality"]["natural_product_count"], 2)
        self.assertEqual(rows[("p1", "surface_claim", "不粘")]["occurrence_count_in_title"], 2)
        self.assertEqual(rows[("p2", "surface_claim", "不粘")]["surfaces"], ["不沾"])
        self.assertEqual(rows[("p1", "material_claim", "纯钛")]["price_yuan"], 300)
        self.assertEqual(rows[("p1", "size_claim", "24cm")]["payment_people"], 100)
        self.assertNotIn(("p1", "unclassified", "24cm"), rows)
        self.assertEqual(rows[("p2", "form_claim", "早餐锅")]["image_url"], "https://example.test/b.jpg")
        self.assertNotIn(("p1", "material_claim", "钛"), rows)
        self.assertEqual(result["quality"]["payment_high_threshold_p90"], 370)

    def test_advertising_or_duplicate_natural_ids_are_rejected(self):
        bad = frame()
        bad.loc[1, "占位类型"] = "广告位"
        with self.assertRaisesRegex(ValueError, "natural-position rows only"):
            MODULE.analyze_frame(bad, self.lexicon)
        bad = frame()
        bad.loc[1, "商品ID"] = "p1"
        with self.assertRaisesRegex(ValueError, "unique"):
            MODULE.analyze_frame(bad, self.lexicon)


if __name__ == "__main__":
    unittest.main()
