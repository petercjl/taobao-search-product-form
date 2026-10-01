import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "visual_observation_batches.py"


class VisualObservationBatchTests(unittest.TestCase):
    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_checkpoint_resume_merge_and_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = {"scope": {"ready": 2}, "items": [
                {"product_id": "1", "status": "ready", "batch_id": "B001", "image_sha256": "a" * 64},
                {"product_id": "2", "status": "ready", "batch_id": "B002", "image_sha256": "b" * 64},
                {"product_id": "3", "status": "image_unavailable", "unavailable_reason": "too_large"}],
                "batches": [{"batch_id": "B001", "product_ids": ["1"]},
                            {"batch_id": "B002", "product_ids": ["2"]}]}
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            batch_dir = root / "checkpoints"
            first = root / "first.json"
            first.write_text(json.dumps({"schema_version": 2, "observations": [
                {"product_id": "1", "status": "tagged", "visible_evidence": "round handled vessel",
                 "form": {"candidate": "handled pot"}, "style": {"candidate": None},
                 "audience": {"candidate": None}}]}), encoding="utf-8")
            initial = json.loads(self.run_cli("status", "--plan", plan_path, "--batch-dir", batch_dir).stdout)
            self.assertEqual(initial["next_batch"], "B001")
            self.run_cli("commit", "--plan", plan_path, "--batch-dir", batch_dir,
                         "--batch-id", "B001", "--draft", first)
            self.assertEqual(json.loads((batch_dir / "B001.json").read_text())["observations"][0]["image_sha256"], "a" * 64)
            self.assertEqual(json.loads(self.run_cli("status", "--plan", plan_path, "--batch-dir", batch_dir).stdout)["next_batch"], "B002")
            self.run_cli("commit", "--plan", plan_path, "--batch-dir", batch_dir,
                         "--batch-id", "B001", "--draft", first, success=False)
            self.run_cli("merge", "--plan", plan_path, "--batch-dir", batch_dir,
                         "--output", root / "incomplete.json", success=False)
            second = root / "second.json"
            second.write_text(json.dumps({"schema_version": 2, "observations": [
                {"product_id": "2", "status": "uncertain", "visible_evidence": "partly obscured pot",
                 "form": {"candidate": None}, "style": {"candidate": None},
                 "audience": {"candidate": None}}]}), encoding="utf-8")
            self.run_cli("commit", "--plan", plan_path, "--batch-dir", batch_dir,
                         "--batch-id", "B002", "--draft", second)
            output = root / "merged.json"
            self.run_cli("merge", "--plan", plan_path, "--batch-dir", batch_dir, "--output", output)
            self.assertEqual([row["product_id"] for row in json.loads(output.read_text())["observations"]], ["1", "2"])
            self.run_cli("merge", "--plan", plan_path, "--batch-dir", batch_dir, "--output", output, success=False)


if __name__ == "__main__":
    unittest.main()
