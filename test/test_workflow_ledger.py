import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "taobao-search-product-form" / "scripts" / "workflow_ledger.py"


def call(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True)


class WorkflowLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "search.xlsx"
        self.input.write_bytes(b"workbook fixture")
        self.run_dir = self.root / "run"
        self.ledger = self.run_dir / "ledger.json"

    def init(self, mode="development"):
        result = call("init", "--run-dir", self.run_dir, "--mode", mode, "--input", self.input)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_development_ledger_and_recoverable_update(self):
        self.init()
        result = call("init", "--run-dir", self.run_dir, "--mode", "development", "--input", self.input)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        result = call("record", "--ledger", self.ledger, "--stage", "clean", "--status", "approved")
        self.assertNotEqual(result.returncode, 0)
        result = call("record", "--ledger", self.ledger, "--stage", "classify/visual-form",
                      "--status", "awaiting_review", "--design-state", "defined",
                      "--artifact", self.input, "--note", "Image ledger checked")
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(Path(response["backup"]).is_file())
        document = json.loads(self.ledger.read_text(encoding="utf-8"))
        stage = document["stages"]["classify/visual-form"]
        self.assertEqual(stage["status"], "awaiting_review")
        self.assertEqual(stage["artifacts"][0]["path"], str(self.input.resolve()))
        self.assertEqual(stage["artifacts"][0]["bytes"], self.input.stat().st_size)
        result = call("record", "--ledger", self.ledger, "--stage", "classify/visual-form",
                      "--status", "approved", "--reviewer", "user", "--note", "Confirmed")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(document["stages"]["classify/visual-form"]["review"]["reviewer"], "user")

    def test_missing_artifact_cannot_change_ledger(self):
        self.init()
        original = self.ledger.read_bytes()
        result = call("record", "--ledger", self.ledger, "--stage", "clean", "--status", "awaiting_review",
                      "--artifact", self.root / "missing.json", "--note", "test")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_run_mode_automatic_verification(self):
        self.init("run")
        result = call("record", "--ledger", self.ledger, "--stage", "input", "--status", "verified",
                      "--note", "Source hash and fields checked")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = call("record", "--ledger", self.ledger, "--stage", "input", "--status", "approved",
                      "--reviewer", "user", "--note", "not permitted")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
