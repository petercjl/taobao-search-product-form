"""Regression checks for search-listing geography grains and evidence boundaries."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "analyze_geography.py"
SPEC = importlib.util.spec_from_file_location("analyze_geography", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def natural():
    return pd.DataFrame([
        {"商品ID": "1", "商品名称": "甲锅", "店铺名称": "甲店", "地址": "浙江 金华", "现价": 30, "付款人数": 100, "占位类型": "自然位"},
        {"商品ID": "2", "商品名称": "乙锅", "店铺名称": "甲店", "地址": "浙江 宁波", "现价": 50, "付款人数": 200, "占位类型": "自然位"},
        {"商品ID": "3", "商品名称": "丙锅", "店铺名称": "乙店", "地址": "浙江 金华", "现价": 100, "付款人数": 300, "占位类型": "自然位"},
        {"商品ID": "4", "商品名称": "丁锅", "店铺名称": "丙店", "地址": "上海", "现价": 80, "付款人数": 400, "占位类型": "自然位"},
    ])


def ads():
    return pd.DataFrame([
        {"商品ID": "1", "店铺名称": "甲店", "地址": "浙江 金华", "占位类型": "广告位"},
        {"商品ID": "1", "店铺名称": "甲店", "地址": "浙江 金华", "占位类型": "广告位"},
        {"商品ID": "9", "店铺名称": "外店", "地址": "河北 邢台", "占位类型": "广告位"},
    ])


class GeographyTests(unittest.TestCase):
    def test_product_shop_region_and_ad_grains(self):
        relations = [
            {"product_id": "1", "facet": "surface_claim", "root": "不粘"},
            {"product_id": "2", "facet": "surface_claim", "root": "不粘"},
            {"product_id": "3", "facet": "surface_claim", "root": "不粘"},
        ]
        result = MODULE.analyze(natural(), ads(), relations)
        summary = result["summary"]
        quality = summary["quality"]
        self.assertEqual(quality["natural_product_count"], 4)
        self.assertEqual(quality["natural_shop_count"], 3)
        self.assertEqual(quality["natural_shop_address_pair_count"], 4)
        self.assertEqual(quality["multi_address_shop_count"], 1)
        self.assertEqual(quality["ad_appearance_count"], 3)
        self.assertEqual(quality["ad_unique_product_id_count"], 2)
        self.assertEqual(quality["ad_product_ids_also_natural_count"], 1)
        self.assertEqual(result["detail"]["natural_products"][0]["address_raw"], "浙江 金华")
        city = {row["region"]: row for row in summary["city_regions"]}
        self.assertEqual(city["浙江 金华"]["product_count"], 2)
        self.assertEqual(city["浙江 金华"]["shop_count"], 2)
        self.assertEqual(city["上海"]["product_count"], 1)
        ad_city = {row["region"]: row for row in summary["ad_city_regions"]}
        self.assertEqual(ad_city["浙江 金华"]["appearance_count"], 2)
        self.assertEqual(ad_city["浙江 金华"]["unique_ad_product_count"], 1)
        root_city = next(row for row in summary["root_regions"] if row["level"] == "city" and row["region"] == "浙江 金华" and row["root"] == "不粘")
        self.assertEqual(root_city["product_count"], 2)
        self.assertEqual(root_city["shop_count"], 2)
        self.assertAlmostEqual(root_city["location_quotient"], 1.3333, places=4)

    def test_duplicate_natural_id_and_wrong_placement_rejected(self):
        bad = natural()
        bad.loc[1, "商品ID"] = "1"
        with self.assertRaisesRegex(ValueError, "must be unique"):
            MODULE.analyze(bad, ads())
        bad = ads()
        bad.loc[0, "占位类型"] = "自然位"
        with self.assertRaisesRegex(ValueError, "another placement"):
            MODULE.analyze(natural(), bad)

    def test_location_unknown_and_municipality(self):
        self.assertEqual(MODULE.location("上海"), {"address": "上海", "province": "上海", "city": "上海", "level": "municipality"})
        self.assertEqual(MODULE.location("  浙江   金华 ")["address"], "浙江 金华")
        self.assertEqual(MODULE.location(None)["level"], "unknown")

    def test_title_join_requires_matching_population_and_preserves_source_title(self):
        products = MODULE.records_from_frame(natural(), True)
        document = {"source": {"sha256": "expected", "sheet": "自然位"},
                    "products": [{"product_id": row["product_id"], "title": row["title"]} for row in products],
                    "product_roots": [{"product_id": "1", "facet": "form_claim", "root": "煎锅"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roots.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(MODULE.load_title_roots(path, "expected", products)[0]["product_id"], "1")
            with self.assertRaisesRegex(ValueError, "hash"):
                MODULE.load_title_roots(path, "other", products)
            document["products"][1] = dict(document["products"][0])
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "product IDs"):
                MODULE.load_title_roots(path, "expected", products)


if __name__ == "__main__":
    unittest.main()
