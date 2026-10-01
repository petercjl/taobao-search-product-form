#!/usr/bin/env python3
"""Checkpoint image-grounded observations one visual batch at a time.

This tool validates membership and provenance. It never generates semantic labels.
"""

import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ready_batches(plan):
    items = {str(item["product_id"]): item for item in plan["items"] if item["status"] == "ready"}
    batches = {batch["batch_id"]: batch for batch in plan["batches"]}
    if len(items) != plan["scope"]["ready"]:
        raise ValueError("ready-image count mismatch")
    return items, batches


def validate_batch(plan_path, batch_id, doc):
    plan = read(plan_path)
    items, batches = ready_batches(plan)
    if batch_id not in batches:
        raise ValueError(f"unknown batch: {batch_id}")
    expected = set(batches[batch_id]["product_ids"])
    rows = doc.get("observations")
    if not isinstance(rows, list):
        raise ValueError("observations must be an array")
    ids = [str(row.get("product_id", "")) for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError(f"batch coverage mismatch: missing={sorted(expected-set(ids))}, extra={sorted(set(ids)-expected)}")
    bound = []
    for row in rows:
        item = items[str(row["product_id"])]
        if item["batch_id"] != batch_id:
            raise ValueError(f"batch membership mismatch: {row['product_id']}")
        if row.get("batch_id", batch_id) != batch_id or row.get("image_sha256", item["image_sha256"]) != item["image_sha256"]:
            raise ValueError(f"image provenance mismatch: {row['product_id']}")
        if row.get("status") not in ("tagged", "uncertain") or not str(row.get("visible_evidence", "")).strip():
            raise ValueError(f"missing status or visible evidence: {row['product_id']}")
        if any(not isinstance(row.get(axis), dict) for axis in ("form", "style", "audience")):
            raise ValueError(f"three axes required: {row['product_id']}")
        bound.append({**row, "product_id": str(row["product_id"]), "batch_id": batch_id,
                      "image_sha256": item["image_sha256"]})
    return {"schema_version": 2, "batch_id": batch_id, "plan_sha256": digest(plan_path),
            "observations": bound}


def checked_files(plan_path, batch_dir):
    plan = read(plan_path)
    _, batches = ready_batches(plan)
    folder = Path(batch_dir)
    found = {}
    if folder.exists():
        for path in sorted(folder.glob("B*.json")):
            batch_id = path.stem
            if batch_id not in batches:
                raise ValueError(f"unexpected batch file: {path}")
            doc = read(path)
            if doc.get("plan_sha256") != digest(plan_path) or doc.get("batch_id") != batch_id:
                raise ValueError(f"stale or mismatched batch file: {path}")
            validated = validate_batch(plan_path, batch_id, doc)
            found[batch_id] = validated["observations"]
    return batches, found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("commit", "status", "merge"):
        command = commands.add_parser(name)
        command.add_argument("--plan", required=True)
        command.add_argument("--batch-dir", required=True)
        if name == "commit":
            command.add_argument("--batch-id", required=True)
            command.add_argument("--draft", required=True)
        if name == "merge":
            command.add_argument("--output", required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan).resolve()
    batch_dir = Path(args.batch_dir).resolve()
    batches, found = checked_files(plan_path, batch_dir)
    if args.command == "commit":
        if args.batch_id in found:
            raise FileExistsError(batch_dir / f"{args.batch_id}.json")
        validated = validate_batch(plan_path, args.batch_id, read(args.draft))
        batch_dir.mkdir(parents=True, exist_ok=True)
        path = batch_dir / f"{args.batch_id}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        found[args.batch_id] = validated["observations"]
    missing = [batch_id for batch_id in batches if batch_id not in found]
    if args.command == "merge":
        if missing:
            raise ValueError(f"incomplete visual observations: {len(missing)} batches remain; next={missing[0]}")
        rows = [row for batch_id in batches for row in found[batch_id]]
        output = Path(args.output).resolve()
        with output.open("x", encoding="utf-8") as stream:
            json.dump({"schema_version": 2, "observations": rows}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({"completed_batches": len(found), "total_batches": len(batches),
                      "observed_products": sum(len(rows) for rows in found.values()),
                      "next_batch": missing[0] if missing else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
