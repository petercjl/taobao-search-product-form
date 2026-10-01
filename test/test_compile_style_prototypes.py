import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "compile_style_prototypes.py"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CompileStylePrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = self.root / "plan.json"
        self.observations = self.root / "observations.json"
        self.decisions = self.root / "decisions.json"
        plan_sha = write_json(self.plan, {"items": [
            {"product_id": "1", "status": "ready", "image_sha256": "1" * 64, "image_path": "one.jpg"},
            {"product_id": "2", "status": "ready", "image_sha256": "2" * 64, "image_path": "two.jpg"},
            {"product_id": "3", "status": "too_large", "image_sha256": "3" * 64, "image_path": "three.jpg"},
        ]})
        observations_sha = write_json(self.observations, {"records": [
            {"product_id": "1", "image_sha256": "1" * 64, "visible_evidence": "单柄完整锅体"},
            {"product_id": "2", "image_sha256": "2" * 64, "visible_evidence": "主图有两种锅体"},
        ]})
        self.data = {
            "schema_version": 1, "source_plan_sha256": plan_sha,
            "source_observations_sha256": observations_sha,
            "prototypes": [
                {"style_id": "A", "name": "单柄小锅", "definition": "完整单柄小锅", "selection_difference": "普通小锅方案",
                 "boundary": "同款尺寸为变体", "representative_ids": ["1"]},
                {"style_id": "B", "name": "带蒸层小锅", "definition": "完整蒸煮配置锅", "selection_difference": "蒸煮配置方案",
                 "boundary": "单独蒸屉不纳入", "representative_ids": ["2"]},
            ],
            "assignments": [
                {"product_id": "1", "image_sha256": "1" * 64, "style_ids": ["A"], "reason": "完整单柄锅", "confidence": "high"},
                {"product_id": "2", "image_sha256": "2" * 64, "style_ids": ["A", "B"], "reason": "主图含两款实物", "confidence": "medium"},
            ],
        }

    def run_compiler(self, data, output):
        write_json(self.decisions, data)
        return subprocess.run([sys.executable, str(SCRIPT), "--plan", str(self.plan),
                               "--observations", str(self.observations), "--decisions", str(self.decisions),
                               "--output-dir", str(output)], capture_output=True, text=True)

    def test_full_ready_coverage_and_multi_style_membership(self):
        output = self.root / "compiled"
        result = self.run_compiler(self.data, output)
        self.assertEqual(result.returncode, 0, result.stderr)
        audit = json.loads((output / "style_prototype_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["ready_count"], 2)
        self.assertEqual(audit["multi_style_count"], 1)
        self.assertEqual(audit["memberships"], 3)
        self.assertEqual(len(json.loads((output / "product_style_labels.json").read_text(encoding="utf-8"))), 2)

    def test_missing_ready_product_decision_fails_without_output(self):
        self.data["assignments"].pop()
        output = self.root / "invalid"
        result = self.run_compiler(self.data, output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assignment population", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
