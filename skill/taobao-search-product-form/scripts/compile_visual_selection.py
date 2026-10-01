#!/usr/bin/env python3
"""Validate and compile three-axis image observations for selection review.

This script checks provenance and evidence contracts; it does not infer labels
from pixels or declare product-market opportunity.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def map_labels(registry, dimension):
    owner = {}
    for canonical, info in registry.get(dimension, {}).items():
        for alias in [canonical, *info.get("aliases", [])]:
            key = alias.strip().casefold()
            if not key or key in owner and owner[key] != canonical:
                raise ValueError(f"invalid or conflicting {dimension} alias: {alias}")
            owner[key] = canonical
    return owner


def clean_text(value):
    return str(value or "").strip()


def compile_run(args):
    plan = load(args.plan)
    draft = load(args.observations)
    registry = load(args.registry)
    if draft.get("schema_version") != 2 or registry.get("schema_version") != 2:
        raise ValueError("three-axis observations and registry require schema_version 2")
    expected = {str(item["product_id"]): item for item in plan["items"] if item["status"] == "ready"}
    entries = draft.get("observations", [])
    ids = [str(item.get("product_id", "")) for item in entries]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError(f"one observation per ready image required; missing={sorted(set(expected)-set(ids))}, extra={sorted(set(ids)-set(expected))}")
    maps = {axis: map_labels(registry, axis) for axis in ("form", "style", "audience")}
    raw = []
    products = []
    unresolved = defaultdict(Counter)
    candidates = defaultdict(Counter)
    counts = defaultdict(Counter)
    examples = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        pid = str(entry["product_id"])
        source = expected[pid]
        if not clean_text(entry.get("visible_evidence")):
            raise ValueError(f"missing visible evidence: {pid}")
        status = entry.get("status")
        if status not in ("tagged", "uncertain"):
            raise ValueError(f"invalid status: {pid}")
        bound = {**entry, "product_id": pid, "batch_id": source["batch_id"],
                 "image_sha256": source["image_sha256"], "image_path": source["image_path"],
                 "source_rank": source["source_rank"]}
        row = {"product_id": pid, "source_rank": source["source_rank"],
               "batch_id": source["batch_id"], "image_path": source["image_path"],
               "image_sha256": source["image_sha256"], "status": status,
               "visible_evidence": entry["visible_evidence"],
               "image_presentation": clean_text(entry.get("image_presentation"))}
        for axis in ("form", "style", "audience"):
            item = entry.get(axis)
            if not isinstance(item, dict):
                raise ValueError(f"missing {axis} object: {pid}")
            candidate = clean_text(item.get("candidate"))
            if axis == "form" and status == "tagged" and not candidate:
                raise ValueError(f"tagged product needs form candidate: {pid}")
            if axis == "style" and candidate:
                cues = item.get("product_cues", [])
                if not isinstance(cues, list) or len([x for x in cues if clean_text(x)]) < 2 or not clean_text(item.get("physical_delta")):
                    raise ValueError(f"style requires two product cues and physical delta: {pid}")
            if axis == "audience" and candidate:
                cues = item.get("task_cues", [])
                if not isinstance(cues, list) or not any(clean_text(x) for x in cues) or not clean_text(item.get("physical_delta")):
                    raise ValueError(f"audience requires task cue and physical delta: {pid}")
                if item.get("evidence_tier") not in ("image_only", "combined"):
                    raise ValueError(f"audience evidence tier required: {pid}")
            canonical = maps[axis].get(candidate.casefold()) if candidate else None
            if candidate:
                candidates[axis][candidate] += 1
                if canonical is None:
                    unresolved[axis][candidate] += 1
            if canonical:
                counts[axis][canonical] += 1
                if len(examples[axis][canonical]) < 3:
                    examples[axis][canonical].append(pid)
            row[axis] = {**item, "candidate": candidate or None, "label": canonical}
        raw.append(bound)
        products.append(row)
    products.sort(key=lambda item: item["source_rank"])
    unavailable_reasons = Counter(item.get("unavailable_reason", "unknown")
                                  for item in plan["items"] if item["status"] == "image_unavailable")
    summary = {"schema_version": 2, "strategy": "visual-selection-three-axis-v1",
               "source_plan_sha256": sha256(args.plan), "source_observations_sha256": sha256(args.observations),
               "registry_sha256": sha256(args.registry), "registry_version": registry.get("version"),
               "scope": plan["scope"], "reviewed_products": len(products),
               "image_unavailable_by_reason": dict(unavailable_reasons),
               "axes": {axis: {"candidate_labels": dict(candidates[axis]),
                                "canonical_counts": dict(counts[axis]),
                                "examples": dict(examples[axis]),
                                "unresolved": dict(unresolved[axis]),
                                "unclassified_products": sum(not row[axis]["label"] for row in products)}
                        for axis in ("form", "style", "audience")},
               "qa": {"one_record_per_ready_image": True, "image_hash_bound": True,
                      "unavailable_reasons_reconciled": sum(unavailable_reasons.values()) == plan["scope"]["image_unavailable"],
                      "all_candidates_resolved": not any(unresolved.values()),
                      "physical_deltas_checked": True},
               "interpretation_boundary": "Pilot product labels and supply descriptions; not actual buyer demographics or proven white-label opportunity."}
    out = Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    save(out / "raw_observations.json", {"schema_version": 2, "records": raw})
    save(out / "product_labels.json", {"schema_version": 2, "records": products})
    save(out / "label_summary.json", summary)
    print(json.dumps({"output_dir": str(out), "products": len(products),
                      "counts": {axis: dict(counts[axis]) for axis in counts},
                      "unresolved": {axis: dict(unresolved[axis]) for axis in unresolved}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output-dir", required=True)
    compile_run(parser.parse_args())
