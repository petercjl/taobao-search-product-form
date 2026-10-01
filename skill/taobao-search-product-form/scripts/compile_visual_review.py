#!/usr/bin/env python3
"""Compile a visually reviewed position ledger to product/image-linked labels."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        parser.error("output already exists; choose a new path")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    products = {p["product_id"]: p for p in manifest["products"]}
    selected = manifest["selected_organic_ids"] + manifest["selected_ad_only_ids"]
    positions = {}
    for pid in selected:
        p = products[pid]
        key = "N" + str(p["first_natural"]) if p["first_natural"] else "A" + str(p["first_ad"])
        if key in positions:
            raise ValueError(f"duplicate display-position key: {key}")
        positions[key] = pid
    labeled = {}
    for group in review["groups"]:
        eligibility = group["eligibility"]
        form = group.get("form")
        evidence = group.get("visible_evidence")
        for key in group["positions"]:
            if key not in positions or key in labeled:
                raise ValueError(f"unknown or duplicate reviewed position: {key}")
            pid = positions[key]
            fetch = manifest["fetches"].get(pid, {})
            if fetch.get("status") != "ok":
                raise ValueError(f"image unavailable for {key}")
            labeled[key] = {
                "product_id": pid,
                "image_path": fetch["path"],
                "eligibility": eligibility,
                "form": form if eligibility == "target" else None,
                "visible_evidence": evidence,
                "confidence": "medium" if eligibility == "uncertain" else "high",
                "review_position": key,
            }
    missing = set(positions) - set(labeled)
    if missing:
        raise ValueError(f"review is incomplete; missing: {sorted(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "search_term": manifest["search_term"], "scope": manifest["scope"], "review_basis": review["review_basis"], "labels": list(labeled.values())}, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "labels": len(labeled)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
