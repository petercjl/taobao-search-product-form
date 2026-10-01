"""Regression tests for the placement module's product/shop distinctions."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "analyze_advertisers.py"
SPEC = importlib.util.spec_from_file_location("analyze_advertisers", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdvertiserAnalysisTests(unittest.TestCase):
    def test_system_display_label_resolves_to_corroborated_actual_shop(self):
        with tempfile.TemporaryDirectory() as temporary:
            workbook = Path(temporary) / "clean.xlsx"
            natural = pd.DataFrame([
                {"商品ID": "p2", "店铺名称": "真实店铺", "占位类型": "自然位", "现价": 50, "付款人数": 7},
            ])
            ads = pd.DataFrame([
                {"商品ID": "p1", "店铺名称": "百亿补贴品牌优选", "掌柜名": "真实店铺", "店铺类型": "非金牌店铺", "占位类型": "广告位", "现价": 32, "序号": 1},
                {"商品ID": "p1", "店铺名称": "真实店铺", "掌柜名": "真实店铺", "店铺类型": "旗舰店", "占位类型": "广告位", "现价": 32, "序号": 2},
                {"商品ID": "p1", "店铺名称": "真实店铺", "掌柜名": "真实店铺", "店铺类型": "旗舰店", "占位类型": "广告位", "现价": 32, "序号": 3},
                {"商品ID": "p1", "店铺名称": "真实店铺", "掌柜名": "真实店铺", "店铺类型": "旗舰店", "占位类型": "广告位", "现价": 32, "序号": 4},
            ])
            with pd.ExcelWriter(workbook) as writer:
                natural.to_excel(writer, sheet_name="自然位", index=False)
                ads.to_excel(writer, sheet_name="广告位", index=False)

            result = MODULE.analyze(workbook, [40])
            self.assertEqual(result["counts"]["ad_appearances"], 4)
            self.assertEqual(result["counts"]["ad_products"], 1)
            self.assertEqual(result["counts"]["advertiser_shops_by_exact_name"], 1)
            self.assertEqual(result["counts"]["ad_appearances_with_resolved_system_display_label"], 1)
            self.assertEqual(result["ad_products"][0]["shop_name"], "真实店铺")
            self.assertEqual(result["ad_products"][0]["shop_type"], "旗舰店")
            self.assertEqual(result["ad_products"][0]["display_shop_names_in_source"], ["百亿补贴品牌优选", "真实店铺"])
            self.assertEqual(result["advertiser_shops"][0]["ad_appearance_count"], 4)
            self.assertEqual(result["ad_appearance_records"][0]["display_shop_name"], "百亿补贴品牌优选")
            self.assertEqual(result["ad_appearance_records"][0]["shop_name"], "真实店铺")
            self.assertEqual(result["shop_type_breakdown"]["advertising"]["旗舰店"]["appearance_count"], 4)

    def test_distinct_actual_shop_names_remain_unresolved(self):
        ads = pd.DataFrame([
            {"商品ID": "p1", "店铺名称": "店铺甲", "掌柜名": "甲"},
            {"商品ID": "p1", "店铺名称": "店铺乙", "掌柜名": "乙"},
        ])
        with self.assertRaisesRegex(ValueError, "unresolved multiple shop names"):
            MODULE.resolve_advertiser_shops(ads)

    def test_shop_layout_uses_natural_payment_and_exact_shop_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            workbook = Path(temporary) / "clean.xlsx"
            natural = pd.DataFrame([
                {"商品ID": "p1", "店铺名称": "店铺甲", "占位类型": "自然位", "现价": 50, "付款人数": 10, "商品名称": "甲商品一", "序号": 1},
                {"商品ID": "p2", "店铺名称": "店铺乙", "占位类型": "自然位", "现价": 150, "付款人数": 20, "商品名称": "乙商品", "序号": 2},
                {"商品ID": "p4", "店铺名称": "店铺甲", "占位类型": "自然位", "现价": 350, "付款人数": 30, "商品名称": "甲商品二", "序号": 3},
            ])
            ads = pd.DataFrame([
                {"商品ID": "p1", "店铺名称": "店铺甲", "占位类型": "广告位", "现价": 50, "付款人数": 0, "商品名称": "甲商品一", "序号": 1},
                {"商品ID": "p1", "店铺名称": "店铺甲", "占位类型": "广告位", "现价": 55, "付款人数": 0, "商品名称": "甲商品一", "序号": 4},
                {"商品ID": "p2", "店铺名称": "店铺甲", "占位类型": "广告位", "现价": 150, "付款人数": 0, "商品名称": "乙商品", "序号": 5},
                {"商品ID": "p3", "店铺名称": "店铺甲", "占位类型": "广告位", "现价": 250, "付款人数": 0, "商品名称": "甲商品三", "序号": 6},
            ])
            with pd.ExcelWriter(workbook) as writer:
                natural.to_excel(writer, sheet_name="自然位", index=False)
                ads.to_excel(writer, sheet_name="广告位", index=False)

            result = MODULE.analyze(workbook, [100, 200])
            shop = result["advertiser_shops"][0]
            products = {row["product_id"]: row for row in result["ad_products"]}

            self.assertEqual((shop["ad_appearance_count"], shop["ad_product_count"]), (4, 3))
            self.assertEqual(shop["natural_shop_payment_people_sum"], 40)
            self.assertEqual(shop["natural_advertised_product_payment_people_sum_by_same_shop_name"], 10)
            self.assertEqual(shop["natural_unadvertised_product_payment_people_sum_by_same_shop_name"], 30)
            self.assertEqual(shop["matching_ad_product_payment_people_sum_by_id"], 30)
            self.assertTrue(products["p2"]["cross_placement_shop_name_differs"])
            self.assertIsNone(products["p3"]["natural_payment_people"])
            self.assertEqual(products["p1"]["ad_price_values_in_source"], [50, 55])
            self.assertEqual(
                [row["product_count"] for row in result["price_bands"]["advertised_unique_products"]["bands"]],
                [1, 1, 1],
            )


if __name__ == "__main__":
    unittest.main()
