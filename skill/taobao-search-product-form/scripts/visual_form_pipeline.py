#!/usr/bin/env python3
"""Plan one-pass visual jobs and reduce open visual observations.

Planning groups images for review; it never infers a product form. Reduction
uses an explicit, versioned registry, so labels can change without rereading.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def dhash(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L").resize((9, 8))
        pixels = list(image.tobytes())
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def plan(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = read_json(manifest_path)
    source_root = manifest_path.parent
    if args.population != "natural":
        raise ValueError("only the natural-position form population is currently implemented")
    ids = manifest["selected_organic_ids"]
    if args.limit:
        ids = ids[:args.limit]
    lookup = {str(p["product_id"]): p for p in manifest["products"]}
    items = []
    for pid in ids:
        fetched = manifest["fetches"].get(pid, {})
        if fetched.get("status") != "ok":
            items.append({"product_id": pid, "status": "image_unavailable", "image_path": None,
                          "unavailable_reason": fetched.get("status") or "missing_fetch_record"})
            continue
        path = (source_root / fetched["path"]).resolve()
        if not path.is_file() or not path.is_relative_to(source_root):
            raise ValueError(f"missing or escaping image path for product {pid}")
        items.append({"product_id": pid, "status": "ready", "image_path": str(path),
                      "source_image_url": lookup[pid].get("image_url"),
                      "image_sha256": digest(path), "image_dhash": f"{dhash(path):016x}",
                      "source_rank": lookup[pid]["organic_rank"]})
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate selected natural-position product ID")
    out = Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    ready = [item for item in items if item["status"] == "ready"]
    # dHash is a cheap grouping hint only. It is never a classification label.
    ready.sort(key=lambda item: (item["image_dhash"], item["product_id"]))
    batches = []
    for start in range(0, len(ready), args.batch_size):
        members = ready[start:start + args.batch_size]
        batch_id = f"B{len(batches) + 1:03d}"
        for item in members:
            item["batch_id"] = batch_id
        batches.append({"batch_id": batch_id, "product_ids": [item["product_id"] for item in members]})
        columns, cell_w, cell_h = 3, 350, 385
        rows = (len(members) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "white")
        draw = ImageDraw.Draw(sheet)
        for n, item in enumerate(members):
            with Image.open(item["image_path"]) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((330, 345))
                x, y = (n % columns) * cell_w, (n // columns) * cell_h
                sheet.paste(image, (x + (cell_w - image.width) // 2, y + 4))
            draw.text((x + 8, y + 354), f'{item["product_id"]}  N{item["source_rank"]}', fill="black")
        sheet_name = f"{batch_id}.jpg"
        sheet.save(out / sheet_name, "JPEG", quality=90)
        batches[-1]["contact_sheet"] = str(out / sheet_name)
    plan_doc = {"schema_version": 1, "strategy": "visual-form-open-v1",
                "semantic_inspection_unit": "original_product_image",
                "contact_sheet_role": "orientation_and_coverage_audit",
                "source_manifest": str(manifest_path), "source_manifest_sha256": digest(manifest_path),
                "population": "natural", "scope": {"selected": len(ids), "ready": len(ready),
                "image_unavailable": len(ids) - len(ready), "manifest_natural_total": manifest["scope"]["organic_total"]},
                "batch_size": args.batch_size, "items": items, "batches": batches}
    write_json(out / "visual_batch_plan.json", plan_doc)
    print(json.dumps({"plan": str(out / "visual_batch_plan.json"), "selected": len(ids),
                      "ready": len(ready), "batches": len(batches)}, ensure_ascii=False))


def bind(args):
    plan_doc = read_json(args.plan)
    draft = read_json(args.draft)
    ready = {item["product_id"]: item for item in plan_doc["items"] if item["status"] == "ready"}
    observations = draft["observations"]
    ids = [str(row["product_id"]) for row in observations]
    if len(ids) != len(set(ids)) or set(ids) != set(ready):
        raise ValueError("draft must cover each ready product exactly once")
    bound = []
    for row in observations:
        item = ready[str(row["product_id"])]
        bound.append({**row, "batch_id": item["batch_id"], "image_sha256": item["image_sha256"]})
    output = Path(args.output).resolve()
    write_json(output, {"schema_version": 1, "plan_sha256": digest(Path(args.plan)),
                        "observations": bound})
    print(json.dumps({"observations": str(output), "count": len(bound)}, ensure_ascii=False))


def reduce(args):
    plan_doc = read_json(args.plan)
    raw = read_json(args.observations)
    registry = read_json(args.registry)
    if raw.get("schema_version") != 1 or registry.get("schema_version") != 1:
        raise ValueError("unsupported observations or registry schema")
    if raw.get("plan_sha256") != digest(Path(args.plan)):
        raise ValueError("observations were bound to a different plan")
    expected = {item["product_id"]: item for item in plan_doc["items"] if item["status"] == "ready"}
    records = raw["observations"]
    ids = [str(record["product_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("a product has more than one semantic observation")
    if set(ids) != set(expected):
        raise ValueError(f"observation coverage mismatch: missing={sorted(set(expected)-set(ids))}, extra={sorted(set(ids)-set(expected))}")
    forms = registry.get("primary_forms", {})
    alias_owner = {}
    for canonical, entry in forms.items():
        for alias in [canonical, *entry.get("aliases", [])]:
            key = alias.strip().casefold()
            if key in alias_owner and alias_owner[key] != canonical:
                raise ValueError(f"alias collision: {alias}")
            alias_owner[key] = canonical
    result = []
    unresolved = Counter()
    uncertain_candidates = Counter()
    candidates = Counter()
    batches = defaultdict(Counter)
    for record in records:
        pid = str(record["product_id"])
        item = expected[pid]
        if record.get("image_sha256") != item["image_sha256"] or record.get("batch_id") != item["batch_id"]:
            raise ValueError(f"image/batch provenance mismatch: {pid}")
        status = record.get("status")
        if status not in {"tagged", "uncertain"}:
            raise ValueError(f"invalid observation status: {pid}")
        evidence = str(record.get("visible_evidence", "")).strip()
        if not evidence:
            raise ValueError(f"missing visible evidence: {pid}")
        candidate = str(record.get("primary_form_candidate", "")).strip()
        if status == "tagged" and not candidate:
            raise ValueError(f"missing form candidate: {pid}")
        facets = record.get("facets", {})
        if not isinstance(facets, dict):
            raise ValueError(f"facets must be an object: {pid}")
        canonical = alias_owner.get(candidate.casefold()) if candidate else None
        if candidate:
            candidates[candidate] += 1
        if status == "tagged" and canonical is None:
            unresolved[candidate] += 1
        if status == "uncertain" and candidate and canonical is None:
            uncertain_candidates[candidate] += 1
        if canonical:
            batches[item["batch_id"]][canonical] += 1
        result.append({"product_id": pid, "batch_id": item["batch_id"],
                       "image_sha256": item["image_sha256"], "status": status,
                       "primary_form_candidate": candidate or None,
                       "primary_form": canonical, "visible_evidence": evidence,
                       "facets": facets})
    out = Path(args.output_dir).resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    counts = Counter(row["primary_form"] for row in result if row["primary_form"])
    report = {"schema_version": 1, "strategy": "visual-form-open-v1",
              "plan_sha256": digest(Path(args.plan)), "observations_sha256": digest(Path(args.observations)),
              "registry_sha256": digest(Path(args.registry)), "registry_version": registry.get("version"),
              "scope": plan_doc["scope"], "observed": len(result),
              "candidate_labels": dict(candidates), "candidate_label_count": len(candidates),
              "canonical_forms": dict(counts), "canonical_form_count": len(counts),
              "representative_product_ids": {form: [row["product_id"] for row in result
                                                       if row["primary_form"] == form][:3]
                                             for form in counts},
              "singleton_forms": [form for form, count in counts.items() if count == 1],
              "unresolved_candidates": dict(unresolved),
              "uncertain_candidates": dict(uncertain_candidates),
              "uncertain_count": sum(row["status"] == "uncertain" for row in result),
              "batch_form_counts": {key: dict(value) for key, value in batches.items()},
              "qa": {"one_record_per_ready_product": True, "image_hash_and_batch_match": True,
                     "all_labels_resolved": not unresolved}}
    write_json(out / "visual_form_assignments.json", {"schema_version": 1, "records": result})
    write_json(out / "visual_form_summary.json", report)
    print(json.dumps({"output_dir": str(out), "observed": len(result),
                      "candidate_labels": len(candidates), "canonical_forms": len(counts),
                      "unresolved": dict(unresolved)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan")
    planning.add_argument("--manifest", required=True)
    planning.add_argument("--output-dir", required=True)
    planning.add_argument("--population", default="natural")
    planning.add_argument("--limit", type=int)
    planning.add_argument("--batch-size", type=int, default=10)
    binding = commands.add_parser("bind")
    binding.add_argument("--plan", required=True)
    binding.add_argument("--draft", required=True)
    binding.add_argument("--output", required=True)
    reducing = commands.add_parser("reduce")
    reducing.add_argument("--plan", required=True)
    reducing.add_argument("--observations", required=True)
    reducing.add_argument("--registry", required=True)
    reducing.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        if args.batch_size < 1 or args.limit is not None and args.limit < 1:
            parser.error("batch size and limit must be positive")
        plan(args)
    elif args.command == "bind":
        bind(args)
    else:
        reduce(args)


if __name__ == "__main__":
    main()
