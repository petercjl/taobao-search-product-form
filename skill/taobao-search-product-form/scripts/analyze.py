#!/usr/bin/env python3
"""Reconcile visual product labels with organic placement and advertiser evidence."""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def median(values):
    usable = [float(value) for value in values if value is not None]
    return round(statistics.median(usable), 2) if usable else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    labels_path = Path(args.labels).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists():
        parser.error("output already exists; select a new path")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger = json.loads(labels_path.read_text(encoding="utf-8"))
    products = {p["product_id"]: p for p in manifest["products"]}
    selected = set(manifest["selected_organic_ids"]) | set(manifest["selected_ad_only_ids"])
    labels = {}
    for item in ledger["labels"]:
        pid = str(item["product_id"])
        if pid in labels or pid not in selected:
            raise ValueError(f"duplicate or out-of-scope visual label: {pid}")
        eligibility = item.get("eligibility")
        if eligibility not in ("target", "non_target", "uncertain"):
            raise ValueError(f"invalid eligibility for {pid}")
        form = item.get("form")
        if eligibility == "target" and (not form or not item.get("visible_evidence")):
            raise ValueError(f"target needs form and visible evidence: {pid}")
        if eligibility != "target" and form:
            raise ValueError(f"non-target/uncertain must not have form: {pid}")
        fetched_path = manifest["fetches"].get(pid, {}).get("path")
        if fetched_path is None or item.get("image_path") != fetched_path:
            raise ValueError(f"label lacks exact fetched-image evidence: {pid}")
        labels[pid] = item
    organic_ids = set(manifest["selected_organic_ids"])
    ad_only_ids = set(manifest["selected_ad_only_ids"])
    organic_labels = {pid: label for pid, label in labels.items() if pid in organic_ids}
    ad_labels = {pid: label for pid, label in labels.items() if pid in ad_only_ids}
    counts = Counter(label["eligibility"] for label in organic_labels.values())
    ad_counts = Counter(label["eligibility"] for label in ad_labels.values())
    by_form = defaultdict(list)
    for pid, label in organic_labels.items():
        if label["eligibility"] == "target":
            by_form[label["form"]].append(products[pid])
    forms = []
    for form, items in by_form.items():
        items.sort(key=lambda p: p["organic_rank"])
        forms.append({
            "form": form,
            "organic_unique_products": len(items),
            "shops": len({p["shop"] for p in items if p["shop"]}),
            "top_100_organic": sum(p["organic_rank"] <= 100 for p in items),
            "top_300_organic": sum(p["organic_rank"] <= 300 for p in items),
            "median_price": median(p["price"] for p in items),
            "median_payment_count": median(p["payment_count"] for p in items),
            "advertised_also": sum(bool(p["ad_positions"]) for p in items),
            "representative_ids": [p["product_id"] for p in items[:8]],
        })
    forms.sort(key=lambda f: (-f["top_100_organic"], -f["organic_unique_products"], f["form"]))
    advertised = [p for p in products.values() if p["ad_positions"]]
    overlap = [p for p in advertised if p["natural_positions"]]
    analysis = {
        "schema_version": 1,
        "source": manifest["source"],
        "search_term": manifest["search_term"],
        "scope": manifest["scope"],
        "source_counts": {
            "display_rows": len(manifest["source_rows"]),
            "unique_products": len(products),
            "organic_unique_products": sum(bool(p["natural_positions"]) for p in products.values()),
            "advertised_unique_products": len(advertised),
            "advertised_distinct_shops": len({p["shop"] for p in advertised if p["shop"]}),
            "advertised_with_natural": len(overlap),
            "ad_only_unique_products": len(advertised) - len(overlap),
            "ad_only_distinct_shops": len({p["shop"] for p in advertised if not p["natural_positions"] and p["shop"]}),
            "ad_display_rows": sum(row["placement"] == "广告位" for row in manifest["source_rows"]),
        },
        "image_fetch": {
            "requested": len(manifest["fetches"]),
            "ok": sum(result["status"] == "ok" for result in manifest["fetches"].values()),
            "failures": {pid: result["status"] for pid, result in manifest["fetches"].items() if result["status"] != "ok"},
        },
        "visual_coverage": {
            "organic_selected": len(organic_ids),
            "organic_labeled": len(organic_labels),
            "organic_target": counts["target"],
            "organic_non_target": counts["non_target"],
            "organic_uncertain": counts["uncertain"],
            "ad_only_selected": len(ad_only_ids),
            "ad_only_labeled": len(ad_labels),
            "ad_only_target": ad_counts["target"],
            "ad_only_non_target": ad_counts["non_target"],
            "ad_only_uncertain": ad_counts["uncertain"],
        },
        "forms": forms,
        "unlabeled_organic_ids": sorted(organic_ids - set(organic_labels)),
        "unlabeled_ad_only_ids": sorted(ad_only_ids - set(ad_labels)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output_path), "source_counts": analysis["source_counts"], "visual_coverage": analysis["visual_coverage"], "form_count": len(forms)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
