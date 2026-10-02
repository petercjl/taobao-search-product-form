#!/usr/bin/env python3
"""Render and validate a report with this package's pinned HTML runtime."""

import argparse
import json
import sys
from pathlib import Path


RUNTIME = Path(__file__).resolve().parents[1] / "report_runtime"
sys.path.insert(0, str(RUNTIME))

from renderer import render_file  # noqa: E402
from validator import validate_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Existing compact-workbench@1.0 ViewModel JSON")
    parser.add_argument("--output", required=True, help="New standalone HTML report path")
    args = parser.parse_args()
    rendered = render_file(args.input, args.output)
    checked = validate_file(args.output)
    result = {"ok": checked["ok"], "render": rendered, "validation": checked}
    print(json.dumps(result, ensure_ascii=False))
    if not checked["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
