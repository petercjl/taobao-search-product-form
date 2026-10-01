#!/usr/bin/env python3
"""Validate image-bound product-style decisions and compile reusable evidence."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    plan, observations, decisions = map(load, (args.plan, args.observations, args.decisions))
    require(decisions.get("schema_version") == 1, "decisions.schema_version must be 1")
    require(decisions.get("source_plan_sha256") == digest(args.plan), "plan checksum mismatch")
    require(decisions.get("source_observations_sha256") == digest(args.observations), "observations checksum mismatch")
    items = {str(item["product_id"]): item for item in plan["items"] if item["status"] == "ready"}
    require(len(items) == sum(item["status"] == "ready" for item in plan["items"]), "duplicate ready IDs")
    raw = {str(item["product_id"]): item for item in observations["records"]}
    require(len(raw) == len(observations["records"]) == len(items), "observation population mismatch")
    require(set(raw) == set(items), "observation IDs differ from ready image IDs")
    for product_id, item in items.items():
        require(raw[product_id]["image_sha256"] == item["image_sha256"], f"raw image hash mismatch: {product_id}")

    prototypes = decisions.get("prototypes", [])
    prototype_ids = [entry["style_id"] for entry in prototypes]
    require(len(prototype_ids) == len(set(prototype_ids)) and prototypes, "duplicate or missing prototypes")
    for entry in prototypes:
        for field in ("style_id", "name", "definition", "selection_difference", "boundary", "representative_ids"):
            require(entry.get(field), f"prototype {entry.get('style_id')} lacks {field}")
        require(isinstance(entry["representative_ids"], list), "representative_ids must be a list")

    records = decisions.get("assignments", [])
    assigned_ids = [str(row["product_id"]) for row in records]
    require(len(records) == len(items) == len(set(assigned_ids)), "assignment population/duplicates mismatch")
    require(set(assigned_ids) == set(items), "assignment IDs differ from ready image IDs")
    by_id = {str(row["product_id"]): row for row in records}
    groups = {style_id: [] for style_id in prototype_ids}
    labels = []
    uncertainty = []
    for product_id, item in items.items():
        row = by_id[product_id]
        style_ids = row.get("style_ids", [])
        boundary_reason = row.get("boundary_reason")
        require(row.get("image_sha256") == item["image_sha256"], f"decision image hash mismatch: {product_id}")
        require(isinstance(style_ids, list) and len(style_ids) == len(set(style_ids)), f"invalid style IDs: {product_id}")
        require(all(style_id in groups for style_id in style_ids), f"unknown prototype: {product_id}")
        require(bool(style_ids) != bool(boundary_reason), f"assign style(s) or boundary: {product_id}")
        require(row.get("reason") and row.get("confidence") in ("high", "medium", "low"), f"missing reason/confidence: {product_id}")
        for style_id in style_ids:
            groups[style_id].append(product_id)
        if row["confidence"] == "low" or boundary_reason:
            uncertainty.append(product_id)
        labels.append({
            "product_id": product_id,
            "image_path": item["image_path"],
            "image_sha256": item["image_sha256"],
            "source_rank": item.get("source_rank"),
            "batch_id": item.get("batch_id"),
            "style_ids": style_ids,
            "variant_or_features": row.get("variant_or_features", []),
            "reason": row["reason"],
            "confidence": row["confidence"],
            "boundary_reason": boundary_reason,
            "visible_evidence": raw[product_id].get("visible_evidence"),
        })
    for entry in prototypes:
        style_id = entry["style_id"]
        require(groups[style_id], f"empty prototype: {style_id}")
        require(all(str(pid) in groups[style_id] for pid in entry["representative_ids"]), f"representative outside group: {style_id}")

    out = Path(args.output_dir)
    require(not out.exists(), "output directory already exists; choose a new versioned path")
    out.mkdir(parents=True)
    summary = [{**entry, "product_count": len(groups[entry["style_id"]]), "product_ids": groups[entry["style_id"]]} for entry in prototypes]
    audit = {
        "source_plan_sha256": digest(args.plan),
        "source_observations_sha256": digest(args.observations),
        "source_decisions_sha256": digest(args.decisions),
        "ready_count": len(items),
        "assigned_count": len(labels),
        "classified_count": sum(bool(row["style_ids"]) for row in labels),
        "boundary_count": sum(bool(row["boundary_reason"]) for row in labels),
        "multi_style_count": sum(len(row["style_ids"]) > 1 for row in labels),
        "memberships": sum(len(row["style_ids"]) for row in labels),
        "prototype_count": len(prototypes),
        "confidence_counts": dict(Counter(row["confidence"] for row in labels)),
        "review_ids": uncertainty,
    }
    for name, data in (("product_style_labels.json", labels), ("style_prototype_summary.json", summary), ("style_prototype_audit.json", audit)):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(out), **{key: audit[key] for key in ("ready_count", "classified_count", "boundary_count", "prototype_count", "memberships")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
