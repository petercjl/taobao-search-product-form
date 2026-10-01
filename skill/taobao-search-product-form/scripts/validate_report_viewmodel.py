#!/usr/bin/env python3
"""Audit the comprehensive report ViewModel against its module sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_report_viewmodel import check_report_bindings, md_blocks, read_json, read_product_links, source_path


MODULE_VIEWS = {
    "advertising": "advertising",
    "title": "title_roots",
    "geography": "geography",
    "price": "price",
    "visual": "visual",
}


def validate(manifest_path: Path, viewmodel_path: Path) -> dict:
    manifest = read_json(manifest_path)
    loaded, srcs = {}, {}
    for key in ("visual", "decision"):
        loaded[key], srcs[key] = {}, {}
        for role, value in manifest["modules"][key].items():
            path = source_path(manifest_path, value)
            loaded[key][role] = path.read_text(encoding="utf-8") if path.suffix == ".md" else read_json(path)
            srcs[key][role] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    check_report_bindings(loaded, srcs)
    report = read_json(viewmodel_path)
    expected_binding = {
        "prototype_labels_sha256": srcs["visual"]["labels"]["sha256"],
        "prototype_summary_sha256": srcs["visual"]["prototypes"]["sha256"],
        "comparison_evidence_sha256": srcs["decision"]["evidence"]["sha256"],
        "opportunity_cards_sha256": srcs["decision"]["cards"]["sha256"],
    }
    if report.get("meta", {}).get("artifact_binding") != expected_binding:
        raise ValueError("ViewModel is not bound to current classification, comparison and cards")
    views = {view["id"]: view for view in report["views"]}
    expected_views = {"overview", "sample", "advertising", "title_roots", "geography", "price",
                      "visual", "candidates", "opportunities", "evidence", "method"}
    if not expected_views <= views.keys():
        raise ValueError(f"missing views: {sorted(expected_views - views.keys())}")
    retained_sections = {}
    for module, view_id in MODULE_VIEWS.items():
        item = manifest["modules"][module]
        if "interpretation" not in item:
            continue
        source = source_path(manifest_path, item["interpretation"])
        interpretation = loaded[module]["interpretation"] if module == "visual" else source.read_text(encoding="utf-8")
        expected = md_blocks(interpretation)
        actual = views[view_id]["blocks"]
        missing = [block for block in expected if block not in actual]
        if missing:
            raise ValueError(f"{module}: {len(missing)} reviewed interpretation block(s) missing")
        retained_sections[module] = len(expected)
    decision = manifest["modules"]["decision"]
    evidence = loaded["decision"]["evidence"]
    cards = loaded["decision"]["cards"]["cards"]
    candidate_table = next(b for b in views["candidates"]["blocks"] if b.get("title") == "全部候选组合")
    product_table = next(b for b in views["evidence"]["blocks"] if b.get("title") == "全部自然位商品")
    tabs = next(b for b in views["opportunities"]["blocks"] if b["type"] == "tabs")["tabs"]
    if len(candidate_table["rows"]) != len(evidence["candidates"]):
        raise ValueError("candidate group coverage mismatch")
    if len(product_table["rows"]) != len(evidence["products"]):
        raise ValueError("natural product coverage mismatch")
    source_links = read_product_links(source_path(manifest_path, manifest["cleaned_workbook"]))
    visual_summary = read_json(source_path(manifest_path, manifest["modules"]["visual"]["summary"]))
    prototypes = loaded["visual"]["prototypes"]
    visual_tabs = next(b for b in views["visual"]["blocks"] if b.get("type") == "tabs")["tabs"]
    expected_family_names = {item["name"] for item in prototypes}
    actual_tab_names = {tab["label"] for tab in visual_tabs}
    if not expected_family_names <= actual_tab_names:
        raise ValueError("visual gallery missing product-style menus")
    gallery_ids = []
    gallery_by_label = {}
    for tab in visual_tabs:
        gallery = next(b for b in tab["blocks"] if b.get("type") == "products")
        if gallery.get("page_size") != 50:
            raise ValueError("visual gallery must show 50 items per page")
        keys = {option["key"] for option in gallery.get("sort_options", [])}
        if not {"price", "payment", "score"} <= keys:
            raise ValueError("visual gallery missing required sort dimensions")
        for item in gallery["items"]:
            if not str(item.get("image_url", "")).startswith("https://"):
                raise ValueError("visual gallery product missing HTTPS image")
            pid = item.get("copy_value")
            if item.get("item_url") != source_links.get(pid):
                raise ValueError(f"visual gallery product link mismatch for {pid}")
            gallery_ids.append(pid)
        gallery_by_label[tab["label"]] = {item["copy_value"] for item in gallery["items"]}
    for prototype in prototypes:
        if gallery_by_label.get(prototype["name"]) != set(map(str, prototype["product_ids"])):
            raise ValueError(f"visual gallery prototype membership mismatch: {prototype['style_id']}")
    expected_ids = {product["product_id"] for product in evidence["products"]}
    if set(gallery_ids) != expected_ids:
        raise ValueError("visual gallery product coverage mismatch")
    card_tabs = [tab for tab in tabs if tab["id"] != "narrative"]
    if len(card_tabs) != len(cards):
        raise ValueError("opportunity card coverage mismatch")
    if {tab["id"] for tab in card_tabs} != {card["candidate_id"] for card in cards}:
        raise ValueError("opportunity card IDs mismatch")
    if "interpretation" in decision:
        source = source_path(manifest_path, decision["interpretation"])
        expected = md_blocks(loaded["decision"]["interpretation"])
        narrative = next((tab for tab in tabs if tab["id"] == "narrative"), None)
        if not narrative or narrative["blocks"] != expected:
            raise ValueError("reviewed opportunity interpretation missing")
        retained_sections["decision"] = len(expected)
    numbered_points = 0
    for view in views.values():
        for block in iter_blocks(view.get("blocks", [])):
            if block.get("type") == "text":
                passages = [block.get("text", ""), *block.get("paragraphs", [])]
                if any(len(passage) > 120 for passage in passages):
                    raise ValueError(f"{view['id']}: oversized unstructured prose block")
            if block.get("type") == "actions":
                numbered_points += len(block.get("items", []))
                for item in block.get("items", []):
                    if not item.get("title") or not item.get("text"):
                        raise ValueError(f"{view['id']}: incomplete numbered judgment")
                    if item.get("source_chunk") and item["text"] not in item["source_chunk"]:
                        raise ValueError(f"{view['id']}: numbered point lost its source explanation")
    if numbered_points == 0:
        raise ValueError("no numbered interpretation points")
    return {"views": len(views), "reviewed_interpretation_blocks": retained_sections,
            "natural_products": len(product_table["rows"]), "candidate_groups": len(candidate_table["rows"]),
            "opportunity_cards": len(card_tabs), "visual_gallery_products": len(gallery_ids),
            "visual_form_menus": len(visual_tabs), "numbered_points": numbered_points}


def iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        yield from iter_blocks(block.get("blocks", []))
        for tab in block.get("tabs", []):
            yield from iter_blocks(tab.get("blocks", []))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--viewmodel", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest, args.viewmodel), ensure_ascii=False))


if __name__ == "__main__":
    main()
