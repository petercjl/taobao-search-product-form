"""Tests for sample-driven price bands and population boundaries."""

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "analyze_price_bands.py"
SPEC = importlib.util.spec_from_file_location("analyze_price_bands", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def natural(prices):
    return pd.DataFrame([{"商品ID": str(i), "商品名称": f"商品{i}", "店铺名称": f"店{i % 4}",
                          "现价": price, "付款人数": i + 1, "占位类型": "自然位"}
                         for i, price in enumerate(prices)])


def ads():
    return pd.DataFrame([{"商品ID": "0", "现价": 11, "占位类型": "广告位"},
                         {"商品ID": "0", "现价": 12, "占位类型": "广告位"},
                         {"商品ID": "new", "现价": 110, "占位类型": "广告位"}])


class PriceBandsTests(unittest.TestCase):
    def test_jenks_uses_sample_and_keeps_all_natural_products(self):
        prices = [10, 11, 12, 13, 14, 15, 90, 100, 110, 120, 130, 140]
        detail, summary = MODULE.analyze(natural(prices), ads(), "sample")
        self.assertEqual(summary["quality"]["natural_product_count"], len(prices))
        self.assertEqual(len(detail["products"]), len(prices))
        self.assertEqual(sum(row["product_count"] for row in summary["bands"]), len(prices))
        self.assertEqual(sum(row["ad_appearance_count"] for row in summary["bands"]), 3)
        self.assertEqual(sum(row["ad_unique_product_count"] for row in summary["bands"]), 2)
        self.assertGreater(summary["selected_model"]["boundaries"][0], 15)
        shifted = MODULE.analyze(natural([price * 10 for price in prices]), ads(), "shifted")[1]
        self.assertEqual([round(x * 10, 5) for x in summary["selected_model"]["boundaries"]],
                         [round(x, 5) for x in shifted["selected_model"]["boundaries"]])

    def test_repeated_prices_never_split_and_counts_not_equalized(self):
        prices = [9] * 30 + [20] * 12 + [80] * 8 + [400] * 5
        detail, summary = MODULE.analyze(natural(prices), ads(), "repeat")
        by_price = {}
        for row in detail["products"]:
            by_price.setdefault(row["price_yuan"], set()).add(row["band"])
        self.assertTrue(all(len(bands) == 1 for bands in by_price.values()))
        self.assertEqual(sum(row["product_count"] for row in summary["bands"]), len(prices))

    def test_invalid_input_and_identity_are_rejected(self):
        frame = natural([10, 20, 30, 40])
        frame.loc[1, "商品ID"] = "0"
        with self.assertRaisesRegex(ValueError, "unique"):
            MODULE.analyze(frame, ads(), "duplicate")
        frame = natural([10, 20, 30, 40])
        frame.loc[1, "现价"] = 0
        with self.assertRaisesRegex(ValueError, "non-positive"):
            MODULE.analyze(frame, ads(), "zero")
        with self.assertRaisesRegex(ValueError, "penalty"):
            MODULE.analyze(natural([10, 20, 30, 40]), ads(), "bad", complexity_penalty=1)


if __name__ == "__main__":
    unittest.main()
