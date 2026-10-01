#!/usr/bin/env python3
"""Prepare and apply an auditable, category-neutral visual-form hierarchy.

Semantic family decisions are made by the host Agent from class profiles and
representative image observations. This script validates and applies them; it
never derives form identity from title, price, payments, or a preset class list.
Outputs must be new paths so raw image observations remain immutable.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def grams(value):
    text = re.sub(r"\s+", "", value.casefold())
    if len(text) < 2:
        return {text}
    return {text[index:index + 2] for index in range(len(text) - 1)}


def similarity(left, right):
    a, b = grams(left), grams(right)
    return round(len(a & b) / len(a | b), 3) if a | b else 0.0


def prepare(labels_path, summary_path, output_path):
    labels, summary = load(labels_path), load(summary_path)
    records = labels["records"]
    counts = summary["axes"]["form"]["canonical_counts"]
    by_label = defaultdict(list)
    for row in records:
        name = row["form"].get("label")
        if name:
            by_label[name].append(row)
    if {name: len(rows) for name, rows in by_label.items()} != counts:
        raise ValueError("form summary and product labels disagree")
    profiles = []
    for name, rows in sorted(by_label.items(), key=lambda item: (-len(item[1]), item[0])):
        examples = sorted(rows, key=lambda row: row["source_rank"])[:3]
        profiles.append({
            "source_label": name,
            "products": len(rows),
            "candidate_words": dict(Counter(row["form"].get("candidate") for row in rows).most_common(8)),
            "style_counts": dict(Counter(row["style"].get("label") for row in rows if row["style"].get("label")).most_common(5)),
            "task_counts": dict(Counter(row["audience"].get("label") for row in rows if row["audience"].get("label")).most_common(5)),
            "examples": [{"product_id": row["product_id"], "visible_evidence": row["visible_evidence"],
                          "image_path": row["image_path"]} for row in examples],
        })
    neighbors = []
    for index, first in enumerate(profiles):
        options = sorted(({"source_label": other["source_label"],
                           "name_similarity": similarity(first["source_label"], other["source_label"])}
                          for j, other in enumerate(profiles) if j != index),
                         key=lambda row: (-row["name_similarity"], row["source_label"]))
        neighbors.append({"source_label": first["source_label"], "possible_neighbors": options[:5]})
    save_new(output_path, {"schema_version": 1, "purpose": "semantic form-family adjudication input",
                           "source_registry_version": summary.get("registry_version"),
                           "product_count": sum(counts.values()), "profiles": profiles,
                           "name_neighbors_for_recall_only": neighbors,
                           "boundary": "Name similarity proposes comparisons; image-grounded structure decides grouping."})


def apply(labels_path, summary_path, decisions_path, output_dir):
    labels, summary, decisions = load(labels_path), load(summary_path), load(decisions_path)
    if decisions.get("schema_version") != 1:
        raise ValueError("cluster decision schema_version must be 1")
    original_counts = summary["axes"]["form"]["canonical_counts"]
    rows = decisions.get("mappings", [])
    if not rows and decisions.get("families"):
        for family in decisions["families"]:
            for variant in family.get("variants", []):
                for source in variant.get("sources", []):
                    rows.append({"source_label": source, "family": family["family"],
                                 "variant": variant["variant"],
                                 "features": variant.get("features", []),
                                 "reason": variant.get("reason") or family.get("reason"),
                                 "confidence": variant.get("confidence", family.get("confidence", "high"))})
    owners = {}
    for row in rows:
        source = str(row.get("source_label") or "").strip()
        family = str(row.get("family") or "").strip()
        variant = str(row.get("variant") or "").strip()
        reason = str(row.get("reason") or "").strip()
        features = row.get("features", [])
        confidence = row.get("confidence")
        if not source or source in owners or not family or not variant or not reason:
            raise ValueError(f"incomplete or duplicate mapping: {source!r}")
        if confidence not in ("high", "medium", "low"):
            raise ValueError(f"invalid confidence for {source}")
        if not isinstance(features, list) or any(not isinstance(x, str) or not x.strip() for x in features):
            raise ValueError(f"invalid features for {source}")
        owners[source] = {"family": family, "variant": variant,
                          "features": list(dict.fromkeys(x.strip() for x in features)),
                          "reason": reason, "confidence": confidence}
    if set(owners) != set(original_counts):
        raise ValueError(f"mapping coverage differs: missing={sorted(set(original_counts)-set(owners))}, "
                         f"extra={sorted(set(owners)-set(original_counts))}")
    if not decisions.get("semantic_review") or not decisions["semantic_review"].get("method"):
        raise ValueError("semantic_review.method is required")

    family_counts, variant_counts = Counter(), Counter()
    family_examples = defaultdict(list)
    family_sources = defaultdict(list)
    for source, decision in owners.items():
        family_sources[decision["family"]].append(source)
    updated = []
    for source_row in labels["records"]:
        row = json.loads(json.dumps(source_row, ensure_ascii=False))
        original = row["form"].get("label")
        if original:
            decision = owners[original]
            family, variant = decision["family"], decision["variant"]
            row["form"].update({"source_label": original, "label": family,
                                "variant": variant, "features": decision["features"],
                                "cluster_confidence": decision["confidence"]})
            family_counts[family] += 1
            variant_counts[(family, variant)] += 1
            if len(family_examples[family]) < 3:
                family_examples[family].append(row["product_id"])
        updated.append(row)
    if sum(family_counts.values()) != sum(original_counts.values()):
        raise ValueError("product population changed during clustering")
    result_summary = json.loads(json.dumps(summary, ensure_ascii=False))
    axis = result_summary["axes"]["form"]
    axis["source_canonical_counts"] = dict(original_counts)
    axis["source_examples"] = axis["examples"]
    axis["canonical_counts"] = dict(family_counts)
    axis["examples"] = dict(family_examples)
    axis["variant_counts"] = [{"family": family, "variant": variant, "products": count}
                              for (family, variant), count in sorted(variant_counts.items())]
    axis["family_sources"] = {key: sorted(value) for key, value in family_sources.items()}
    result_summary["strategy"] = "visual-selection-three-axis-hierarchical-v1"
    result_summary["form_cluster"] = {"method": decisions["semantic_review"]["method"],
                                      "source_class_count": len(original_counts),
                                      "family_count": len(family_counts),
                                      "variant_count": len(variant_counts),
                                      "source_singletons": sum(count == 1 for count in original_counts.values()),
                                      "family_singletons": sum(count == 1 for count in family_counts.values()),
                                      "low_confidence_sources": [source for source, item in owners.items()
                                                                 if item["confidence"] == "low"]}
    result_summary["qa"]["form_cluster_mapping_complete"] = True
    result_summary["qa"]["form_cluster_population_preserved"] = True
    result_summary["qa"]["form_cluster_semantic_review_recorded"] = True
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True)
    save_new(target / "product_labels.json", {"schema_version": labels["schema_version"], "records": updated})
    save_new(target / "label_summary.json", result_summary)
    save_new(target / "cluster_audit.json", {"schema_version": 1, "mappings": rows,
                                             "family_sources": result_summary["axes"]["form"]["family_sources"],
                                             "counts": result_summary["form_cluster"],
                                             "semantic_review": decisions["semantic_review"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("prepare")
    first.add_argument("--labels", required=True)
    first.add_argument("--summary", required=True)
    first.add_argument("--output", required=True)
    second = sub.add_parser("apply")
    second.add_argument("--labels", required=True)
    second.add_argument("--summary", required=True)
    second.add_argument("--decisions", required=True)
    second.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.labels, args.summary, args.output)
    else:
        apply(args.labels, args.summary, args.decisions, args.output_dir)


if __name__ == "__main__":
    main()
