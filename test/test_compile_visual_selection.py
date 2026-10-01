import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "compile_visual_selection.py"


class ThreeAxisCompileTest(unittest.TestCase):
    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_three_axes_and_evidence_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = {"scope": {"selected": 3, "ready": 2, "image_unavailable": 1, "manifest_natural_total": 3},
                    "items": [{"product_id": pid, "status": "ready", "batch_id": "B001",
                               "image_sha256": pid * 64, "image_path": f"/tmp/{pid}.jpg", "source_rank": n}
                              for n, pid in enumerate(("a", "b"), 1)] +
                             [{"product_id": "c", "status": "image_unavailable", "unavailable_reason": "too_large"}]}
            registry = {"schema_version": 2, "version": "test", "form": {"round": {}},
                        "style": {"warm": {}}, "audience": {"single meal": {}}}
            observations = {"schema_version": 2, "observations": [
                {"product_id": "a", "status": "tagged", "visible_evidence": "round pale pan",
                 "form": {"candidate": "round"},
                 "style": {"candidate": "warm", "product_cues": ["pale body", "wood handle"],
                           "physical_delta": "pale body and wood handle"},
                 "audience": {"candidate": "single meal", "task_cues": ["small size"],
                              "evidence_tier": "image_only", "physical_delta": "small diameter"}},
                {"product_id": "b", "status": "tagged", "visible_evidence": "plain black round pan",
                 "form": {"candidate": "round"}, "style": {"candidate": None},
                 "audience": {"candidate": None}}]}
            paths = []
            for name, value in (("plan", plan), ("registry", registry), ("observations", observations)):
                path = root / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                paths.append(path)
            out = root / "compiled"
            self.run_cli("--plan", paths[0], "--registry", paths[1],
                         "--observations", paths[2], "--output-dir", out)
            summary = json.loads((out / "label_summary.json").read_text())
            self.assertEqual(summary["reviewed_products"], 2)
            self.assertEqual(summary["image_unavailable_by_reason"], {"too_large": 1})
            self.assertEqual(summary["axes"]["style"]["unclassified_products"], 1)
            self.assertEqual(summary["axes"]["audience"]["canonical_counts"], {"single meal": 1})
            self.run_cli("--plan", paths[0], "--registry", paths[1],
                         "--observations", paths[2], "--output-dir", out, success=False)
            observations["observations"][0]["style"]["product_cues"] = ["pale body"]
            bad = root / "bad.json"
            bad.write_text(json.dumps(observations), encoding="utf-8")
            self.run_cli("--plan", paths[0], "--registry", paths[1],
                         "--observations", bad, "--output-dir", root / "bad-output", success=False)


if __name__ == "__main__":
    unittest.main()
