#!/usr/bin/env python3
"""Analyze listing-location evidence from a cleaned Taobao search workbook.

The source's 地址 is an observed listing field, not verified warehouse or factory location.
Creates a new directory with geography_detail.json and geography_summary.json.
Requires pandas and an XLSX reader. A title-root JSON is optional.
"""

import argparse
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


NATURAL_REQUIRED = {"商品ID", "商品名称", "店铺名称", "地址", "现价", "付款人数", "占位类型"}
AD_REQUIRED = {"商品ID", "店铺名称", "地址", "占位类型"}
MUNICIPALITIES = {"北京", "天津", "上海", "重庆"}
EXCLUDED_ROOT_FACETS = {"unclassified", "marketing", "size_claim"}


def text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value):
    value = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(value) else float(value)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def location(value):
    raw = " ".join(unicodedata.normalize("NFKC", text(value)).split())
    if not raw:
        return {"address": None, "province": None, "city": None, "level": "unknown"}
    parts = raw.split(" ")
    if len(parts) == 1:
        return {"address": raw, "province": raw, "city": raw if raw in MUNICIPALITIES else None,
                "level": "municipality" if raw in MUNICIPALITIES else "province_only"}
    if len(parts) == 2:
        return {"address": raw, "province": parts[0], "city": parts[1], "level": "province_city"}
    return {"address": raw, "province": None, "city": None, "level": "unparsed"}


def median(values):
    series = pd.Series([value for value in values if value is not None], dtype="float64")
    return None if series.empty else round(float(series.median()), 4)


def quantile(values, q):
    series = pd.Series([value for value in values if value is not None], dtype="float64")
    return None if series.empty else round(float(series.quantile(q)), 4)


def validate_frame(frame, required, placement):
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{placement} sheet missing columns: {sorted(missing)}")
    if not frame["占位类型"].map(text).eq(placement).all():
        raise ValueError(f"{placement} sheet contains another placement type")
    if frame["商品ID"].map(text).eq("").any():
        raise ValueError(f"{placement} sheet has blank product IDs")
    if frame["店铺名称"].map(text).eq("").any():
        raise ValueError(f"{placement} sheet has blank shop names")


def band(price, cutoffs):
    if price is None or any(value is None for value in cutoffs):
        return "unknown"
    for index, cutoff in enumerate(cutoffs):
        if price <= cutoff:
            return f"Q{index + 1}"
    return "Q4"


def product_summary(rows, threshold, cutoffs):
    shops = Counter(row["shop_name"] for row in rows)
    prices = [row["price_yuan"] for row in rows]
    payments = [row["payment_people"] for row in rows]
    high = sum(value is not None and threshold is not None and value >= threshold for value in payments)
    count = len(rows)
    return {
        "product_count": count,
        "shop_count": len(shops),
        "price_p25": quantile(prices, 0.25), "price_median": median(prices), "price_p75": quantile(prices, 0.75),
        "payment_people_median": median(payments),
        "high_payment_product_count": high,
        "high_payment_product_share": round(high / count, 6) if count else None,
        "top_shop_product_share": round(max(shops.values()) / count, 6) if count else None,
        "shop_product_hhi": round(sum((n / count) ** 2 for n in shops.values()), 6) if count else None,
        "price_quartile_band_counts": dict(sorted(Counter(band(value, cutoffs) for value in prices).items())),
        "top_shops": [{"shop_name": name, "product_count": n} for name, n in sorted(shops.items(), key=lambda pair: (-pair[1], pair[0]))[:5]],
    }


def records_from_frame(frame, natural):
    result = []
    for _, source in frame.iterrows():
        result.append({
            "product_id": text(source["商品ID"]),
            "title": text(source.get("商品名称")) if natural else None,
            "shop_name": text(source["店铺名称"]),
            "shop_type": text(source.get("店铺类型")) or None,
            "address_raw": text(source["地址"]) or None,
            **location(source["地址"]),
            "price_yuan": number(source.get("现价")) if natural else None,
            "payment_people": number(source.get("付款人数")) if natural else None,
            "source_position": number(source.get("序号")),
        })
    return result


def load_title_roots(path, source_hash, products):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("source", {}).get("sha256") != source_hash or document.get("source", {}).get("sheet") != "自然位":
        raise ValueError("title-root source hash or sheet does not match cleaned workbook")
    by_id = {row["product_id"]: row for row in products}
    source_products = document.get("products")
    if not isinstance(source_products, list) or len(source_products) != len(products):
        raise ValueError("title-root product population differs from natural sheet")
    if {row.get("product_id") for row in source_products} != set(by_id):
        raise ValueError("title-root product IDs differ from natural sheet")
    for row in source_products:
        current = by_id.get(row.get("product_id"))
        if current is None or row.get("title") != current["title"]:
            raise ValueError("title-root product identity or title differs from natural sheet")
    relations = document.get("product_roots")
    if not isinstance(relations, list):
        raise ValueError("title-root relations missing")
    seen = set()
    selected = []
    for row in relations:
        key = (row.get("product_id"), row.get("facet"), row.get("root"))
        if key[0] not in by_id or not all(key) or key in seen:
            raise ValueError("title-root relation identity invalid or duplicated")
        seen.add(key)
        if key[1] not in EXCLUDED_ROOT_FACETS:
            selected.append({"product_id": key[0], "facet": key[1], "root": key[2]})
    return selected


def analyze(natural_frame, ad_frame, root_relations=None):
    validate_frame(natural_frame, NATURAL_REQUIRED, "自然位")
    validate_frame(ad_frame, AD_REQUIRED, "广告位")
    products = records_from_frame(natural_frame, True)
    ads = records_from_frame(ad_frame, False)
    ids = [row["product_id"] for row in products]
    if len(ids) != len(set(ids)):
        raise ValueError("natural-position product IDs must be unique")
    if not products:
        raise ValueError("natural-position sheet is empty")
    by_id = {row["product_id"]: row for row in products}
    threshold = quantile([row["payment_people"] for row in products], 0.9)
    cutoffs = [quantile([row["price_yuan"] for row in products], q) for q in (0.25, 0.5, 0.75)]

    city_groups = defaultdict(list)
    province_groups = defaultdict(list)
    for row in products:
        if row["address"] is not None:
            city_groups[row["address"]].append(row)
        if row["province"] is not None:
            province_groups[row["province"]].append(row)
    shop_locations = defaultdict(set)
    for row in products:
        shop_locations[row["shop_name"]].add(row["address"])
    shop_region_pairs = sorted({(row["shop_name"], row["address"]) for row in products}, key=lambda pair: (pair[0], pair[1] or ""))

    def region_rows(groups, level):
        items = []
        for name, rows in groups.items():
            item = {"level": level, "region": name, **product_summary(rows, threshold, cutoffs)}
            item["product_share_of_all_natural"] = round(len(rows) / len(products), 6)
            items.append(item)
        return sorted(items, key=lambda item: (-item["product_count"], item["region"]))

    ad_groups = defaultdict(list)
    for row in ads:
        if row["address"] is not None:
            ad_groups[row["address"]].append(row)
    ad_regions = []
    for name, rows in ad_groups.items():
        matched = {row["product_id"] for row in rows if row["product_id"] in by_id}
        ad_regions.append({
            "region": name,
            "appearance_count": len(rows),
            "unique_ad_product_count": len({row["product_id"] for row in rows}),
            "unique_ad_shop_count": len({row["shop_name"] for row in rows}),
            "product_ids_also_natural_count": len(matched),
            "product_ids_with_different_natural_address_count": sum(by_id[pid]["address"] != name for pid in matched),
        })
    ad_regions.sort(key=lambda item: (-item["appearance_count"], item["region"]))

    root_regions = []
    root_totals = []
    if root_relations is not None:
        root_groups = defaultdict(list)
        root_city_groups = defaultdict(list)
        root_province_groups = defaultdict(list)
        for relation in root_relations:
            row = by_id[relation["product_id"]]
            key = (relation["facet"], relation["root"])
            root_groups[key].append(row)
            if row["address"] is not None:
                root_city_groups[("city", row["address"], *key)].append(row)
            if row["province"] is not None:
                root_province_groups[("province", row["province"], *key)].append(row)
        for (facet, root), rows in root_groups.items():
            root_totals.append({"facet": facet, "root": root, **product_summary(rows, threshold, cutoffs)})
        for groups, populations in ((root_city_groups, city_groups), (root_province_groups, province_groups)):
            for (level, region, facet, root), rows in groups.items():
                region_n = len(populations[region])
                root_n = len(root_groups[(facet, root)])
                item = {
                    "level": level, "region": region, "facet": facet, "root": root,
                    "region_product_count": region_n, "root_product_count_all_natural": root_n,
                    "root_coverage_within_region": round(len(rows) / region_n, 6),
                    "region_share_within_root": round(len(rows) / root_n, 6),
                    "location_quotient": round((len(rows) / region_n) / (root_n / len(products)), 4),
                    **product_summary(rows, threshold, cutoffs),
                }
                item["interpretation_sample_ok"] = len(rows) >= 10 and item["shop_count"] >= 3
                root_regions.append(item)
        root_totals.sort(key=lambda item: (-item["product_count"], item["facet"], item["root"]))
        root_regions.sort(key=lambda item: (item["level"], -item["product_count"], item["region"], item["facet"], item["root"]))

    quality = {
        "natural_product_count": len(products),
        "natural_unique_product_id_count": len(by_id),
        "natural_shop_count": len(shop_locations),
        "natural_shop_address_pair_count": len(shop_region_pairs),
        "multi_address_shop_count": sum(len(addresses) > 1 for addresses in shop_locations.values()),
        "natural_unknown_address_count": sum(row["address"] is None for row in products),
        "natural_unparsed_address_count": sum(row["level"] == "unparsed" for row in products),
        "natural_missing_price_count": sum(row["price_yuan"] is None for row in products),
        "natural_missing_payment_count": sum(row["payment_people"] is None for row in products),
        "ad_appearance_count": len(ads),
        "ad_unique_product_id_count": len({row["product_id"] for row in ads}),
        "ad_unknown_address_count": sum(row["address"] is None for row in ads),
        "ad_product_ids_also_natural_count": len({row["product_id"] for row in ads if row["product_id"] in by_id}),
        "title_root_relation_count_used": len(root_relations) if root_relations is not None else None,
        "payment_p90_threshold": threshold,
        "natural_products_at_or_above_payment_p90": sum(row["payment_people"] is not None and threshold is not None and row["payment_people"] >= threshold for row in products),
        "price_quartile_cutoffs_yuan": cutoffs,
    }
    return {
        "detail": {"natural_products": products, "ad_appearances": ads, "shop_address_pairs": [{"shop_name": shop, "address": address} for shop, address in shop_region_pairs], "product_root_relations_used": root_relations},
        "summary": {
            "definitions": {
                "address": "Normalized source 地址 as shown in the listing export; actual dispatch warehouse, merchant registration and factory location are unverified.",
                "population": "Natural-position products are unique by product ID; advertising records are appearances and remain separate.",
                "shop_count": "Distinct exact shop names within each region. A multi-address shop may appear in several regions; regional shop counts are not additive.",
                "payment": "Source-sheet 付款人数 with unspecified period; not sales units, GMV or causality.",
                "price_bands": "Q1 <= p25; Q2 <= p50; Q3 <= p75; Q4 > p75, using natural-position price quartiles; ties may make bands uneven.",
                "high_payment": "Product at or above the all-natural 90th percentile of displayed 付款人数; ties may make the group larger than 10%.",
                "shop_hhi": "Sum of squared within-region listing shares across exact shop names; a descriptive concentration measure, not market share.",
                "location_quotient": "Root coverage within region divided by root coverage across all natural-position products; descriptive title-language specialization, not buyer demand or production origin.",
                "interpretation_sample_ok": "At least 10 products and 3 shops in a root-region cell; a screening guard, not a significance or opportunity test.",
            },
            "quality": quality,
            "city_regions": region_rows(city_groups, "city_or_address"),
            "province_regions": region_rows(province_groups, "province"),
            "ad_city_regions": ad_regions,
            "root_totals": root_totals,
            "root_regions": root_regions,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned two-sheet workbook")
    parser.add_argument("--output-dir", required=True, help="New directory for geography JSON artifacts")
    parser.add_argument("--title-roots", help="Optional product_roots.json from the same cleaned workbook")
    args = parser.parse_args()
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    title_path = Path(args.title_roots).expanduser().resolve() if args.title_roots else None
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        parser.error("input must be an existing XLSX file")
    if output.exists():
        parser.error("output directory already exists")
    if title_path and not title_path.is_file():
        parser.error("title-roots must be an existing JSON file")
    source_hash = sha256(source)
    natural = pd.read_excel(source, sheet_name="自然位", dtype={"商品ID": str})
    ad = pd.read_excel(source, sheet_name="广告位", dtype={"商品ID": str})
    validate_frame(natural, NATURAL_REQUIRED, "自然位")
    validate_frame(ad, AD_REQUIRED, "广告位")
    products = records_from_frame(natural, True)
    roots = load_title_roots(title_path, source_hash, products) if title_path else None
    result = analyze(natural, ad, roots)
    source_meta = {"file_name": source.name, "sha256": source_hash, "title_roots_file_name": title_path.name if title_path else None,
                   "title_roots_sha256": sha256(title_path) if title_path else None}
    output.mkdir(parents=True, exist_ok=False)
    for name, body in (("geography_detail.json", result["detail"]), ("geography_summary.json", result["summary"])):
        with (output / name).open("x", encoding="utf-8") as handle:
            json.dump({"schema_version": "1.0", "source": source_meta, **body}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps({"output_dir": str(output), "files": ["geography_detail.json", "geography_summary.json"],
                      "quality": result["summary"]["quality"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
