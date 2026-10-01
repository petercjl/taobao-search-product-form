#!/usr/bin/env python3
"""Join approved search modules into product-keyed opportunity evidence.

This script describes observed groups; it does not score or recommend entry.
Inputs are local stage artifacts. The output path must not exist.
"""

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_rows(rows, label):
    result = {}
    for row in rows:
        key = str(row.get("product_id", "")).strip()
        if not key or key in result:
            raise ValueError(f"{label}: blank or duplicate product_id: {key!r}")
        result[key] = row
    return result


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo), 2)


def number(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc
    if result < 0 or result != result or result == float("inf"):
        raise ValueError(f"invalid {label}: {value!r}")
    return result


def same_fact(left, right):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 0.011
    return left == right


def candidate_id(axis, labels):
    payload = json.dumps([axis, labels], ensure_ascii=False, separators=(",", ":"))
    return "c-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build(args):
    if not getattr(args, "prototype_labels", None):
        raise ValueError("whole-product prototype labels are required for cross-module comparison")
    paths = {"visual": args.visual_labels, "price": args.price_detail,
             "title": args.title_roots, "geography": args.geography_detail,
             "advertising": args.advertiser_detail}
    data = {name: read_json(path) for name, path in paths.items()}
    price = data["price"]
    roots = data["title"]
    geo = data["geography"]
    ads = data["advertising"]
    visual = data["visual"]

    source_hashes = {"price": price["source"]["sha256"],
                     "title": roots["source"]["sha256"],
                     "geography": geo["source"]["sha256"],
                     "advertising": ads["source"]["sha256"]}
    if len(set(source_hashes.values())) != 1:
        raise ValueError(f"cleaned-workbook source hash mismatch: {source_hashes}")

    base = unique_rows(price["products"], "price products")
    title = unique_rows(roots["products"], "title products")
    location = unique_rows(geo["natural_products"], "geography products")
    observed = unique_rows(visual["records"], "visual records")
    prototype_rows = unique_rows(read_json(args.prototype_labels), "prototype labels")
    if set(base) != set(title) or set(base) != set(location):
        raise ValueError("price, title and geography natural product IDs differ")
    if not set(observed).issubset(base):
        raise ValueError("visual IDs are not a subset of cleaned natural products")
    if set(prototype_rows) != set(observed):
        raise ValueError("prototype labels and visual records must cover the same image IDs")
    for pid, row in prototype_rows.items():
        if row["image_sha256"] != observed[pid]["image_sha256"]:
            raise ValueError(f"prototype image hash disagrees for {pid}")
        if bool(row.get("style_ids")) == bool(row.get("boundary_reason")):
            raise ValueError(f"prototype label needs style membership or boundary reason: {pid}")

    for pid, row in base.items():
        for name, item, fields in (
            ("title", title[pid], ("title", "shop_name", "price_yuan", "payment_people")),
            ("geography", location[pid], ("title", "shop_name", "price_yuan", "payment_people")),
        ):
            for field in fields:
                if not same_fact(row[field], item[field]):
                    raise ValueError(f"{name} disagrees on {field} for product {pid}")

    roots_by_id = defaultdict(set)
    for relation in roots["product_roots"]:
        pid = str(relation["product_id"])
        if pid not in base:
            raise ValueError(f"title root references unknown product {pid}")
        roots_by_id[pid].add((relation["facet"], relation["root"]))

    ads_by_id = defaultdict(list)
    ads_by_shop = defaultdict(list)
    for row in ads["ad_appearance_records"]:
        pid = str(row["product_id"])
        ads_by_id[pid].append(row)
        ads_by_shop[row["shop_name"]].append(row)
    if len(ads["ad_appearance_records"]) != ads["counts"]["ad_appearances"]:
        raise ValueError("advertising appearance count does not reconcile")
    if len(ads_by_id) != ads["counts"]["ad_products"]:
        raise ValueError("advertising unique-product count does not reconcile")

    products = []
    for pid, row in base.items():
        v = observed.get(pid)
        status = v["status"] if v else "not_observed"
        labels = {axis: v[axis].get("label") if v else None
                  for axis in ("form", "style", "audience")}
        form_variant = v["form"].get("variant") if v else None
        form_source_label = v["form"].get("source_label") if v else None
        form_features = v["form"].get("features", []) if v else []
        if status == "tagged" and not labels["form"]:
            raise ValueError(f"tagged product {pid} lacks a form")
        price_yuan = number(row["price_yuan"], "price_yuan")
        payment = number(row["payment_people"], "payment_people")
        ad_rows = ads_by_id.get(pid, [])
        shop = row["shop_name"]
        products.append({
            "product_id": pid,
            "title": row["title"],
            "image_url": title[pid].get("image_url"),
            "image_path": v.get("image_path") if v else None,
            "visual_status": status,
            "form": labels["form"], "form_variant": form_variant,
            "product_style_ids": prototype_rows.get(pid, {}).get("style_ids", []),
            "product_style_boundary": prototype_rows.get(pid, {}).get("boundary_reason"),
            "form_source_label": form_source_label, "form_features": form_features,
            "style": labels["style"],
            "task_audience": labels["audience"],
            "visible_evidence": v.get("visible_evidence") if v else None,
            "style_product_delta": v["style"].get("physical_delta") if v else None,
            "task_product_delta": v["audience"].get("physical_delta") if v else None,
            "shop_name": shop,
            "shop_type_label": title[pid].get("shop_type"),
            "price_yuan": price_yuan, "price_band": row["band"],
            "payment_people_displayed": payment,
            "natural_position": title[pid].get("natural_position"),
            "listing_address": location[pid].get("address_raw"),
            "title_roots": [{"facet": facet, "root": root}
                            for facet, root in sorted(roots_by_id[pid])],
            "ad_appearances_same_shop": sum(a["shop_name"] == shop for a in ad_rows),
            "ad_appearances_other_shop": sum(a["shop_name"] != shop for a in ad_rows),
        })

    by_id = {p["product_id"]: p for p in products}
    by_shop = defaultdict(list)
    for p in products:
        by_shop[p["shop_name"]].append(p)

    member_sets = defaultdict(set)
    definitions = {}
    for p in products:
        if p["visual_status"] != "tagged" and not p["product_style_ids"]:
            continue
        axes = [("product_style", {"product_style_id": style_id}) for style_id in p["product_style_ids"]]
        if p["visual_status"] != "tagged":
            for axis, labels in axes:
                cid = candidate_id(axis, labels)
                member_sets[cid].add(p["product_id"])
                definitions[cid] = (axis, labels)
            continue
        axes.append(("form", {"form": p["form"]}))
        if p["form_variant"]:
            axes.append(("form_variant", {"form": p["form"], "variant": p["form_variant"]}))
        if p["style"]:
            axes.append(("form_style", {"form": p["form"], "style": p["style"]}))
            if p["form_variant"]:
                axes.append(("form_variant_style", {"form": p["form"], "variant": p["form_variant"], "style": p["style"]}))
        if p["task_audience"]:
            axes.append(("form_task", {"form": p["form"], "task_audience": p["task_audience"]}))
            if p["form_variant"]:
                axes.append(("form_variant_task", {"form": p["form"], "variant": p["form_variant"], "task_audience": p["task_audience"]}))
        if p["style"] and p["task_audience"]:
            axes.append(("form_style_task", {"form": p["form"], "style": p["style"],
                                             "task_audience": p["task_audience"]}))
            if p["form_variant"]:
                axes.append(("form_variant_style_task", {"form": p["form"], "variant": p["form_variant"],
                                                           "style": p["style"], "task_audience": p["task_audience"]}))
        for axis, labels in axes:
            cid = candidate_id(axis, labels)
            member_sets[cid].add(p["product_id"])
            definitions[cid] = (axis, labels)

    candidates = []
    for cid, ids in member_sets.items():
        axis, labels = definitions[cid]
        members = [by_id[pid] for pid in ids]
        members.sort(key=lambda p: (-p["payment_people_displayed"], p["product_id"]))
        prices = [p["price_yuan"] for p in members]
        payments = [p["payment_people_displayed"] for p in members]
        shop_groups = defaultdict(list)
        for p in members:
            shop_groups[p["shop_name"]].append(p)
        shops = []
        for name, shop_members in shop_groups.items():
            full_line = by_shop[name]
            shops.append({
                "shop_name": name,
                "candidate_product_count": len(shop_members),
                "candidate_payment_people_sum_displayed": sum(p["payment_people_displayed"] for p in shop_members),
                "natural_product_count_in_export": len(full_line),
                "natural_form_counts": dict(Counter(p["form"] or "unconfirmed" for p in full_line)),
                "natural_price_band_counts": dict(Counter(str(p["price_band"]) for p in full_line)),
                "same_shop_ad_appearance_count": len(ads_by_shop.get(name, [])),
                "same_shop_ad_product_count": len({a["product_id"] for a in ads_by_shop.get(name, [])}),
                "candidate_product_ids": [p["product_id"] for p in shop_members],
            })
        shops.sort(key=lambda s: (-s["candidate_payment_people_sum_displayed"], s["shop_name"]))
        top = shops[0]
        payment_sum = sum(payments)
        root_counts = Counter((r["facet"], r["root"]) for p in members for r in p["title_roots"])
        parent_id = candidate_id("form", {"form": labels["form"]}) if axis not in ("form", "product_style") else None
        candidates.append({
            "candidate_id": cid, "axis": axis, "labels": labels,
            "parent_form_candidate_id": parent_id,
            "product_ids": sorted(ids),
            "product_count": len(members), "shop_count": len(shops),
            "displayed_payment_people": {
                "sum_across_products": payment_sum,
                "median_per_product": round(statistics.median(payments), 2),
                "p75_per_product": percentile(payments, .75),
                "p90_per_product": percentile(payments, .90),
                "highest_product_share_of_sum": round(max(payments) / payment_sum, 4) if payment_sum else None,
                "top_shop_share_of_sum": round(top["candidate_payment_people_sum_displayed"] / payment_sum, 4) if payment_sum else None,
                "sum_after_excluding_top_shop": payment_sum - top["candidate_payment_people_sum_displayed"],
            },
            "displayed_price_yuan": {"min": min(prices), "p25": percentile(prices, .25),
                                     "median": round(statistics.median(prices), 2),
                                     "p75": percentile(prices, .75), "max": max(prices)},
            "price_band_product_counts": dict(sorted(Counter(str(p["price_band"]) for p in members).items())),
            "natural_advertised_product_count_same_shop": sum(p["ad_appearances_same_shop"] > 0 for p in members),
            "ad_appearance_count_same_shop": sum(p["ad_appearances_same_shop"] for p in members),
            "ad_appearance_count_other_shop": sum(p["ad_appearances_other_shop"] for p in members),
            "title_roots_top": [{"facet": facet, "root": root, "product_count": count}
                                for (facet, root), count in root_counts.most_common(12)],
            "listing_address_top": [{"address": address, "product_count": count}
                                    for address, count in Counter(p["listing_address"] for p in members).most_common(8)],
            "leading_products": [{"product_id": p["product_id"], "shop_name": p["shop_name"],
                                  "price_yuan": p["price_yuan"], "payment_people_displayed": p["payment_people_displayed"],
                                  "image_url": p["image_url"]} for p in members[:10]],
            "leading_shops": shops[:10],
            "physical_deltas_observed": list(dict.fromkeys(
                delta for p in members for delta in (p["style_product_delta"], p["task_product_delta"]) if delta))[:12],
        })
    candidate_axis_order = ("product_style", "form", "form_variant", "form_style", "form_task", "form_style_task",
                            "form_variant_style", "form_variant_task", "form_variant_style_task")
    candidates.sort(key=lambda c: candidate_axis_order.index(c["axis"]) * 100000 - c["product_count"])

    output = {
        "schema_version": 1,
        "purpose": "descriptive evidence for user-reviewed opportunity cards; not an entry score",
        "sources": {**{name: {"sha256": digest(path), "file_name": Path(path).name}
                    for name, path in paths.items()},
                    "prototype_labels": {"sha256": digest(args.prototype_labels),
                                         "file_name": Path(args.prototype_labels).name}},
        "cleaned_workbook_sha256": next(iter(source_hashes.values())),
        "population": {
            "natural_products": len(products),
            "visual_observed": len(observed),
            "visual_tagged": sum(p["visual_status"] == "tagged" for p in products),
            "visual_uncertain": sum(p["visual_status"] == "uncertain" for p in products),
            "visual_not_observed": sum(p["visual_status"] == "not_observed" for p in products),
            "visual_product_style_classified": sum(bool(p["product_style_ids"]) for p in products),
            "advertising_appearances": len(ads["ad_appearance_records"]),
            "advertising_unique_products": len(ads_by_id),
        },
        "grain_notes": [
            "Each natural product ID appears once; candidate families overlap and must not be summed together.",
            "Displayed payment people have an unknown time window and are not units, GMV, conversion or unique buyers across products.",
            "Ad appearances are sampled positions, not spend or impressions; cross-shop ID matches are separate.",
            "Listing address is not a verified factory or dispatch warehouse.",
            "Task-audience labels indicate image-grounded use hypotheses, not actual buyer demographics.",
        ],
        "products": products,
        "candidates": candidates,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(path.resolve()), "products": len(products),
                      "candidates": len(candidates), "tagged": output["population"]["visual_tagged"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-labels", required=True)
    parser.add_argument("--prototype-labels", required=True,
                        help="compiled product_style_labels.json for whole-product prototypes")
    parser.add_argument("--price-detail", required=True)
    parser.add_argument("--title-roots", required=True)
    parser.add_argument("--geography-detail", required=True)
    parser.add_argument("--advertiser-detail", required=True)
    parser.add_argument("--output", required=True)
    build(parser.parse_args())
