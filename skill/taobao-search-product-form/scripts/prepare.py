#!/usr/bin/env python3
"""Normalize a Taobao search export and prepare auditable image contact sheets."""

import argparse
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageOps


REQUIRED = ["商品ID", "商品名称", "商品图片链接", "占位类型"]
ALLOWED_IMAGE_HOSTS = ("alicdn.com", "alicdn.cn")


def scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_image_url(url):
    parsed = urllib.parse.urlparse(str(url))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_IMAGE_HOSTS)


def fetch_image(product, cache_dir):
    pid = product["product_id"]
    url = product["image_url"]
    if not safe_image_url(url):
        return pid, {"status": "blocked_host", "path": None}
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            blob = response.read(10_000_001)
            if len(blob) > 10_000_000:
                return pid, {"status": "too_large", "path": None}
        image = Image.open(io.BytesIO(blob))
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((500, 500))
        digest = hashlib.sha256(pid.encode()).hexdigest()[:16]
        path = cache_dir / f"{digest}.jpg"
        image.save(path, "JPEG", quality=88, optimize=True)
        return pid, {"status": "ok", "path": str(path.relative_to(cache_dir.parent)), "width": image.width, "height": image.height}
    except Exception as exc:  # fetch errors are reported, never converted into visual labels
        return pid, {"status": "fetch_failed", "path": None, "error": type(exc).__name__}


def make_sheets(products, fetches, out_dir, prefix):
    cell_w, cell_h, columns, per_sheet = 180, 190, 8, 80
    included = [p for p in products if fetches.get(p["product_id"], {}).get("status") == "ok"]
    result = []
    for start in range(0, len(included), per_sheet):
        batch = included[start:start + per_sheet]
        rows = (len(batch) + columns - 1) // columns
        sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "white")
        draw = ImageDraw.Draw(sheet)
        for i, product in enumerate(batch):
            x, y = (i % columns) * cell_w, (i // columns) * cell_h
            path = out_dir / fetches[product["product_id"]]["path"]
            image = Image.open(path)
            image.thumbnail((160, 158))
            sheet.paste(image, (x + (cell_w - image.width) // 2, y + 4))
            draw.text((x + 5, y + 164), f"{product['product_id']}", fill="black")
            rank = product["first_natural"] if product["first_natural"] is not None else product["first_ad"]
            draw.text((x + 5, y + 177), f"{'N' if product['first_natural'] is not None else 'A'} {rank}", fill="black")
        path = out_dir / f"{prefix}-{start // per_sheet + 1:02d}.jpg"
        sheet.save(path, "JPEG", quality=88)
        result.append(path.name)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--search-term")
    parser.add_argument("--max-organic", type=int)
    parser.add_argument("--max-ad-only", type=int, default=50)
    args = parser.parse_args()
    source = Path(args.input).expanduser().resolve()
    out = Path(args.output_dir).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        parser.error("input must be an existing .xlsx file")
    if out.exists():
        parser.error("output directory already exists; select a new path")
    if args.max_organic is not None and args.max_organic < 1:
        parser.error("--max-organic must be positive")
    frame = pd.read_excel(source)
    missing = [column for column in REQUIRED if column not in frame.columns]
    if missing:
        parser.error("missing required columns: " + ", ".join(missing))
    out.mkdir(parents=True)
    cache = out / "images"
    cache.mkdir()
    raw_rows = []
    products = {}
    for index, (_, row) in enumerate(frame.iterrows(), start=1):
        pid = str(scalar(row["商品ID"]))
        position = int(number(row.get("序号")) or index)
        placement = str(scalar(row["占位类型"]) or "")
        if placement not in ("自然位", "广告位"):
            raise ValueError(f"unknown placement at row {index}: {placement}")
        raw = {"product_id": pid, "display_position": position, "placement": placement}
        raw_rows.append(raw)
        if pid not in products:
            products[pid] = {
                "product_id": pid,
                "title": str(scalar(row["商品名称"]) or ""),
                "image_url": str(scalar(row["商品图片链接"]) or ""),
                "item_url": str(scalar(row.get("商品链接")) or ""),
                "price": number(row.get("现价")),
                "payment_count": number(row.get("付款人数")),
                "shop": str(scalar(row.get("店铺名称")) or ""),
                "shop_type": str(scalar(row.get("店铺类型")) or ""),
                "platform_category": str(scalar(row.get("类目")) or ""),
                "natural_positions": [], "ad_positions": [],
            }
        key = "natural_positions" if placement == "自然位" else "ad_positions"
        products[pid][key].append(position)
    entries = list(products.values())
    for product in entries:
        product["first_natural"] = min(product["natural_positions"], default=None)
        product["first_ad"] = min(product["ad_positions"], default=None)
    organic = sorted((p for p in entries if p["first_natural"] is not None), key=lambda p: p["first_natural"])
    for rank, product in enumerate(organic, start=1):
        product["organic_rank"] = rank
    ad_only = sorted((p for p in entries if p["first_natural"] is None), key=lambda p: p["first_ad"])
    selected_organic = organic[:args.max_organic] if args.max_organic else organic
    selected_ad = ad_only[:args.max_ad_only]
    selected = selected_organic + selected_ad
    fetches = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_image, p, cache) for p in selected]
        for future in as_completed(futures):
            pid, result = future.result()
            fetches[pid] = result
    sheets = make_sheets(selected_organic, fetches, out, "organic") + make_sheets(selected_ad, fetches, out, "ad-only")
    stem = source.stem
    inferred = re.search(r"市场分析[-_](.+?)[-_]\d{8}$", stem)
    term = args.search_term or (inferred.group(1) if inferred else "")
    manifest = {
        "schema_version": 1,
        "source": {"name": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "rows": len(raw_rows), "captured_at": datetime.now(timezone.utc).isoformat()},
        "search_term": term,
        "search_term_inferred": args.search_term is None,
        "scope": {"kind": "pilot" if args.max_organic else "full", "organic_selected": len(selected_organic), "organic_total": len(organic), "ad_only_selected": len(selected_ad), "ad_only_total": len(ad_only)},
        "source_rows": raw_rows,
        "products": entries,
        "selected_organic_ids": [p["product_id"] for p in selected_organic],
        "selected_ad_only_ids": [p["product_id"] for p in selected_ad],
        "fetches": fetches,
        "contact_sheets": sheets,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(out / "manifest.json"), "rows": len(raw_rows), "unique_products": len(entries), "organic_products": len(organic), "ad_only_products": len(ad_only), "images_ok": sum(v["status"] == "ok" for v in fetches.values()), "images_requested": len(selected), "contact_sheets": sheets}, ensure_ascii=False))


if __name__ == "__main__":
    main()
