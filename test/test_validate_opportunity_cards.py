import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "validate_opportunity_cards.py"
SPEC = importlib.util.spec_from_file_location("validate_opportunity_cards", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample():
    evidence = {"sources": {"prototype_labels": {"sha256": "a" * 64}},
                "products": [{"product_id": "1"}],
                "candidates": [{"candidate_id": "c-1", "axis": "product_style", "product_ids": ["1"],
                                "product_count": 1, "displayed_price_yuan": {"median": 50}}]}
    card = {"candidate_id": "c-1", "definition": "test", "parent_comparison": "parent",
            "scope": "one product", "interpretation": "uncertain",
            "observations": [{"claim": "one", "refs": ["c-1.product_count"]}],
            "supporting_evidence": [{"claim": "visible", "refs": ["1"]}],
            "counterevidence": [{"claim": "price unknown", "refs": ["c-1.displayed_price_yuan.median"]}],
            "unknowns": ["cost"],
            "next_checks": [{"question": "check cost", "changes_assessment_if": "margin fails"}],
            "research_order": {"position": 1, "reason": "first check"}}
    return {"schema_version": 2, "source_evidence_sha256": "b" * 64, "cards": [card]}, evidence


class OpportunityCardValidationTests(unittest.TestCase):
    def test_valid_card(self):
        cards, evidence = sample()
        self.assertEqual(MODULE.validate(cards, evidence, "b" * 64)["cards"], 1)

    def test_stale_evidence_hash_rejected(self):
        cards, evidence = sample()
        with self.assertRaisesRegex(ValueError, "current comparison evidence hash"):
            MODULE.validate(cards, evidence, "c" * 64)

    def test_secondary_axis_card_rejected(self):
        cards, evidence = sample()
        evidence["candidates"][0]["axis"] = "form_variant_task"
        with self.assertRaisesRegex(ValueError, "product-style candidates"):
            MODULE.validate(cards, evidence, "b" * 64)

    def test_secondary_axis_card_with_prototype_present_rejected(self):
        cards, evidence = sample()
        evidence["candidates"].append({"candidate_id": "c-2", "axis": "form_variant_task", "product_ids": ["1"]})
        cards["cards"][0]["candidate_id"] = "c-2"
        with self.assertRaisesRegex(ValueError, "whole-product style prototype"):
            MODULE.validate(cards, evidence, "b" * 64)

    def test_broken_evidence_reference(self):
        cards, evidence = sample()
        cards["cards"][0]["observations"][0]["refs"] = ["c-1.no_such_field"]
        with self.assertRaisesRegex(ValueError, "missing evidence field"):
            MODULE.validate(cards, evidence, "b" * 64)

    def test_foreign_product_reference(self):
        cards, evidence = sample()
        evidence["products"].append({"product_id": "2"})
        cards["cards"][0]["supporting_evidence"][0]["refs"] = ["2"]
        with self.assertRaisesRegex(ValueError, "not a member"):
            MODULE.validate(cards, evidence, "b" * 64)

    def test_score_is_rejected(self):
        cards, evidence = sample()
        cards["cards"][0]["score"] = 87
        with self.assertRaisesRegex(ValueError, "composite score"):
            MODULE.validate(cards, evidence, "b" * 64)


if __name__ == "__main__":
    unittest.main()
