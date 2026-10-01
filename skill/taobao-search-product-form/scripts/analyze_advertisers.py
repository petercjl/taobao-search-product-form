#!/usr/bin/env python3
"""Profile advertisers in a cleaned two-sheet Taobao search workbook."""

import argparse
import bisect
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd


REQUIRED = {"商品ID", "店铺名称", "占位类型"}
SYSTEM_DISPLAY_SHOP_LABELS = {"百亿补贴品牌优选"}


def text(value):
    return "" if pd.isna(value) else str(value).strip()


def position(value):
    if pd.isna(value):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def number(value):
    if pd.isna(value):
        return None
    return float(value)


def total_or_none(values):
    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    return int(numeric.sum()) if numeric.notna().any() else None


def median_or_none(values):
    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    return float(numeric.median()) if numeric.notna().any() else None


def price_band(value, edges):
    return None if value is None else bisect.bisect_right(edges, value)


def price_band_labels(edges):
    fmt = lambda value: f"¥{value:g}"
    return [f"<{fmt(edges[0])}"] + [f"{fmt(a)}–<{fmt(b)}" for a, b in zip(edges, edges[1:])] + [f"≥{fmt(edges[-1])}"]


def load_sheet(source, sheet_name, placement):
    frame = pd.read_excel(source, sheet_name=sheet_name, dtype={"商品ID": str})
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"{sheet_name}: missing columns {sorted(missing)}")
    frame["商品ID"] = frame["商品ID"].map(text)
    frame["店铺名称"] = frame["店铺名称"].map(text)
    if (frame["商品ID"] == "").any() or (frame["店铺名称"] == "").any():
        raise ValueError(f"{sheet_name}: blank product ID or shop name")
    if not frame["占位类型"].map(text).eq(placement).all():
        raise ValueError(f"{sheet_name}: unexpected placement label")
    return frame


def resolve_advertiser_shops(ads):
    """Keep source display labels while resolving corroborated platform aliases."""
    ads = ads.copy()
    ads["_resolved_shop_name"] = ads["店铺名称"]
    ads["_shop_resolution"] = "exact_display_name"
    aliases = []
    for product_id, group in ads.groupby("商品ID", sort=False):
        names = set(group["店铺名称"])
        aliases_for_product = names & SYSTEM_DISPLAY_SHOP_LABELS
        if not aliases_for_product:
            if len(names) != 1:
                raise ValueError(f"广告位 product {product_id} has unresolved multiple shop names: {sorted(names)}")
            continue
        actual_names = names - SYSTEM_DISPLAY_SHOP_LABELS
        sellers = {text(value) for value in group.get("掌柜名", pd.Series(dtype=str)) if text(value)}
        if len(actual_names) != 1 or sellers != actual_names:
            raise ValueError(
                f"广告位 product {product_id} has an unresolved display shop label: "
                f"display names={sorted(names)}, seller names={sorted(sellers)}"
            )
        actual_shop = next(iter(actual_names))
        alias_mask = (ads["商品ID"] == product_id) & ads["店铺名称"].isin(aliases_for_product)
        ads.loc[alias_mask, "_resolved_shop_name"] = actual_shop
        ads.loc[alias_mask, "_shop_resolution"] = "system_display_label_corroborated_by_seller_and_same_id_shop"
        aliases.append({
            "product_id": product_id,
            "resolved_shop_name": actual_shop,
            "display_shop_names": sorted(names),
            "alias_appearance_count": int(alias_mask.sum()),
            "basis": "same product ID has an actual shop display name matching every seller name",
        })
    return ads, aliases


def analyze(source, supplied_price_bands=None):
    natural = load_sheet(source, "自然位", "自然位")
    ads = load_sheet(source, "广告位", "广告位")
    if natural["商品ID"].duplicated().any():
        raise ValueError("自然位 must contain one first-seen row per product ID")
    if ads.empty:
        raise ValueError("广告位 is empty; no advertiser profile can be calculated")
    if "现价" not in ads or "现价" not in natural or "付款人数" not in natural:
        raise ValueError("price comparison needs 现价 in both sheets and 付款人数 in 自然位")

    natural_by_id = natural.set_index("商品ID")
    natural_ids = set(natural["商品ID"])
    natural_shop_counts = natural.groupby("店铺名称")["商品ID"].nunique().to_dict()
    ads, alias_resolutions = resolve_advertiser_shops(ads)
    ads["_resolved_shop_type"] = ads.get("店铺类型", pd.Series([None] * len(ads)))
    for entry in alias_resolutions:
        actual_rows = ads[(ads["商品ID"] == entry["product_id"]) & (ads["店铺名称"] == entry["resolved_shop_name"])]
        actual_types = [text(value) for value in actual_rows.get("店铺类型", []) if text(value)]
        if actual_types:
            alias_mask = (ads["商品ID"] == entry["product_id"]) & (ads["店铺名称"] != entry["resolved_shop_name"])
            ads.loc[alias_mask, "_resolved_shop_type"] = actual_types[0]
    ad_product_counts = ads["商品ID"].value_counts()
    ad_unique = ads.drop_duplicates("商品ID", keep="first")
    ad_unique_prices = pd.to_numeric(ad_unique["现价"], errors="coerce")
    if supplied_price_bands is None:
        edges = sorted(set(round(float(value), 2) for value in ad_unique_prices.quantile([0.25, 0.5, 0.75]).dropna()))
        band_source = "advertised-product price quartiles"
    else:
        edges = supplied_price_bands
        band_source = "run-supplied boundaries after inspecting the source prices"
    if not edges or any(edge <= 0 for edge in edges) or edges != sorted(set(edges)):
        raise ValueError("price band boundaries must be positive, unique and ascending")
    labels = price_band_labels(edges)

    products = []
    for product_id, group in ads.groupby("商品ID", sort=False):
        shop_names = group["_resolved_shop_name"].unique().tolist()
        if len(shop_names) != 1:
            raise ValueError(f"广告位 product {product_id} has unresolved multiple shop names: {shop_names}")
        first = group.iloc[0]
        actual_rows = group[group["店铺名称"] == shop_names[0]]
        shop_type_row = actual_rows.iloc[0] if not actual_rows.empty else first
        natural_row = natural_by_id.loc[product_id] if product_id in natural_ids else None
        natural_shop = text(natural_row["店铺名称"]) if natural_row is not None else None
        ad_prices = sorted(set(float(value) for value in pd.to_numeric(group["现价"], errors="coerce").dropna()))
        first_ad_price = number(pd.to_numeric(first["现价"], errors="coerce"))
        products.append({
            "product_id": product_id,
            "title": text(first.get("商品名称")),
            "shop_name": shop_names[0],
            "shop_type": text(shop_type_row.get("店铺类型")) or None,
            "display_shop_names_in_source": list(dict.fromkeys(group["店铺名称"].tolist())),
            "system_display_alias_appearances": int(group["_shop_resolution"].ne("exact_display_name").sum()),
            "ad_appearances": len(group),
            "ad_positions": [position(value) for value in group.get("序号", pd.Series([None] * len(group)))],
            "ad_price_first_appearance": first_ad_price,
            "ad_price_band": labels[price_band(first_ad_price, edges)] if first_ad_price is not None else None,
            "ad_price_values_in_source": ad_prices,
            "ad_price_varies_across_appearances": len(ad_prices) > 1,
            "in_natural": natural_row is not None,
            "natural_position": position(natural_row.get("序号")) if natural_row is not None else None,
            "natural_shop_name": natural_shop,
            "natural_price": number(pd.to_numeric(natural_row.get("现价"), errors="coerce")) if natural_row is not None else None,
            "natural_payment_people": number(pd.to_numeric(natural_row.get("付款人数"), errors="coerce")) if natural_row is not None else None,
            "cross_placement_shop_name_differs": natural_shop is not None and natural_shop != shop_names[0],
        })
    product_by_id = {row["product_id"]: row for row in products}

    shops = []
    for shop_name, group in ads.groupby("_resolved_shop_name", sort=False):
        product_ids = list(dict.fromkeys(group["商品ID"].tolist()))
        shop_types = sorted({text(value) for value in group["_resolved_shop_type"] if text(value)})
        overlap_count = sum(product_by_id[pid]["in_natural"] for pid in product_ids)
        shop_natural = natural[natural["店铺名称"] == shop_name]
        natural_advertised = shop_natural[shop_natural["商品ID"].isin(product_ids)]
        natural_unadvertised = shop_natural[~shop_natural["商品ID"].isin(product_ids)]
        matching_ad_natural = natural[natural["商品ID"].isin(product_ids)]
        top_natural = shop_natural.sort_values("付款人数", ascending=False).iloc[0] if not shop_natural.empty else None
        first_ad_prices = [product_by_id[pid]["ad_price_first_appearance"] for pid in product_ids]
        shops.append({
            "shop_name": shop_name,
            "shop_types": shop_types,
            "ad_product_count": len(product_ids),
            "ad_appearance_count": len(group),
            "ad_products_in_natural": overlap_count,
            "ad_only_products": len(product_ids) - overlap_count,
            "natural_product_count_by_exact_shop_name": natural_shop_counts.get(shop_name, 0),
            "shop_name_present_in_natural": shop_name in natural_shop_counts,
            "ad_product_ids": product_ids,
            "ad_price_median_by_unique_product": median_or_none(first_ad_prices),
            "natural_shop_payment_people_sum": total_or_none(shop_natural["付款人数"]),
            "natural_shop_payment_people_median_per_product": median_or_none(shop_natural["付款人数"]),
            "natural_advertised_product_count_by_same_shop_name": len(natural_advertised),
            "natural_advertised_product_payment_people_sum_by_same_shop_name": total_or_none(natural_advertised["付款人数"]),
            "natural_unadvertised_product_count_by_same_shop_name": len(natural_unadvertised),
            "natural_unadvertised_product_payment_people_sum_by_same_shop_name": total_or_none(natural_unadvertised["付款人数"]),
            "matching_ad_product_payment_people_sum_by_id": total_or_none(matching_ad_natural["付款人数"]),
            "highest_payment_natural_product": None if top_natural is None else {
                "product_id": text(top_natural["商品ID"]),
                "title": text(top_natural.get("商品名称")),
                "payment_people": number(top_natural["付款人数"]),
                "advertised_by_this_shop": text(top_natural["商品ID"]) in product_ids,
            },
            "natural_unadvertised_product_ids_by_same_shop_name": natural_unadvertised["商品ID"].tolist(),
        })
    product_ranks = {row["shop_name"]: rank for rank, row in enumerate(sorted(shops, key=lambda row: (-row["ad_product_count"], -row["ad_appearance_count"], row["shop_name"])), start=1)}
    shops.sort(key=lambda row: (-row["ad_appearance_count"], -row["ad_product_count"], row["shop_name"]))
    cumulative_products = cumulative_appearances = 0
    for rank, row in enumerate(shops, start=1):
        cumulative_products += row["ad_product_count"]
        cumulative_appearances += row["ad_appearance_count"]
        row["rank_by_ad_appearances"] = rank
        row["rank_by_ad_products"] = product_ranks[row["shop_name"]]
        row["ad_product_share"] = round(row["ad_product_count"] / len(products), 6)
        row["ad_appearance_share"] = round(row["ad_appearance_count"] / len(ads), 6)
        row["cumulative_ad_product_share_in_appearance_rank"] = round(cumulative_products / len(products), 6)
        row["cumulative_ad_appearance_share"] = round(cumulative_appearances / len(ads), 6)

    def type_breakdown(frame, grain):
        if "店铺类型" not in frame.columns:
            return {}
        result = {}
        for shop_type, group in frame.groupby(frame["店铺类型"].map(lambda x: text(x) or "未标注")):
            result[shop_type] = {
                "shop_count": group["_resolved_shop_name"].nunique() if grain == "ads" else group["店铺名称"].nunique(),
                "product_count": group["商品ID"].nunique(),
            }
            if grain == "ads":
                result[shop_type]["appearance_count"] = len(group)
        return result

    overlap_products = sum(row["in_natural"] for row in products)
    overlap_shops = sum(row["shop_name_present_in_natural"] for row in shops)
    repeat_distribution = dict(sorted(Counter(ad_product_counts.tolist()).items()))
    advertiser_shop_names = {row["shop_name"] for row in shops}
    natural_layout = [
        {
            "product_id": text(row["商品ID"]),
            "shop_name": text(row["店铺名称"]),
            "title": text(row.get("商品名称")),
            "natural_price": number(pd.to_numeric(row["现价"], errors="coerce")),
            "natural_payment_people": number(pd.to_numeric(row["付款人数"], errors="coerce")),
            "advertised_by_same_shop_name": text(row["商品ID"]) in product_by_id and product_by_id[text(row["商品ID"])]["shop_name"] == text(row["店铺名称"]),
            "advertised_by_any_shop_name": text(row["商品ID"]) in product_by_id,
        }
        for _, row in natural[natural["店铺名称"].isin(advertiser_shop_names)].iterrows()
    ]

    def price_distribution(rows, key, shop_key=None):
        result = []
        valid = [row for row in rows if row[key] is not None]
        for index, label in enumerate(labels):
            selected = [row for row in valid if price_band(row[key], edges) == index]
            entry = {"band": label, "product_count": len(selected), "share_of_priced_products": round(len(selected) / len(valid), 6) if valid else None}
            if shop_key:
                entry["shop_count"] = len({row[shop_key] for row in selected})
            result.append(entry)
        return {"priced_product_count": len(valid), "missing_price_count": len(rows) - len(valid), "bands": result}

    ad_price_distribution = price_distribution(products, "ad_price_first_appearance", "shop_name")
    natural_price_rows = [{"price": number(pd.to_numeric(row["现价"], errors="coerce"))} for _, row in natural.iterrows()]
    natural_price_distribution = price_distribution(natural_price_rows, "price")
    non_advertised_layout = [row for row in natural_layout if not row["advertised_by_same_shop_name"]]
    natural_non_ad_price_distribution = price_distribution(non_advertised_layout, "natural_price", "shop_name")
    counts = {
        "natural_products": len(natural),
        "natural_shops_by_exact_name": natural["店铺名称"].nunique(),
        "ad_appearances": len(ads),
        "ad_products": len(products),
        "advertiser_shops_by_exact_name": len(shops),
        "ad_appearances_with_resolved_system_display_label": sum(row["alias_appearance_count"] for row in alias_resolutions),
        "ad_products_with_resolved_system_display_label": len(alias_resolutions),
        "ad_products_in_natural": overlap_products,
        "ad_only_products": len(products) - overlap_products,
        "advertiser_shops_in_natural_by_exact_name": overlap_shops,
        "advertiser_shops_not_in_natural_by_exact_name": len(shops) - overlap_shops,
        "ad_products_repeated_in_ad_slots": sum(count > 1 for count in ad_product_counts),
        "ad_products_with_cross_placement_shop_name_difference": sum(row["cross_placement_shop_name_differs"] for row in products),
        "advertiser_shops_with_one_ad_product": sum(row["ad_product_count"] == 1 for row in shops),
        "natural_products_in_advertiser_shops_by_exact_name": len(natural_layout),
        "natural_products_not_advertised_by_same_shop_name": len(non_advertised_layout),
        "advertised_products_with_ad_price_variation": sum(row["ad_price_varies_across_appearances"] for row in products),
        "ad_rows_with_zero_displayed_payment_people": int(pd.to_numeric(ads["付款人数"], errors="coerce").eq(0).sum()) if "付款人数" in ads else None,
    }
    if sum(row["ad_product_count"] for row in shops) != len(products):
        raise ValueError("QA failed: shop-level product counts do not reconcile")
    if sum(row["ad_appearance_count"] for row in shops) != len(ads):
        raise ValueError("QA failed: shop-level appearance counts do not reconcile")

    return {
        "schema_version": "1.1",
        "source": {"file_name": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "sheets": ["自然位", "广告位"]},
        "definitions": {
            "ad_appearance": "One row in the advertising-position sheet; not an impression, click, spend, or campaign count.",
            "ad_product": "One unique product ID in advertising positions, regardless of repeated appearances.",
            "advertiser_shop": "One resolved shop name in advertising positions; a known platform display label is assigned to the same-ID actual shop only when every seller name corroborates it. Matching names are not proof of a shared legal entity or brand.",
            "product_natural_overlap": "The same product ID appears in the natural-position sheet.",
            "shop_natural_overlap": "The same exact shop name appears in the natural-position sheet.",
            "natural_payment_people": "The source field 付款人数 on first-seen natural-position product rows; its time window is unspecified. A shop-level sum adds displayed product values and is not storewide sales or unique shop buyers.",
            "natural_shop_layout": "Natural-position products under the same exact shop name, split by whether that shop advertises the same product ID.",
            "ad_price": "The first advertising appearance's 现价 for each product ID; all observed ad prices and any variation remain in the product detail.",
        },
        "counts": counts,
        "ad_appearances_per_product_distribution": {str(k): v for k, v in repeat_distribution.items()},
        "shop_type_breakdown": {"advertising": type_breakdown(ads.assign(店铺类型=ads["_resolved_shop_type"]), "ads"), "natural": type_breakdown(natural, "natural")},
        "system_display_label_resolutions": alias_resolutions,
        "price_bands": {
            "boundaries_yuan": edges,
            "boundary_source": band_source,
            "interval_rule": "left-inclusive, right-exclusive",
            "advertised_unique_products": ad_price_distribution,
            "all_natural_unique_products": natural_price_distribution,
            "natural_products_in_advertiser_shops_not_advertised_by_same_shop": natural_non_ad_price_distribution,
        },
        "advertiser_shops": shops,
        "ad_products": products,
        "natural_products_of_advertiser_shops": natural_layout,
        "ad_appearance_records": [
            {"product_id": text(row["商品ID"]), "shop_name": text(row["_resolved_shop_name"]), "display_shop_name": text(row["店铺名称"]), "shop_resolution": text(row["_shop_resolution"]), "position": position(row.get("序号"))}
            for _, row in ads.iterrows()
        ],
        "quality": {"shop_identity_key": "resolved_shop_name_with_source_display_preserved", "product_identity_key": "product_id", "reconciled_shop_product_count": True, "reconciled_shop_appearance_count": True, "natural_payment_field": "付款人数", "ad_payment_field_used_for_sales_conclusion": False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned XLSX with 自然位 and 广告位 sheets")
    parser.add_argument("--output", required=True, help="New JSON file; existing files are refused")
    parser.add_argument("--price-bands", help="Optional ascending comma-separated price boundaries in yuan; defaults to advertised-product quartiles")
    args = parser.parse_args()
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        parser.error("input must be an existing XLSX file")
    if output.exists():
        parser.error("output already exists")
    try:
        price_bands = [float(value.strip()) for value in args.price_bands.split(",")] if args.price_bands else None
    except ValueError as error:
        parser.error(f"invalid --price-bands: {error}")
    result = analyze(source, price_bands)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(output), "counts": result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
