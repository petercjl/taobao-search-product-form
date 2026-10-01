import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "assemble_opportunity_evidence.py"
SPEC = importlib.util.spec_from_file_location("assemble_opportunity_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    source = "a" * 64
    common = [
        {"product_id": "1", "title": "浅锅早餐", "shop_name": "甲店", "price_yuan": 60,
         "payment_people": 100, "band": 2},
        {"product_id": "2", "title": "浅锅早餐", "shop_name": "乙店", "price_yuan": 70,
         "payment_people": 40, "band": 2},
        {"product_id": "3", "title": "相邻品", "shop_name": "甲店", "price_yuan": 30,
         "payment_people": 20, "band": 1},
    ]
    visual = {"records": [
        {"product_id": "1", "status": "tagged", "image_path": "one.jpg", "image_sha256": "1" * 64, "visible_evidence": "分格",
         "form": {"label": "分格锅"}, "style": {"label": "浅色", "physical_delta": "浅色锅体"},
         "audience": {"label": "早餐", "physical_delta": "独立分格"}},
        {"product_id": "2", "status": "tagged", "image_path": "two.jpg", "image_sha256": "2" * 64, "visible_evidence": "分格",
         "form": {"label": "分格锅"}, "style": {"label": "深色", "physical_delta": "深色锅体"},
         "audience": {"label": "早餐", "physical_delta": "独立分格"}},
        {"product_id": "3", "status": "uncertain", "image_path": "three.jpg", "image_sha256": "3" * 64, "visible_evidence": "模糊",
         "form": {"label": "非目标"}, "style": {"label": None}, "audience": {"label": None}},
    ]}
    price = {"source": {"sha256": source}, "products": common,
             "advertising_appearances": [{"product_id": "1"}]}
    title = {"source": {"sha256": source}, "products": [
        {**{key: row[key] for key in ("product_id", "title", "shop_name", "price_yuan", "payment_people")},
         "shop_type": "普通店", "image_url": "https://example.org/x.jpg", "natural_position": i + 1}
        for i, row in enumerate(common)],
        "product_roots": [{"product_id": "1", "facet": "task", "root": "早餐"}]}
    geography = {"source": {"sha256": source}, "natural_products": [
        {**{key: row[key] for key in ("product_id", "title", "shop_name", "price_yuan", "payment_people")},
         "address_raw": "浙江"} for row in common]}
    advertising = {"source": {"sha256": source},
                   "counts": {"ad_appearances": 2, "ad_products": 2},
                   "ad_appearance_records": [
                       {"product_id": "1", "shop_name": "甲店", "position": 1},
                       {"product_id": "9", "shop_name": "丙店", "position": 2}]}
    prototypes = [
        {"product_id": "1", "image_sha256": "1" * 64, "style_ids": ["PS-A"], "boundary_reason": None},
        {"product_id": "2", "image_sha256": "2" * 64, "style_ids": ["PS-A"], "boundary_reason": None},
        {"product_id": "3", "image_sha256": "3" * 64, "style_ids": [], "boundary_reason": "实物难辨"},
    ]
    return {"visual": visual, "prototype_labels": prototypes, "price": price, "title": title,
            "geography": geography, "advertising": advertising}


class OpportunityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = fixture()
        self.paths = {}
        for name, value in self.docs.items():
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            self.paths[name] = str(path)

    def args(self, output="result.json"):
        return SimpleNamespace(visual_labels=self.paths["visual"],
                               prototype_labels=self.paths["prototype_labels"],
                               price_detail=self.paths["price"],
                               title_roots=self.paths["title"],
                               geography_detail=self.paths["geography"],
                               advertiser_detail=self.paths["advertising"],
                               output=str(self.root / output))

    def rewrite(self, name):
        Path(self.paths[name]).write_text(json.dumps(self.docs[name], ensure_ascii=False), encoding="utf-8")

    def test_join_keeps_uncertain_outside_candidates_and_ads_separate(self):
        MODULE.build(self.args())
        result = json.loads((self.root / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["population"]["natural_products"], 3)
        self.assertEqual(result["population"]["visual_tagged"], 2)
        self.assertEqual(result["population"]["visual_uncertain"], 1)
        self.assertEqual(result["population"]["advertising_unique_products"], 2)
        form = next(c for c in result["candidates"] if c["axis"] == "form")
        self.assertEqual(form["product_count"], 2)
        self.assertEqual(form["shop_count"], 2)
        self.assertEqual(form["displayed_payment_people"]["sum_after_excluding_top_shop"], 40)
        self.assertEqual(form["natural_advertised_product_count_same_shop"], 1)
        self.assertEqual(len(form["product_ids"]), 2)
        self.assertTrue(all("3" not in c["product_ids"] for c in result["candidates"]))
        self.assertEqual(len([c for c in result["candidates"] if c["axis"] == "form_style_task"]), 2)
        prototype = next(c for c in result["candidates"] if c["axis"] == "product_style")
        self.assertEqual(prototype["product_ids"], ["1", "2"])
        self.assertIn("prototype_labels", result["sources"])

    def test_missing_prototype_labels_rejected(self):
        args = self.args()
        args.prototype_labels = None
        with self.assertRaisesRegex(ValueError, "prototype labels are required"):
            MODULE.build(args)

    def test_prototype_hash_mismatch_rejected(self):
        self.docs["prototype_labels"][0]["image_sha256"] = "f" * 64
        self.rewrite("prototype_labels")
        with self.assertRaisesRegex(ValueError, "image hash disagrees"):
            MODULE.build(self.args())

    def test_source_mismatch_rejected(self):
        self.docs["title"]["source"]["sha256"] = "b" * 64
        self.rewrite("title")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            MODULE.build(self.args())

    def test_unobserved_oversize_product_remains_in_population(self):
        self.docs["visual"]["records"] = self.docs["visual"]["records"][:2]
        self.docs["prototype_labels"] = self.docs["prototype_labels"][:2]
        self.rewrite("visual")
        self.rewrite("prototype_labels")
        MODULE.build(self.args())
        result = json.loads((self.root / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["population"]["natural_products"], 3)
        self.assertEqual(result["population"]["visual_not_observed"], 1)
        product = next(item for item in result["products"] if item["product_id"] == "3")
        self.assertEqual(product["visual_status"], "not_observed")
        self.assertTrue(all("3" not in card["product_ids"] for card in result["candidates"]))

    def test_field_conflict_rejected(self):
        self.docs["geography"]["natural_products"][0]["shop_name"] = "另一店"
        self.rewrite("geography")
        with self.assertRaisesRegex(ValueError, "disagrees on shop_name"):
            MODULE.build(self.args())

    def test_duplicate_visual_id_rejected(self):
        self.docs["visual"]["records"].append(self.docs["visual"]["records"][0])
        self.rewrite("visual")
        with self.assertRaisesRegex(ValueError, "duplicate product_id"):
            MODULE.build(self.args())

    def test_existing_output_is_preserved(self):
        output = self.root / "result.json"
        output.write_text("user-owned", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            MODULE.build(self.args())
        self.assertEqual(output.read_text(encoding="utf-8"), "user-owned")


if __name__ == "__main__":
    unittest.main()
