#!/usr/bin/env python3
"""Build auditable product-title roots from a cleaned natural-position sheet.

Requires pandas, an XLSX reader, and a Python package exposing ``jieba``.
Writes a new output directory; never changes the workbook or shared lexicon.
"""

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

try:
    import jieba
except ImportError as error:
    raise SystemExit("jieba is required; install the documented jieba-compatible Python package") from error


REQUIRED = {"商品ID", "商品名称", "商品图片链接", "现价", "付款人数", "店铺名称", "占位类型"}
DEFAULT_LEXICON = Path(__file__).resolve().parents[1] / "references" / "title-lexicon.json"
WORDLIKE = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
SIZE = re.compile(r"(?<!\d)(\d{2}(?:\.\d+)?)\s*(cm|厘米|寸)(?![A-Za-z])", re.IGNORECASE)


def clean_text(value):
    return "" if pd.isna(value) else str(value).strip()


def normalized(value):
    return unicodedata.normalize("NFKC", clean_text(value))


def optional_number(value):
    numeric = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(numeric) else float(numeric)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lexicon(base_path, project_path=None):
    paths = [base_path] + ([project_path] if project_path else [])
    entries = []
    surface_map = {}
    sources = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_version") != "1.0" or not isinstance(document.get("entries"), list):
            raise ValueError(f"invalid title lexicon schema: {path}")
        sources.append({"file_name": path.name, "sha256": file_sha(path), "entry_count": len(document["entries"])})
        for raw in document["entries"]:
            canonical = normalized(raw.get("canonical"))
            facet = clean_text(raw.get("facet"))
            surfaces = raw.get("surfaces")
            if not canonical or not facet or not isinstance(surfaces, list) or not surfaces:
                raise ValueError(f"invalid lexicon entry in {path}: {raw}")
            item = {"canonical": canonical, "facet": facet, "surfaces": []}
            for raw_surface in surfaces:
                surface = normalized(raw_surface)
                if not surface or not WORDLIKE.search(surface):
                    raise ValueError(f"invalid lexicon surface in {path}: {raw_surface}")
                key = surface.casefold()
                current = surface_map.get(key)
                if current and current != (canonical, facet):
                    raise ValueError(f"conflicting lexicon surface {surface}: {current} versus {(canonical, facet)}")
                surface_map[key] = (canonical, facet)
                if surface not in item["surfaces"]:
                    item["surfaces"].append(surface)
            entries.append(item)
    return {"schema_version": "1.0", "entries": entries, "sources": sources}


def match_title(title, lexicon, tokenizer):
    """Return longest mapped phrases per facet plus unclaimed jieba candidates."""
    matches = []
    occupied_by_facet = defaultdict(set)
    surfaces = [
        (surface, entry["canonical"], entry["facet"])
        for entry in lexicon["entries"] for surface in entry["surfaces"]
    ]
    for surface, canonical, facet in sorted(surfaces, key=lambda item: (-len(item[0]), item[0])):
        lower_title = title.casefold()
        lower_surface = surface.casefold()
        start = 0
        while True:
            found = lower_title.find(lower_surface, start)
            if found < 0:
                break
            end = found + len(surface)
            if not any(index in occupied_by_facet[facet] for index in range(found, end)):
                matches.append({"root": canonical, "facet": facet, "surface": title[found:end], "start": found, "end": end, "source": "lexicon"})
                occupied_by_facet[facet].update(range(found, end))
            start = found + 1

    protected = set().union(*occupied_by_facet.values()) if occupied_by_facet else set()
    for found in SIZE.finditer(title):
        root = f"{found.group(1)}{found.group(2).lower()}"
        matches.append({"root": root, "facet": "size_claim", "surface": found.group(), "start": found.start(), "end": found.end(), "source": "size_pattern"})
        protected.update(range(found.start(), found.end()))
    for word, start, end in tokenizer.tokenize(title, HMM=False):
        candidate = word.strip()
        if not candidate or not WORDLIKE.search(candidate) or all(char.isdigit() for char in candidate):
            continue
        if any(index in protected for index in range(start, end)):
            continue
        if len(candidate) < 2:
            continue
        matches.append({"root": candidate.casefold(), "facet": "unclassified", "surface": word, "start": start, "end": end, "source": "jieba_candidate"})

    return sorted(matches, key=lambda item: (item["start"], item["end"], item["facet"], item["root"]))


def percentile(values, quantile):
    numeric = pd.Series([value for value in values if value is not None], dtype="float64")
    return None if numeric.empty else round(float(numeric.quantile(quantile)), 4)


def analyze_frame(frame, lexicon):
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"natural-position sheet missing columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("natural-position sheet is empty")
    ids = frame["商品ID"].map(clean_text)
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError("natural-position product IDs must be nonblank and unique")
    if not frame["占位类型"].map(clean_text).eq("自然位").all():
        raise ValueError("title analysis accepts natural-position rows only")

    tokenizer = jieba.Tokenizer()
    for entry in lexicon["entries"]:
        for surface in entry["surfaces"]:
            tokenizer.add_word(surface, freq=2_000_000)

    products = []
    relations = []
    for _, row in frame.iterrows():
        product_id = clean_text(row["商品ID"])
        title = clean_text(row["商品名称"])
        title_normalized = normalized(title)
        product = {
            "product_id": product_id,
            "title": title,
            "title_normalized": title_normalized,
            "image_url": clean_text(row["商品图片链接"]),
            "price_yuan": optional_number(row["现价"]),
            "payment_people": optional_number(row["付款人数"]),
            "shop_name": clean_text(row["店铺名称"]),
            "shop_type": clean_text(row.get("店铺类型")) or None,
            "natural_position": optional_number(row.get("序号")),
        }
        if not title_normalized or not product["shop_name"]:
            raise ValueError(f"natural-position product {product_id} has a blank title or shop name")
        products.append(product)
        grouped = defaultdict(list)
        for match in match_title(title_normalized, lexicon, tokenizer):
            grouped[(match["facet"], match["root"])].append(match)
        for (facet, root), occurrences in sorted(grouped.items()):
            relations.append({
                "product_id": product_id,
                "root": root,
                "facet": facet,
                "surfaces": sorted({hit["surface"] for hit in occurrences}),
                "occurrence_count_in_title": len(occurrences),
                "spans_in_normalized_title": [[hit["start"], hit["end"]] for hit in occurrences],
                "sources": sorted({hit["source"] for hit in occurrences}),
                "title": title,
                "image_url": product["image_url"],
                "price_yuan": product["price_yuan"],
                "payment_people": product["payment_people"],
                "shop_name": product["shop_name"],
                "shop_type": product["shop_type"],
            })

    by_id = {row["product_id"]: row for row in products}
    payment_threshold = percentile([row["payment_people"] for row in products], 0.9)
    by_root = defaultdict(list)
    by_shop = defaultdict(list)
    mapped_by_product = defaultdict(set)
    for relation in relations:
        by_root[(relation["facet"], relation["root"])].append(relation)
        if relation["facet"] != "unclassified":
            mapped_by_product[relation["product_id"]].add((relation["facet"], relation["root"]))
            by_shop[relation["shop_name"]].append(relation)

    roots = []
    for (facet, root), rows in by_root.items():
        prices = [row["price_yuan"] for row in rows]
        payments = [row["payment_people"] for row in rows]
        shop_groups = defaultdict(list)
        for row in rows:
            shop_groups[row["shop_name"]].append(row)
        top_shops = sorted(
            ({"shop_name": shop, "product_count": len(group), "displayed_payment_people_sum": round(sum(item["payment_people"] or 0 for item in group), 2)} for shop, group in shop_groups.items()),
            key=lambda item: (-item["product_count"], -item["displayed_payment_people_sum"], item["shop_name"]),
        )[:5]
        high = sum(value is not None and payment_threshold is not None and value >= payment_threshold for value in payments)
        roots.append({
            "root": root, "facet": facet, "product_count": len(rows),
            "product_share": round(len(rows) / len(products), 6),
            "shop_count": len(shop_groups),
            "price_p25": percentile(prices, 0.25), "price_median": percentile(prices, 0.5), "price_p75": percentile(prices, 0.75),
            "payment_people_median": percentile(payments, 0.5),
            "payment_people_p75": percentile(payments, 0.75),
            "displayed_payment_people_sum_within_root": round(sum(value or 0 for value in payments), 2),
            "high_payment_product_count": high,
            "high_payment_product_share": round(high / len(rows), 6),
            "top_shops_by_product_count": top_shops,
        })
    roots.sort(key=lambda item: (-item["product_count"], item["facet"], item["root"]))
    root_counts = {(item["facet"], item["root"]): item["product_count"] for item in roots}

    shops = []
    for shop_name, group in frame.groupby("店铺名称", sort=False):
        shop_ids = {clean_text(value) for value in group["商品ID"]}
        shop_relations = by_shop.get(shop_name, [])
        root_groups = defaultdict(list)
        for relation in shop_relations:
            root_groups[(relation["facet"], relation["root"])].append(relation)
        shop_roots = sorted(
            ({"facet": facet, "root": root, "product_count": len(rows), "displayed_payment_people_sum_within_root": round(sum(row["payment_people"] or 0 for row in rows), 2)} for (facet, root), rows in root_groups.items()),
            key=lambda item: (-item["product_count"], -item["displayed_payment_people_sum_within_root"], item["root"]),
        )
        distinctive = []
        for item in shop_roots:
            corpus_count = root_counts[(item["facet"], item["root"])]
            if item["product_count"] < 2 or corpus_count < 5:
                continue
            shop_share = item["product_count"] / len(shop_ids)
            corpus_share = corpus_count / len(products)
            distinctive.append({
                **item,
                "shop_product_share": round(shop_share, 6),
                "corpus_product_share": round(corpus_share, 6),
                "shop_to_corpus_coverage_ratio": round(shop_share / corpus_share, 4),
            })
        distinctive.sort(key=lambda item: (-item["shop_to_corpus_coverage_ratio"], -item["product_count"], item["root"]))
        shops.append({
            "shop_name": shop_name,
            "natural_product_count": len(shop_ids),
            "displayed_payment_people_sum_across_visible_products": round(sum(by_id[pid]["payment_people"] or 0 for pid in shop_ids), 2),
            "top_mapped_roots": shop_roots[:15],
            "top_distinctive_roots": distinctive[:15],
        })
    shops.sort(key=lambda item: (-item["natural_product_count"], item["shop_name"]))

    pairs = Counter()
    for roots_in_product in mapped_by_product.values():
        for first, second in itertools.combinations(sorted(roots_in_product), 2):
            if first[0] != second[0]:
                pairs[(first, second)] += 1
    pair_rows = [
        {"first": {"facet": first[0], "root": first[1]}, "second": {"facet": second[0], "root": second[1]}, "product_count": count}
        for (first, second), count in sorted(pairs.items(), key=lambda item: (-item[1], item[0]))
        if count >= 5
    ][:500]

    candidate_rows = [
        {"candidate": root["root"], "product_count": root["product_count"], "shop_count": root["shop_count"], "example_product_ids": [row["product_id"] for row in by_root[("unclassified", root["root"])][:5]]}
        for root in roots if root["facet"] == "unclassified" and root["product_count"] >= 3
    ][:500]
    quality = {
        "natural_product_count": len(products),
        "distinct_product_ids": len(by_id),
        "product_root_rows": len(relations),
        "products_with_mapped_root": len(mapped_by_product),
        "mapped_product_root_rows": sum(row["facet"] != "unclassified" for row in relations),
        "candidate_product_root_rows": sum(row["facet"] == "unclassified" for row in relations),
        "missing_price_count": sum(row["price_yuan"] is None for row in products),
        "missing_payment_count": sum(row["payment_people"] is None for row in products),
        "payment_high_threshold_p90": payment_threshold,
        "actual_products_at_or_above_p90": sum(row["payment_people"] is not None and row["payment_people"] >= payment_threshold for row in products) if payment_threshold is not None else 0,
    }
    if len(products) != len(by_id) or any(len({row["product_id"] for row in group}) != len(group) for group in by_root.values()):
        raise ValueError("product/root identity reconciliation failed")
    return {"products": products, "product_roots": relations, "roots": roots, "shops": shops, "root_pairs": pair_rows, "candidate_terms": candidate_rows, "quality": quality}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned XLSX with a 自然位 sheet")
    parser.add_argument("--output-dir", required=True, help="New directory for title-root JSON artifacts")
    parser.add_argument("--project-lexicon", help="Optional reviewed lexicon JSON for this project; never modified")
    args = parser.parse_args()
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    project = Path(args.project_lexicon).expanduser().resolve() if args.project_lexicon else None
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        parser.error("input must be an existing XLSX file")
    if output.exists():
        parser.error("output directory already exists")
    if project and not project.is_file():
        parser.error("project lexicon must be an existing JSON file")
    lexicon = load_lexicon(DEFAULT_LEXICON, project)
    frame = pd.read_excel(source, sheet_name="自然位", dtype={"商品ID": str})
    result = analyze_frame(frame, lexicon)
    try:
        jieba_version = importlib.metadata.version("jieba-py")
        distribution = "jieba-py"
    except importlib.metadata.PackageNotFoundError:
        jieba_version = importlib.metadata.version("jieba")
        distribution = "jieba"
    source_meta = {"file_name": source.name, "sha256": file_sha(source), "sheet": "自然位", "jieba_distribution": distribution, "jieba_version": jieba_version}
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "product_roots.json": {"schema_version": "1.0", "source": source_meta, "products": result["products"], "product_roots": result["product_roots"]},
        "root_summary.json": {"schema_version": "1.0", "source": source_meta, "definitions": {"root_coverage": "Distinct natural-position product IDs containing this title-root claim; not buyer search-query volume.", "payment": "Source-sheet 付款人数 with unspecified period; a product can belong to several roots, so sums across roots are non-additive.", "form": "Title-stated form only; real product form requires image review.", "shop_to_corpus_coverage_ratio": "Share of one shop's visible products using a root divided by the share of all visible products using that root; descriptive, not proof of merchant intent."}, "quality": result["quality"], "roots": result["roots"], "shops": result["shops"], "root_pairs": result["root_pairs"]},
        "lexicon_snapshot.json": {"schema_version": "1.0", "source": source_meta, "dictionary_policy": "Versioned bundled vocabulary plus optional reviewed project vocabulary; each run stores a snapshot and candidates but never mutates either lexicon.", **lexicon},
        "lexicon_candidates.json": {"schema_version": "1.0", "source": source_meta, "promotion_policy": "Candidates need semantic review before inclusion in a later versioned lexicon.", "candidates": result["candidate_terms"]},
    }
    for filename, document in artifacts.items():
        with (output / filename).open("x", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps({"output_dir": str(output), "files": list(artifacts), "quality": result["quality"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
