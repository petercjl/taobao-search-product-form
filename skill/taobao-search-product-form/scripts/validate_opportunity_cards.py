#!/usr/bin/env python3
"""Validate opportunity-card structure and links to joined product evidence.

This is a mechanical check. It cannot decide whether natural-language claims are
commercially justified; the Agent must audit figures and alternative explanations.
"""

import argparse
import hashlib
import json
from pathlib import Path


def validate(cards, evidence, evidence_sha256):
    if cards.get("schema_version") != 2 or not isinstance(cards.get("cards"), list):
        raise ValueError("cards must have schema_version 2 and a cards array")
    if cards.get("source_evidence_sha256") != evidence_sha256:
        raise ValueError("opportunity cards do not match the current comparison evidence hash")
    if not evidence.get("sources", {}).get("prototype_labels", {}).get("sha256"):
        raise ValueError("comparison evidence lacks whole-product prototype labels")
    candidates = {c["candidate_id"]: c for c in evidence["candidates"]}
    if not any(c.get("axis") == "product_style" for c in candidates.values()):
        raise ValueError("comparison evidence lacks product-style candidates")
    products = {p["product_id"]: p for p in evidence["products"]}
    seen = set()
    orders = set()
    for card in cards["cards"]:
        cid = card.get("candidate_id")
        if cid not in candidates or cid in seen:
            raise ValueError(f"unknown or repeated candidate_id: {cid}")
        seen.add(cid)
        candidate = candidates[cid]
        if candidate.get("axis") != "product_style":
            raise ValueError(f"{cid}: opportunity card must use a whole-product style prototype")
        for field in ("definition", "parent_comparison", "scope", "interpretation"):
            if not isinstance(card.get(field), str) or not card[field].strip():
                raise ValueError(f"{cid}: missing {field}")
        if "score" in card or "entry_decision" in card:
            raise ValueError(f"{cid}: card cannot contain a composite score or entry verdict")
        for field in ("observations", "supporting_evidence", "counterevidence", "unknowns", "next_checks"):
            if not isinstance(card.get(field), list) or not card[field]:
                raise ValueError(f"{cid}: missing {field}")
        for item in card["observations"] + card["supporting_evidence"] + card["counterevidence"]:
            if not isinstance(item.get("claim"), str) or not item["claim"].strip():
                raise ValueError(f"{cid}: evidence item lacks claim")
            if not isinstance(item.get("refs"), list) or not item["refs"]:
                raise ValueError(f"{cid}: evidence item lacks references")
            for ref in item["refs"]:
                if ref.isdigit():
                    if ref not in products or ref not in candidate["product_ids"]:
                        raise ValueError(f"{cid}: product reference is not a member: {ref}")
                    continue
                target_id, separator, field_path = ref.partition(".")
                if not separator or target_id not in candidates:
                    raise ValueError(f"{cid}: invalid candidate reference: {ref}")
                target = candidates[target_id]
                for key in field_path.split("."):
                    if not isinstance(target, dict) or key not in target:
                        raise ValueError(f"{cid}: missing evidence field: {ref}")
                    target = target[key]
        for check in card["next_checks"]:
            if not check.get("question") or not check.get("changes_assessment_if"):
                raise ValueError(f"{cid}: next check lacks a discriminating result")
        research_order = card.get("research_order")
        if research_order is not None:
            position = research_order.get("position")
            if not isinstance(position, int) or position < 1 or position in orders or not research_order.get("reason"):
                raise ValueError(f"{cid}: invalid or duplicate research order")
            orders.add(position)
    if not cards["cards"]:
        raise ValueError("no opportunity cards")
    return {"ok": True, "cards": len(seen), "linked_candidates": len(candidates),
            "linked_products": len(products)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    cards = json.loads(Path(args.cards).read_text(encoding="utf-8"))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    evidence_sha256 = hashlib.sha256(Path(args.evidence).read_bytes()).hexdigest()
    print(json.dumps(validate(cards, evidence, evidence_sha256), ensure_ascii=False))
