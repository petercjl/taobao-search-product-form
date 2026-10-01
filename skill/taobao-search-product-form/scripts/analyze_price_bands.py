#!/usr/bin/env python3
"""Find data-dependent Jenks price bands in a cleaned search workbook.

Natural-position products define the fitted population. Advertising rows are
reported against those same boundaries but never influence the fit.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


NATURAL_REQUIRED = {"商品ID", "商品名称", "店铺名称", "现价", "付款人数", "占位类型"}
AD_REQUIRED = {"商品ID", "现价", "占位类型"}
METHOD = "log-price-weighted-jenks-marginal-gain-v1"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required(frame, fields, placement):
    missing = fields - set(frame.columns)
    if missing:
        raise ValueError(f"{placement} sheet missing columns: {sorted(missing)}")
    if not frame["占位类型"].astype(str).eq(placement).all():
        raise ValueError(f"{placement} sheet contains another placement type")
    ids = frame["商品ID"].fillna("").astype(str).str.strip()
    if ids.eq("").any():
        raise ValueError(f"{placement} sheet has blank product IDs")
    return ids


def positive_prices(frame, placement):
    prices = pd.to_numeric(frame["现价"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError(f"{placement} sheet has missing, non-finite or non-positive current prices")
    return prices


def jenks_models(prices, *, max_bands=10, minimum_share=0.02):
    """Exact 1-D Jenks on log(price), with repeated prices kept in one band."""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 2 or not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("at least two finite, positive prices are required")
    values, counts = np.unique(prices, return_counts=True)
    if len(values) < 2:
        return [{"band_count": 1, "sse": 0.0, "explained_variance": 1.0,
                 "marginal_gain": None, "boundaries": [], "counts": [len(prices)]}]
    if len(values) > 3000:
        raise ValueError("more than 3000 distinct prices; exact Jenks needs a scalable implementation")
    floor = max(2, math.ceil(len(prices) * minimum_share))
    limit = min(max_bands, len(values), len(prices) // floor)
    logs = np.log(values)
    cumulative_n = np.r_[0, np.cumsum(counts)]
    cumulative_x = np.r_[0, np.cumsum(counts * logs)]
    cumulative_x2 = np.r_[0, np.cumsum(counts * logs * logs)]
    width = len(values)
    dp = np.full((limit + 1, width + 1), np.inf)
    previous = np.full((limit + 1, width + 1), -1, dtype=int)
    dp[0, 0] = 0.0
    for bands in range(1, limit + 1):
        for end in range(bands, width + 1):
            start = np.arange(bands - 1, end)
            population = cumulative_n[end] - cumulative_n[start]
            eligible = (population >= floor) & (cumulative_n[start] >= (bands - 1) * floor)
            if not eligible.any():
                continue
            start = start[eligible]
            population = population[eligible]
            total = cumulative_x[end] - cumulative_x[start]
            cost = cumulative_x2[end] - cumulative_x2[start] - total * total / population
            scores = dp[bands - 1, start] + np.maximum(cost, 0)
            winner = int(np.argmin(scores))
            if np.isfinite(scores[winner]):
                dp[bands, end] = scores[winner]
                previous[bands, end] = start[winner]
    baseline = float(dp[1, width])
    models = []
    for bands in range(1, limit + 1):
        if not np.isfinite(dp[bands, width]):
            continue
        end = width
        ranges = []
        for tier in range(bands, 0, -1):
            start = int(previous[tier, end])
            ranges.append((start, end))
            end = start
        ranges.reverse()
        boundaries = [float(values[start]) for start, _ in ranges[1:]]
        sizes = [int(cumulative_n[end] - cumulative_n[start]) for start, end in ranges]
        explained = 1 - float(dp[bands, width]) / baseline if baseline > 0 else 1.0
        prior = models[-1]["explained_variance"] if models else None
        models.append({"band_count": bands, "sse": round(float(dp[bands, width]), 8),
                       "explained_variance": round(explained, 8),
                       "marginal_gain": round(explained - prior, 8) if prior is not None else None,
                       "boundaries": boundaries, "counts": sizes})
    return models


def select_model(models, complexity_penalty=0.03):
    """Stop before an extra band explains less than the declared complexity cost."""
    if not 0 < complexity_penalty < 1:
        raise ValueError("complexity penalty must be between zero and one")
    selected = models[0]
    for model in models[1:]:
        if model["marginal_gain"] < complexity_penalty:
            break
        selected = model
    return selected


def assign(price, boundaries):
    return int(np.searchsorted(boundaries, price, side="right")) + 1


def bootstrap_stability(prices, selected_count, complexity_penalty, replicates, seed):
    if replicates < 0:
        raise ValueError("bootstrap replicates must not be negative")
    if not replicates:
        return None
    rng = np.random.default_rng(seed)
    selections = Counter()
    same_count_boundaries = []
    for _ in range(replicates):
        sample = rng.choice(prices, size=len(prices), replace=True)
        chosen = select_model(jenks_models(sample), complexity_penalty)
        selections[chosen["band_count"]] += 1
        if chosen["band_count"] == selected_count:
            same_count_boundaries.append(chosen["boundaries"])
    intervals = []
    if same_count_boundaries and selected_count > 1:
        matrix = np.asarray(same_count_boundaries)
        for index in range(selected_count - 1):
            intervals.append({"boundary_number": index + 1,
                              "p10": round(float(np.quantile(matrix[:, index], 0.1)), 4),
                              "median": round(float(np.median(matrix[:, index])), 4),
                              "p90": round(float(np.quantile(matrix[:, index], 0.9)), 4)})
    return {"replicates": replicates, "seed": seed,
            "selected_band_count_frequency": {str(k): selections[k] for k in sorted(selections)},
            "same_band_count_share": round(selections[selected_count] / replicates, 6),
            "same_count_boundary_intervals": intervals,
            "note": "Intervals use only resamples selecting the original band count; low same-count share means boundaries are provisional."}


def analyze(natural, advertising, source_hash, *, complexity_penalty=0.03,
            bootstrap_replicates=0, bootstrap_seed=20260927):
    ids = required(natural, NATURAL_REQUIRED, "自然位")
    required(advertising, AD_REQUIRED, "广告位")
    if ids.duplicated().any():
        raise ValueError("natural-position product IDs must be unique")
    prices = positive_prices(natural, "自然位")
    ad_prices = positive_prices(advertising, "广告位") if len(advertising) else np.array([])
    models = jenks_models(prices)
    selected = select_model(models, complexity_penalty)
    boundaries = selected["boundaries"]
    payments = pd.to_numeric(natural["付款人数"], errors="coerce")
    if ((payments.dropna() < 0) | ~np.isfinite(payments.dropna())).any():
        raise ValueError("natural-position payment counts must be finite and non-negative")
    products = []
    for row, product_id, price, payment in zip(natural.to_dict("records"), ids, prices, payments):
        products.append({"product_id": product_id, "title": str(row["商品名称"]),
                         "shop_name": str(row["店铺名称"]), "price_yuan": float(price),
                         "payment_people": None if pd.isna(payment) else float(payment),
                         "band": assign(price, boundaries)})
    ad_ids = advertising["商品ID"].astype(str).tolist()
    ad_rows = [{"product_id": product_id, "price_yuan": float(price),
                "band": assign(price, boundaries)} for product_id, price in zip(ad_ids, ad_prices)]
    first_ads = {}
    for row in ad_rows:
        first_ads.setdefault(row["product_id"], row)
    ad_unique = list(first_ads.values())
    groups = []
    for band in range(1, selected["band_count"] + 1):
        members = [item for item in products if item["band"] == band]
        displayed = [item["price_yuan"] for item in members]
        paid = [item["payment_people"] for item in members if item["payment_people"] is not None]
        groups.append({"band": band,
                       "lower_inclusive": float(prices.min()) if band == 1 else boundaries[band - 2],
                       "upper_exclusive": boundaries[band - 1] if band <= len(boundaries) else None,
                       "product_count": len(members), "product_share": round(len(members) / len(products), 6),
                       "shop_count": len({item["shop_name"] for item in members}),
                       "price_min": min(displayed), "price_median": float(np.median(displayed)),
                       "price_max": max(displayed),
                       "payment_known_count": len(paid),
                       "payment_people_median": float(np.median(paid)) if paid else None,
                       "ad_appearance_count": sum(item["band"] == band for item in ad_rows),
                       "ad_unique_product_count": sum(item["band"] == band for item in ad_unique)})
    if sum(item["product_count"] for item in groups) != len(products):
        raise RuntimeError("natural product bands do not reconcile")
    if sum(item["ad_appearance_count"] for item in groups) != len(ad_rows):
        raise RuntimeError("advertising appearances do not reconcile")
    detail = {"source": {"sha256": source_hash, "sheet": "自然位"},
              "products": products, "advertising_appearances": ad_rows}
    summary = {"source": {"sha256": source_hash, "natural_sheet": "自然位", "advertising_sheet": "广告位"},
               "method": METHOD,
               "definitions": {"fit_population": "Every cleaned natural-position product ID; no product eligibility filter in this module.",
                               "fit_field": "现价, the displayed current price; not a verified transaction price.",
                               "transform": "Natural logarithm of positive price; Jenks minimizes within-band squared log-price deviation.",
                               "selection": "Choose the largest sequential band count whose additional explained variance meets the complexity penalty; each band needs minimum support.",
                               "advertising": "Advertising appearances and first-seen unique advertised IDs are mapped to fitted natural boundaries but do not fit them.",
                               "payment": "付款人数 is a source display field with unspecified observation window; it is not conversion, units or GMV.",
                               "interpretation": "Price-density breaks describe visible supply, not proven buyer psychological thresholds or opportunity."},
               "parameters": {"complexity_penalty": complexity_penalty, "minimum_share": 0.02,
                              "minimum_count": max(2, math.ceil(len(products) * 0.02)), "max_bands": 10},
               "candidate_models": models, "selected_model": selected, "bands": groups,
               "bootstrap_stability": bootstrap_stability(prices, selected["band_count"],
                                                        complexity_penalty, bootstrap_replicates, bootstrap_seed),
               "sensitivity": {str(value): select_model(models, value)["band_count"] for value in (0.02, 0.03, 0.04)},
               "quality": {"natural_product_count": len(products),
                           "natural_unique_product_id_count": len(set(ids)),
                           "advertising_appearance_count": len(ad_rows),
                           "advertising_unique_product_count": len(ad_unique),
                           "missing_payment_count": int(payments.isna().sum()),
                           "boundary_count": len(boundaries),
                           "all_natural_assigned": True}}
    return detail, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--complexity-penalty", type=float, default=0.03)
    parser.add_argument("--bootstrap-replicates", type=int, default=30)
    parser.add_argument("--bootstrap-seed", type=int, default=20260927)
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input workbook not found: {args.input}")
    if args.output_dir.exists():
        parser.error(f"output path already exists: {args.output_dir}")
    natural = pd.read_excel(args.input, sheet_name="自然位", dtype={"商品ID": str})
    advertising = pd.read_excel(args.input, sheet_name="广告位", dtype={"商品ID": str})
    detail, summary = analyze(natural, advertising, sha256(args.input),
                              complexity_penalty=args.complexity_penalty,
                              bootstrap_replicates=args.bootstrap_replicates,
                              bootstrap_seed=args.bootstrap_seed)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, document in (("price_band_detail.json", detail), ("price_band_summary.json", summary)):
        (args.output_dir / name).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(args.output_dir), "selected_band_count": summary["selected_model"]["band_count"],
                      "boundaries": summary["selected_model"]["boundaries"], "quality": summary["quality"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
