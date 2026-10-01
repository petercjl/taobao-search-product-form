import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "visual_form_pipeline.py"


class VisualFormPipelineTest(unittest.TestCase):
    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_plan_bind_reduce_and_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            images = root / "images"
            images.mkdir()
            for pid, color in [("1", "red"), ("2", "blue")]:
                Image.new("RGB", (40, 40), color).save(images / f"{pid}.jpg")
            manifest = {"products": [{"product_id": "1", "organic_rank": 1},
                                      {"product_id": "2", "organic_rank": 2},
                                      {"product_id": "3", "organic_rank": 3}],
                        "selected_organic_ids": ["1", "2", "3"],
                        "scope": {"organic_total": 3},
                        "fetches": {**{pid: {"status": "ok", "path": f"images/{pid}.jpg"}
                                        for pid in ("1", "2")}, "3": {"status": "too_large"}}}
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            plan_dir = root / "planned"
            self.run_cli("plan", "--manifest", manifest_path, "--batch-size", 1,
                         "--output-dir", plan_dir)
            self.run_cli("plan", "--manifest", manifest_path, "--output-dir", plan_dir,
                         success=False)
            plan = json.loads((plan_dir / "visual_batch_plan.json").read_text())
            self.assertEqual(len(plan["batches"]), 2)
            self.assertEqual(len({pid for b in plan["batches"] for pid in b["product_ids"]}), 2)
            self.assertEqual(plan["scope"]["image_unavailable"], 1)
            self.assertEqual(next(item for item in plan["items"] if item["product_id"] == "3")["unavailable_reason"], "too_large")
            draft = {"schema_version": 1, "observations": [
                {"product_id": pid, "status": "tagged", "primary_form_candidate": label,
                 "visible_evidence": "visible round pan", "facets": {"outline": "round"}}
                for pid, label in [("1", "round pan"), ("2", "circular pan")]]}
            draft_path = root / "draft.json"
            draft_path.write_text(json.dumps(draft))
            obs_path = root / "observations.json"
            self.run_cli("bind", "--plan", plan_dir / "visual_batch_plan.json",
                         "--draft", draft_path, "--output", obs_path)
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps({"schema_version": 1, "version": "test-v1",
                                                 "primary_forms": {"round pan": {"aliases": ["circular pan"]}}}))
            result_dir = root / "result"
            self.run_cli("reduce", "--plan", plan_dir / "visual_batch_plan.json",
                         "--observations", obs_path, "--registry", registry_path,
                         "--output-dir", result_dir)
            summary = json.loads((result_dir / "visual_form_summary.json").read_text())
            self.assertEqual(summary["candidate_label_count"], 2)
            self.assertEqual(summary["canonical_forms"], {"round pan": 2})
            self.assertTrue(summary["qa"]["all_labels_resolved"])
            tampered = json.loads(obs_path.read_text())
            tampered["observations"][1]["image_sha256"] = "wrong"
            tampered_path = root / "tampered.json"
            tampered_path.write_text(json.dumps(tampered))
            self.run_cli("reduce", "--plan", plan_dir / "visual_batch_plan.json",
                         "--observations", tampered_path, "--registry", registry_path,
                         "--output-dir", root / "bad-result", success=False)


if __name__ == "__main__":
    unittest.main()
