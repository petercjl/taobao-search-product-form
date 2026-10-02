#!/usr/bin/env python3
"""Assemble a comprehensive report ViewModel from reviewed run artifacts.

This adapter transforms evidence and interpretation; HTML is rendered only by
the package's pinned report runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from openpyxl import load_workbook


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def read_product_links(workbook_path: Path) -> dict[str, str]:
    """Preserve source-listing links at the unique natural product-ID grain."""
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["自然位"]
        rows = sheet.values
        columns = {str(value): index for index, value in enumerate(next(rows))}
        if not {"商品ID", "商品链接"} <= columns.keys():
            raise ValueError("cleaned natural sheet requires 商品ID and 商品链接")
        links: dict[str, str] = {}
        for row in rows:
            pid = str(row[columns["商品ID"]] or "").strip()
            url = str(row[columns["商品链接"]] or "").strip()
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            allowed_host = host in {"taobao.com", "tmall.com"} or host.endswith((".taobao.com", ".tmall.com"))
            if not pid or pid in links:
                raise ValueError(f"blank or duplicate natural product ID in link source: {pid!r}")
            if parsed.scheme != "https" or not allowed_host or parsed.username or parsed.password:
                raise ValueError(f"invalid marketplace URL for product {pid}")
            if parse_qs(parsed.query).get("id") != [pid]:
                raise ValueError(f"marketplace URL ID disagrees with product {pid}")
            links[pid] = url
        return links
    finally:
        workbook.close()


def plain(text: object) -> str:
    value = str(text if text is not None else "")
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
    return value.replace("**", "").replace("__", "").replace("`", "").strip()


def visual_group(product: dict) -> str:
    if product.get("form"):
        return product["form"]
    return "未识图" if product.get("visual_status") == "not_observed" else "待确认形态"


def visual_state(status: str) -> str:
    return {"tagged": "分类明确", "uncertain": "待确认", "not_observed": "未识图（图片不可用）"}.get(status, "待确认")


def table(title: str, columns: list[tuple[str, str]], rows: list[dict], meta: str = "") -> dict:
    return {
        "type": "table",
        "title": title,
        "meta": meta or f"{len(rows)} 行",
        "columns": [label for _, label in columns],
        "rows": [[row.get(key) for key, _ in columns] for row in rows],
    }


def point_tone(label: str) -> tuple[str, str]:
    if any(word in label for word in ("启发", "行动", "下一步", "验证", "支持")):
        return label or "选款启发", "positive"
    if any(word in label for word in ("反证", "限制", "边界", "风险", "未知")):
        return label or "注意边界", "warning"
    if any(word in label for word in ("解读", "判断", "推断")):
        return label or "分析判断", "info"
    return label or "要点", "info"


def point_items(value: str, label: str = "") -> list[dict]:
    """One source judgment becomes one numbered row, including its evidence and caveat."""
    raw = value.strip()
    content = plain(raw)
    if not content:
        return []
    marked = re.match(r"^\*\*([^*]{2,100})\*\*\s*(.*)$", raw, re.S)
    if marked:
        title = plain(marked.group(1)).rstrip("。:：")
        body = plain(marked.group(2))
    else:
        lead = re.match(r"^(.{8,46}?[，。！？；：])", content)
        if lead:
            title = lead.group(1).strip()
            body = content[len(lead.group(1)):].strip()
        else:
            title = label if label and not label.startswith("第") else "研究判断"
            body = content
    semantic = title if any(word in title for word in ("启发", "解读", "边界", "风险", "验证", "布局")) else label
    if not semantic or semantic.startswith("第"):
        semantic = "结论"
    badge, tone = point_tone(semantic)
    if len(badge) > 12:
        badge = "选款启发" if tone == "positive" else "研究判断"
    return [{"title": title, "text": body, "label": badge, "tone": tone,
             "source_chunk": content}]


def prose_block(value: str) -> dict:
    raw = value.strip()
    if len(plain(raw)) <= 65 and not raw.startswith("**"):
        return {"type": "text", "text": plain(raw)}
    return {"type": "actions", "items": point_items(raw)}


def merge_adjacent_actions(items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for item in items:
        if item["type"] == "actions" and merged and merged[-1]["type"] == "actions":
            merged[-1]["items"].extend(item["items"])
        else:
            merged.append(item)
    return merged


def md_blocks(markdown: str) -> list[dict]:
    """Keep the reviewed prose, lists and pipe tables in readable blocks."""
    lines = markdown.splitlines()
    blocks: list[dict] = []
    paragraph: list[str] = []
    bullet: list[str] = []
    bullet_ordered: bool | None = None
    section_title: str | None = None
    section_blocks: list[dict] = []

    def add(block: dict) -> None:
        (section_blocks if section_title else blocks).append(block)

    def flush_paragraph() -> None:
        if paragraph:
            add(prose_block(" ".join(paragraph)))
            paragraph.clear()

    def flush_bullet() -> None:
        nonlocal bullet_ordered
        if bullet:
            if bullet_ordered or any(len(plain(item)) > 65 for item in bullet):
                rows = []
                for index, item in enumerate(bullet, 1):
                    rows.extend(point_items(item, "结论"))
                add({"type": "actions", "items": rows})
            else:
                add({"type": "list", "ordered": bool(bullet_ordered), "items": [plain(item) for item in bullet]})
            bullet.clear()
        bullet_ordered = None

    def flush_section() -> None:
        nonlocal section_title, section_blocks
        flush_paragraph()
        flush_bullet()
        if section_title:
            blocks.append({"type": "card", "title": section_title, "blocks": merge_adjacent_actions(section_blocks)})
        section_title, section_blocks = None, []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("# "):
            flush_section()
            i += 1
            continue
        if line.startswith("## ") or line.startswith("### "):
            flush_section()
            section_title = plain(line.lstrip("# "))
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"[|:\-\s]+", lines[i + 1].strip()):
            flush_paragraph()
            flush_bullet()
            heads = [plain(cell) for cell in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [plain(cell) for cell in lines[i].strip().strip("|").split("|")]
                rows.append({f"c{j}": cells[j] if j < len(cells) else "" for j in range(len(heads))})
                i += 1
            add(table("数据对照", [(f"c{j}", h) for j, h in enumerate(heads)], rows))
            continue
        bullet_match = re.match(r"^(\d+\.|[-*])\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            ordered = bullet_match.group(1).endswith(".")
            if bullet and ordered != bullet_ordered:
                flush_bullet()
            bullet_ordered = ordered
            bullet.append(bullet_match.group(2))
            i += 1
            continue
        if not line:
            flush_paragraph()
            flush_bullet()
        else:
            if bullet:
                bullet[-1] += " " + line
            else:
                paragraph.append(line)
        i += 1
    flush_section()
    return merge_adjacent_actions(blocks)


def conclusion(items: list[tuple[str, str, str, str]]) -> dict:
    return {"type": "conclusion", "title": "先看结论", "items": [
        {"label": label, "tone": tone, "segments": [
            {"text": lead, "emphasis": "strong", "tone": tone},
            {"text": rest, "emphasis": "italic" if tone == "warning" else "normal"},
        ]}
        for label, lead, rest, tone in items
    ]}


def rounded(value, digits=1):
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        formatted = f"{value:,.{digits}f}"
        return formatted.rstrip("0").rstrip(".") if digits > 0 else formatted
    return str(value)


def bound_interpretation(text: str, marker: str, source_sha256: str) -> str:
    match = re.match(rf"\A<!-- {re.escape(marker)}: ([0-9a-f]{{64}}) -->\s*\n", text)
    if not match or match.group(1) != source_sha256:
        raise ValueError(f"interpretation is not bound to the current {marker}")
    return text[match.end():].lstrip("\n")


def check_report_bindings(loaded: dict, srcs: dict) -> None:
    visual_files = loaded["visual"]
    decision_files = loaded["decision"]
    for role in ("summary", "labels", "prototypes"):
        if role not in visual_files:
            raise ValueError(f"report requires visual.{role} from the current prototype classification")
    for role in ("evidence", "cards"):
        if role not in decision_files:
            raise ValueError(f"report requires decision.{role}")
    evidence = decision_files["evidence"]
    cards_doc = decision_files["cards"]
    prototype_source = evidence.get("sources", {}).get("prototype_labels", {})
    if prototype_source.get("sha256") != srcs["visual"]["labels"]["sha256"]:
        raise ValueError("report prototype labels do not match comparison evidence")
    if cards_doc.get("schema_version") != 2 or cards_doc.get("source_evidence_sha256") != srcs["decision"]["evidence"]["sha256"]:
        raise ValueError("report opportunity cards are not bound to current comparison evidence")
    candidates = {candidate["candidate_id"]: candidate for candidate in evidence["candidates"]}
    if not cards_doc.get("cards"):
        raise ValueError("report has no opportunity cards")
    for card in cards_doc["cards"]:
        candidate = candidates.get(card.get("candidate_id"))
        if not candidate or candidate.get("axis") != "product_style":
            raise ValueError("report opportunity card must reference a whole-product style prototype")

    labels = visual_files["labels"]
    prototypes = visual_files["prototypes"]
    if not labels or not prototypes:
        raise ValueError("report requires complete product-style labels and prototypes")
    label_by_id = {str(row["product_id"]): row for row in labels}
    if len(label_by_id) != len(labels):
        raise ValueError("duplicate product-style label ID")
    products = {str(row["product_id"]): row for row in evidence["products"]}
    observed_ids = {pid for pid, row in products.items() if row["visual_status"] != "not_observed"}
    if set(label_by_id) != observed_ids:
        raise ValueError("product-style label coverage disagrees with observed products")
    prototype_ids = [row["style_id"] for row in prototypes]
    if len(prototype_ids) != len(set(prototype_ids)):
        raise ValueError("duplicate product-style prototype ID")
    prototype_names = [row["name"] for row in prototypes]
    if len(prototype_names) != len(set(prototype_names)) or set(prototype_names) & {"边界／待确认", "未识图"}:
        raise ValueError("duplicate or reserved product-style prototype name")
    groups = {style_id: set() for style_id in prototype_ids}
    for pid, label in label_by_id.items():
        if label["style_ids"] != products[pid]["product_style_ids"] or label.get("boundary_reason") != products[pid].get("product_style_boundary"):
            raise ValueError(f"report product-style assignment disagrees for {pid}")
        for style_id in label["style_ids"]:
            if style_id not in groups:
                raise ValueError(f"unknown product-style prototype: {style_id}")
            groups[style_id].add(pid)
    for prototype in prototypes:
        actual = groups[prototype["style_id"]]
        if actual != set(map(str, prototype["product_ids"])) or len(actual) != prototype["product_count"]:
            raise ValueError(f"prototype summary membership disagrees: {prototype['style_id']}")
    if "interpretation" in visual_files:
        visual_files["interpretation"] = bound_interpretation(
            visual_files["interpretation"], "source_prototype_summary_sha256",
            srcs["visual"]["prototypes"]["sha256"])
    if "interpretation" in decision_files:
        decision_files["interpretation"] = bound_interpretation(
            decision_files["interpretation"], "source_evidence_sha256",
            srcs["decision"]["evidence"]["sha256"])


def build(manifest_path: Path, output_path: Path) -> None:
    manifest = read_json(manifest_path)
    required = ["advertising", "title", "geography", "price", "visual", "decision"]
    for key in required:
        if key not in manifest["modules"]:
            raise ValueError(f"missing module: {key}")
    loaded: dict[str, dict] = {}
    srcs: dict[str, dict] = {}
    for key, files in manifest["modules"].items():
        loaded[key], srcs[key] = {}, {}
        for role, value in files.items():
            path = source_path(manifest_path, value)
            loaded[key][role] = path.read_text(encoding="utf-8") if path.suffix == ".md" else read_json(path)
            srcs[key][role] = {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    check_report_bindings(loaded, srcs)

    ad = loaded["advertising"]["detail"]
    roots = loaded["title"]["summary"]
    geo = loaded["geography"]["summary"]
    price = loaded["price"]["summary"]
    visual = loaded["visual"]["summary"]
    prototypes = loaded["visual"]["prototypes"]
    evidence = loaded["decision"]["evidence"]
    cards = loaded["decision"]["cards"]["cards"]
    pop = evidence["population"]
    products = evidence["products"]
    candidates = evidence["candidates"]
    sample = manifest.get("sample", {})
    if len(products) != pop["natural_products"]:
        raise ValueError("natural product population mismatch")
    if ad["counts"]["natural_products"] != len(products):
        raise ValueError("advertising natural population mismatch")
    if sum(b["product_count"] for b in price["bands"]) != len(products):
        raise ValueError("price-band population mismatch")
    if visual["scope"]["selected"] != len(products):
        raise ValueError("visual population mismatch")
    if visual["scope"]["ready"] != visual["reviewed_products"] or pop["visual_observed"] != visual["reviewed_products"]:
        raise ValueError("ready-image observation coverage mismatch")
    if visual["scope"]["image_unavailable"] != pop["visual_not_observed"]:
        raise ValueError("unobserved products must match unavailable images")
    unavailable_reasons = visual.get("image_unavailable_by_reason", {})
    if sum(unavailable_reasons.values()) != pop["visual_not_observed"]:
        raise ValueError("unavailable-image reasons do not reconcile")
    if set(unavailable_reasons) - {"too_large"}:
        raise ValueError("non-size image failures require resolution before the full report")
    if len({p["product_id"] for p in products}) != len(products):
        raise ValueError("duplicate natural product ID")
    expected_workbook_hash = manifest.get("cleaned_workbook_sha256")
    if expected_workbook_hash and evidence["cleaned_workbook_sha256"] != expected_workbook_hash:
        raise ValueError("evidence workbook hash mismatch")
    if manifest.get("cleaned_workbook"):
        workbook_path = source_path(manifest_path, manifest["cleaned_workbook"])
        workbook_hash = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
        if workbook_hash != evidence["cleaned_workbook_sha256"]:
            raise ValueError("cleaned workbook file hash mismatch")
        product_links = read_product_links(workbook_path)
        srcs["input"] = {"cleaned_workbook": {"name": workbook_path.name, "sha256": workbook_hash}}
    else:
        product_links = {p["product_id"]: p["item_url"] for p in products if p.get("item_url")}
    if set(product_links) != {p["product_id"] for p in products}:
        raise ValueError("product-link coverage mismatch; provide cleaned_workbook in report manifest")

    candidate_by_id = {c["candidate_id"]: c for c in candidates}
    product_by_id = {p["product_id"]: p for p in products}
    for card in cards:
        if card["candidate_id"] not in candidate_by_id:
            raise ValueError(f"unresolved candidate: {card['candidate_id']}")

    views: list[dict] = []

    def view(id_: str, label: str, title: str, subtitle: str, blocks: list[dict]) -> None:
        views.append({"id": id_, "label": label, "title": title, "subtitle": subtitle, "blocks": blocks})

    card_sorted = sorted(cards, key=lambda c: c.get("research_order", {}).get("position", 999))
    intro = conclusion([
        ("先研究什么", plain(card_sorted[0]["definition"].split("：")[0]), "。先做同配置、评价和店铺因素核验。", "positive"),
        ("如何理解顺序", "这是核验顺序，", "不是入场排名；每张卡并列展示支持、反证和改变判断的条件。", "info"),
        ("最重要的边界", "付款人数统计周期未知，", "搜索快照不提供市场增长、利润或广告花费。", "warning"),
    ])
    overview_rows = []
    for card in card_sorted:
        group = candidate_by_id[card["candidate_id"]]
        overview_rows.append({
            "order": card["research_order"]["position"],
            "proposal": card["definition"].split("：")[0],
            "products": group["product_count"],
            "shops": group["shop_count"],
            "payment": rounded(group["displayed_payment_people"]["median_per_product"]),
            "price": rounded(group["displayed_price_yuan"]["median"], 2),
            "why": card["research_order"]["reason"],
            "candidate": card["candidate_id"],
        })
    view("overview", "一页读懂", manifest["title"], "从搜索样本走向值得核验的商品方案", [
        intro,
        {"type": "metrics", "columns": 4, "items": [
            {"label": "自然位唯一商品", "value": str(pop["natural_products"])},
            {"label": "广告位出现", "value": str(pop["advertising_appearances"])},
            {"label": "视觉已打标", "value": str(pop["visual_tagged"])},
            {"label": "视觉待确认", "value": str(pop["visual_uncertain"]), "tone": "warning"},
        ]},
        table("首批研究方案", [("order", "顺序"), ("proposal", "商品方案"), ("products", "商品"), ("shops", "店铺"), ("payment", "展示付款人数中位数"), ("price", "展示价格中位数/元"), ("why", "为何先查"), ("candidate", "证据组ID")], overview_rows),
        {"type": "actions", "items": [
            {"title": "读市场结构", "text": "广告、标题、地址、价格和视觉章节保留各阶段完整解读与证据。", "label": "分析", "tone": "info"},
            {"title": "查具体方案", "text": "每张机会判断卡都有支持、反证、代表商品及改变判断的下一步。", "label": "判断", "tone": "positive"},
            {"title": "回到商品明细", "text": "全量自然位数据与候选组合供按ID核对；独立JSON保存更细证据。", "label": "追溯", "tone": "warning"},
        ]},
    ])

    view("sample", "样本与清洗", "样本与口径", "自然位与广告位在不同统计粒度上分析", [
        conclusion([
            ("自然位", f"{pop['natural_products']:,} 个唯一商品 ID。", "同 ID 按源表顺序保留首条。", "info"),
            ("广告位", f"{pop['advertising_appearances']:,} 条出现记录、{pop['advertising_unique_products']:,} 个商品 ID。", "重复出现保留，用于研究谁在广告位露出。", "warning"),
        ]),
        {"type": "text", "paragraphs": [
            (f"源表 {sample['source_rows']:,} 行；自然位原始 {sample['natural_before_dedup']:,} 行，"
             f"去重排除 {sample['natural_deduplicated_out']:,} 行；广告位 {pop['advertising_appearances']:,} 行。自然位与广告位分开统计。")
            if {"source_rows", "natural_before_dedup", "natural_deduplicated_out"} <= sample.keys()
            else f"自然位唯一商品 {pop['natural_products']:,} 件；广告位出现 {pop['advertising_appearances']:,} 条，按各自粒度统计。",
            "自然位付款人数仅是列表展示值，统计期未知；广告位出现次数不是曝光量、投放成本或转化。图片标签来自本次视觉观察，任务标签代表可见使用线索而非真实买家画像。",
            f"清洗工作簿 SHA-256：{evidence['cleaned_workbook_sha256']}。分析中所有自然位产品按这份清洗结果和唯一商品 ID 对齐。",
        ]},
    ])

    ad_shops = [{
        "shop": s["shop_name"], "ad_products": s["ad_product_count"], "appearances": s["ad_appearance_count"],
        "natural_products": s["natural_product_count_by_exact_shop_name"],
        "ad_payment": rounded(s["natural_advertised_product_payment_people_sum_by_same_shop_name"], 0),
        "nonad_payment": rounded(s["natural_unadvertised_product_payment_people_sum_by_same_shop_name"], 0),
        "ad_only": s["ad_only_products"],
    } for s in ad["advertiser_shops"]]
    ad_products = [{
        "id": x["product_id"], "shop": x["shop_name"], "title": x["title"],
        "price": rounded(x["ad_price_first_appearance"], 2), "appearances": x["ad_appearances"],
        "natural_payment": rounded(x["natural_payment_people"], 0),
        "in_natural": "是" if x["in_natural"] else "否/未知付款",
    } for x in ad["ad_products"]]
    view("advertising", "广告与店铺", "谁在广告位出现", "案例解读与商品布局证据", [
        conclusion([
            ("店铺策略不一", "广告商品与自然位强品的关系不同。", "需逐店看商品线，而非用广告频次挑款。", "positive"),
            ("广告口径", "出现次数不等于花费。", "广告商品缺少自然位记录时，付款情况是未知。", "warning"),
        ]),
        *md_blocks(loaded["advertising"]["interpretation"]),
        table("全部广告店铺布局", [("shop", "店铺"), ("ad_products", "广告商品ID"), ("appearances", "出现次数"), ("natural_products", "自然位商品"), ("ad_payment", "同店广告商品可见付款之和"), ("nonad_payment", "同店非广告商品可见付款之和"), ("ad_only", "仅广告位商品")], ad_shops),
        table("广告商品明细", [("id", "商品ID"), ("shop", "店铺"), ("title", "标题"), ("price", "广告现价/元"), ("appearances", "出现次数"), ("natural_payment", "自然位展示付款"), ("in_natural", "同ID见于自然位")], ad_products),
    ])

    root_rows = [{"root": r["root"], "facet": r["facet"], "products": r["product_count"],
                  "shops": r["shop_count"], "price": rounded(r["price_median"], 2),
                  "payment": rounded(r["payment_people_median"], 0), "high": r["high_payment_product_count"]}
                 for r in roots["roots"]]
    shop_rows = [{"shop": s["shop_name"], "products": s["natural_product_count"],
                  "payment_sum": rounded(s["displayed_payment_people_sum_across_visible_products"], 0),
                  "distinctive_roots": "、".join(x["root"] for x in s["top_distinctive_roots"][:5])}
                 for s in roots["shops"]]
    top_root = max(roots["roots"], key=lambda r: r["product_count"])
    view("title_roots", "标题与词根", "标题说了什么", "商家表达的词根结构和店铺布局", [
        conclusion([
            ("高覆盖词根", f"“{top_root['root']}”覆盖 {top_root['product_count']:,} 件商品。", "高频表述需与实物形态及店铺分布一起判断。", "info"),
            ("核验边界", "标题词是商家表述。", "材料、功效和真实商品形态须结合图片、详情与实物证据。", "warning"),
        ]),
        *md_blocks(loaded["title"]["interpretation"]),
        table("全部标题词根", [("root", "词根"), ("facet", "属性"), ("products", "商品数"), ("shops", "店铺数"), ("price", "价格中位数/元"), ("payment", "展示付款中位数"), ("high", "高付款商品数")], root_rows),
        table("店铺词根布局", [("shop", "店铺"), ("products", "自然位商品"), ("payment_sum", "展示付款之和"), ("distinctive_roots", "突出词根")], shop_rows),
    ])

    city_rows = [{"region": r["region"], "products": r["product_count"], "shops": r["shop_count"],
                  "price": rounded(r["price_median"], 2), "payment": rounded(r["payment_people_median"], 0),
                  "high": r["high_payment_product_count"], "top_share": f"{100*r['top_shop_product_share']:.1f}%"}
                 for r in geo["city_regions"]]
    focus_set = {tuple(pair) for pair in manifest.get("focus_region_roots", [])}
    focus_rows = [{"region": r["region"], "root": r["root"], "products": r["product_count"],
                   "shops": r["shop_count"], "price": rounded(r["price_median"], 2),
                   "payment": rounded(r["payment_people_median"], 0), "high": r["high_payment_product_count"],
                   "relative": rounded(r["location_quotient"], 2)}
                  for r in geo["root_regions"] if (r["region"], r["root"]) in focus_set]
    view("geography", "地址与区域", "列表地址的区域结构", "观察商家和商品聚集，不推定工厂所在地", [
        conclusion([
            ("地区分布", f"样本出现 {len(geo['city_regions'])} 个列表地址值。", "可作为后续商家和商品群核验线索。", "info"),
            ("地址边界", "列表地址不等于工厂所在地。", "供应链结论仍需独立核验。", "warning"),
        ]),
        *md_blocks(loaded["geography"]["interpretation"]),
        table("全部地址区域", [("region", "列表地址"), ("products", "商品数"), ("shops", "店铺数"), ("price", "价格中位数/元"), ("payment", "展示付款中位数"), ("high", "高付款商品"), ("top_share", "最大店商品占比")], city_rows),
        *( [table("文中重点地区 × 词根证据", [("region", "地址"), ("root", "标题词根"), ("products", "商品数"), ("shops", "店铺数"), ("price", "价格中位数/元"), ("payment", "展示付款中位数"), ("high", "高付款商品"), ("relative", "相对覆盖倍数")], focus_rows)] if focus_rows else [] ),
    ])

    band_rows = []
    for b in price["bands"]:
        interval = f"{b['lower_inclusive']:.2f}—{'<'+format(b['upper_exclusive'], '.2f') if b['upper_exclusive'] is not None else format(b['price_max'], '.2f')}"
        band_rows.append({"band": b["band"], "range": interval, "products": b["product_count"],
                          "share": f"{100*b['product_share']:.1f}%", "shops": b["shop_count"],
                          "payment": rounded(b["payment_people_median"], 0), "ads": b["ad_appearance_count"],
                          "ad_ids": b["ad_unique_product_count"]})
    largest_band = max(price["bands"], key=lambda b: b["product_count"])
    ad_band = max(price["bands"], key=lambda b: b["ad_appearance_count"])
    def band_range(b):
        return f"{b['lower_inclusive']:.2f}—{b['upper_exclusive']:.2f} 元" if b["upper_exclusive"] is not None else f"{b['lower_inclusive']:.2f} 元及以上"
    view("price", "价格带", f"本样本的 {len(price['bands'])} 个价格群", "边界来自样本拟合，不是预设固定区间", [
        conclusion([
            ("供给中心", f"{band_range(largest_band)}有 {largest_band['product_count']} 件商品。", "这是样本中商品最多的一档，不等于进入建议。", "info"),
            ("广告集中", f"{band_range(ad_band)}出现 {ad_band['ad_appearance_count']} 次广告位。", "出现次数不能推算预算或投放效率。", "warning"),
        ]),
        *md_blocks(loaded["price"]["interpretation"]),
        table("样本自然价格带", [("band", "档"), ("range", "展示现价/元"), ("products", "自然位商品"), ("share", "占比"), ("shops", "店铺"), ("payment", "展示付款中位数"), ("ads", "广告出现"), ("ad_ids", "广告商品ID")], band_rows),
    ])

    # This is an evidence-review order, not a predicted profit or entry score.
    payment_values = sorted(max(0.0, float(p.get("payment_people_displayed") or 0)) for p in products)
    p99 = payment_values[min(len(payment_values) - 1, math.ceil(len(payment_values) * 0.99) - 1)]
    payment_scale = math.log1p(p99) if p99 > 0 else 1.0
    band_counts = Counter(p.get("price_band") for p in products)
    largest_band_count = max(band_counts.values())

    def research_score(product: dict) -> float:
        payment = max(0.0, float(product.get("payment_people_displayed") or 0))
        payment_part = min(1.0, math.log1p(payment) / payment_scale)
        band_part = band_counts[product.get("price_band")] / largest_band_count
        visual_part = 1.0 if product.get("product_style_ids") else 0.0
        return round(60 * payment_part + 25 * band_part + 15 * visual_part, 1)

    axes = visual["axes"]
    top_forms = [(item["name"], item["product_count"]) for item in sorted(prototypes, key=lambda x: -x["product_count"])[:2]]
    axis_blocks = []
    for key, title in [("form", "产品主形态"), ("style", "产品风格"), ("audience", "可见使用任务")]:
        rows = [{"label": label, "products": count, "examples": "、".join(axes[key]["examples"].get(label, []))}
                for label, count in axes[key]["canonical_counts"].items()]
        axis_blocks.append(table(title, [("label", "标签"), ("products", "商品数"), ("examples", "代表商品ID")], rows))
    variant_rows = [{"family": item["family"], "variant": item["variant"], "products": item["products"]}
                    for item in axes["form"].get("variant_counts", [])]
    if variant_rows:
        axis_blocks.insert(1, table("主形态下的子形态与配置", [("family", "主形态"), ("variant", "子形态／配置"),
                                                    ("products", "商品数")], variant_rows))
    form_groups: dict[str, list[dict]] = {}
    for prototype in prototypes:
        ids = prototype["product_ids"]
        if len(ids) != prototype["product_count"] or any(pid not in product_by_id for pid in ids):
            raise ValueError(f"invalid product-style members: {prototype['style_id']}")
        form_groups[prototype["name"]] = [product_by_id[pid] for pid in ids]
    boundary = [product for product in products if product.get("product_style_boundary")]
    unavailable = [product for product in products if product.get("visual_status") == "not_observed"]
    if boundary:
        form_groups["边界／待确认"] = boundary
    if unavailable:
        form_groups["未识图"] = unavailable
    if {p["product_id"] for members in form_groups.values() for p in members} != set(product_by_id):
        raise ValueError("product-style gallery does not cover natural products")
    prototype_by_name = {prototype["name"]: prototype for prototype in prototypes}
    form_tabs = []
    for index, (form, members) in enumerate(sorted(form_groups.items(), key=lambda pair: (-len(pair[1]), pair[0])), 1):
        gallery_items = []
        for product in members:
            score = research_score(product)
            gallery_items.append({
                "image_url": product.get("image_url"), "alt": product["title"],
                "item_url": product_links[product["product_id"]],
                "title": product["title"], "price": f"¥{rounded(product.get('price_yuan'), 2)}",
                "badge": f"研究优先分 {score:.1f}", "tone": "info" if product.get("product_style_ids") else "warning",
                "copy_value": product["product_id"], "copy_label": "复制商品ID",
                "facts": [
                    {"label": "商品ID", "value": product["product_id"]},
                    {"label": "展示付款人数", "value": rounded(product.get("payment_people_displayed"), 0)},
                    {"label": "店铺", "value": product.get("shop_name") or "—"},
                    {"label": "产品款式 / 子形态",
                     "value": f"{form} / {product.get('form_variant') or '未细分'}"},
                    {"label": "风格 / 配置", "value": f"{product.get('style') or '待确认'} / {'、'.join(product.get('form_features') or []) or '—'}"},
                    {"label": "可见使用任务", "value": product.get("task_audience") or "未见明确任务"},
                    {"label": "价格档 / 列表地址", "value": f"{product.get('price_band') or '—'} / {product.get('listing_address') or '—'}"},
                    {"label": "视觉状态", "value": visual_state(product.get("visual_status"))},
                ],
                "evidence": product.get("visible_evidence") or ("原图超过读取上限，未作视觉判断" if product.get("visual_status") == "not_observed" else "视觉证据待确认"),
                "sort_values": {"price": product.get("price_yuan"),
                                "payment": product.get("payment_people_displayed"), "score": score},
            })
        prototype = prototype_by_name.get(form)
        group_explanation = (
            f"{form}：{prototype['definition']}。选款差异：{prototype['selection_difference']}。"
            f"分类边界：{prototype['boundary']}。" if prototype else f"{form}：保留单独审阅的边界商品。"
        )
        form_tabs.append({"id": f"form-{index}", "label": form, "badge": str(len(members)), "blocks": [
            {"type": "callout", "text": f"{group_explanation}本组 {len(members)} 件自然位商品；同图多款时菜单可能重叠。每页 50 件。"},
            {"type": "products", "columns": 3, "page_size": 50,
             "sort_options": [
                 {"key": "score", "label": "研究优先分：高到低", "direction": "desc"},
                 {"key": "payment", "label": "展示付款人数：高到低", "direction": "desc"},
                 {"key": "payment", "label": "展示付款人数：低到高", "direction": "asc"},
                 {"key": "price", "label": "现价：低到高", "direction": "asc"},
                 {"key": "price", "label": "现价：高到低", "direction": "desc"},
             ], "items": gallery_items},
        ]})
    view("visual", "商品形态", "图片显示了哪些商品方案", "完整产品款式原型，加上结构、风格与可见使用任务", [
        conclusion([
            ("形态结构", "、".join(f"{name} {count} 件" for name, count in top_forms) + "。", "同一搜索词下存在多种实物形态。", "info"),
            ("分类边界", f"{pop['visual_product_style_classified']:,} 件进入产品款式原型，{pop['visual_observed'] - pop['visual_product_style_classified']:,} 件为边界样本，{pop['visual_not_observed']:,} 件未识图。", "款式归属可以重叠；未识图商品不参与视觉形态聚合。", "warning"),
        ]),
        *[prose_block(value) for value in [
            (f"本章以完整实物款式原型组织图片：{len(prototypes)} 个原型，"
             f"{pop['visual_product_style_classified']:,} 件可读商品获得款式归属；"
             f"{pop['visual_observed'] - pop['visual_product_style_classified']:,} 件为边界样本，"
             f"{pop['visual_not_observed']:,} 件未识图。"),
            "每个款式代表一种可独立比较和开发的实物方案；主形态、局部配置、风格与可见使用任务保留为辅助证据。一个商品可展示多种实物，款式组数量不能相加。",
            "分类只描述图片可见的供给形态。是否值得白牌深入研究，需要继续核查展示付款、价格、店铺布局与广告证据；材质、真实人群和利润仍待独立验证。",
        ]],
        *(md_blocks(loaded["visual"]["interpretation"]) if "interpretation" in loaded["visual"] else [
            {"type": "alert", "tone": "warning", "title": "解读状态", "text": "本次全量视觉阶段只有标签汇总，以上文字是依据汇总所作的报告解读，尚未作为独立阶段结论审核。"}
        ]),
        *axis_blocks,
        {"type": "card", "title": "商品级研究优先分：公式与边界", "blocks": [
            {"type": "actions", "items": [
                {"title": "评分公式", "text": "研究优先分 = 60 × min[1, ln(1+该商品展示付款人数) / ln(1+样本付款人数P99)] + 25 × (该商品价格档自然位商品数 / 样本最大价格档商品数) + 15 × 款式归属明确性（已归属=1，边界/未识图=0）。结果保留 1 位小数。", "label": "可复算", "tone": "info"},
                {"title": "分数含义", "text": "高分表示当前搜索快照中有更多可观察的付款记录、所在价格档有更多可比商品、图片分类更明确，因此适合优先查看和核验。它不等于产品潜力、利润率或白牌可进入性。", "label": "研究顺序", "tone": "positive"},
                {"title": "使用边界", "text": "展示付款人数的统计周期未知；价格档商品多代表可见供给多，不证明需求更大；视觉明确性只衡量分类证据。评分没有纳入真实销量、利润、竞争成本、评价与供应链，跨搜索词或跨期不可直接比较。", "label": "注意边界", "tone": "warning"},
            ]},
            {"type": "text", "text": f"本样本付款人数 P99={rounded(p99, 0)}；最大价格档有 {largest_band_count} 件自然位商品。"},
        ]},
        {"type": "tabs", "title": "全量视觉商品图库｜按产品款式查看", "tabs": form_tabs},
    ])

    group_rows = []
    for c in candidates:
        labels = c["labels"]
        group_rows.append({
            "id": c["candidate_id"], "grain": c["axis"],
            "prototype": next((p["name"] for p in prototypes if p["style_id"] == labels.get("product_style_id")), "—"),
            "form": labels.get("form", "—"),
            "variant": labels.get("variant", "—"),
            "style": labels.get("style", "—"), "task": labels.get("task_audience", labels.get("audience", "—")),
            "products": c["product_count"], "shops": c["shop_count"],
            "payment": rounded(c["displayed_payment_people"]["median_per_product"], 0),
            "price": rounded(c["displayed_price_yuan"]["median"], 2),
            "ad": c["natural_advertised_product_count_same_shop"],
        })
    view("candidates", "组合对比", "把前面证据合到同一商品方案", f"{len(candidates)} 个可见候选组合，分层归类且彼此可能重叠", [
        conclusion([
            ("比较单位", "先比较完整产品款式原型，再看相近结构、配置与使用任务。", "价格、店铺和广告因素会改变表面上的付款差异。", "info"),
            ("组合口径", "产品款式与辅助维度可能互相重叠。", "这些行不能相加为一个市场总量。", "warning"),
        ]),
        table("全部候选组合", [("id", "证据组ID"), ("grain", "组合层级"), ("prototype", "产品款式原型"), ("form", "主形态"), ("variant", "子形态／配置"), ("style", "风格"), ("task", "使用任务"), ("products", "商品"), ("shops", "店铺"), ("payment", "展示付款中位数"), ("price", "价格中位数/元"), ("ad", "同店广告重合商品")], group_rows),
    ])

    assets = {}
    tabs = []
    for card in card_sorted:
        group = candidate_by_id[card["candidate_id"]]
        tab_blocks: list[dict] = [
            {"type": "callout", "text": card["definition"]},
            {"type": "metrics", "columns": 4, "items": [
                {"label": "自然位商品", "value": str(group["product_count"])},
                {"label": "店铺", "value": str(group["shop_count"])},
                {"label": "展示付款中位数", "value": rounded(group["displayed_payment_people"]["median_per_product"], 0)},
                {"label": "展示价格中位数/元", "value": rounded(group["displayed_price_yuan"]["median"], 2)},
            ]},
            {"type": "card", "title": "当前解读", "blocks": [prose_block(card["interpretation"])]},
            prose_block(card["scope"]),
            prose_block("父组/可比组：" + card["parent_comparison"]),
        ]
        for key, title, tone in [("observations", "观察到的数据", "info"),
                                 ("supporting_evidence", "支持继续研究", "positive"),
                                 ("counterevidence", "反证与其他解释", "warning")]:
            rows = []
            reference_rows = []
            for claim_index, item in enumerate(card[key], 1):
                label = f"{title} {claim_index}"
                for row in point_items(item["claim"], title):
                    row["label"] = label
                    row["tone"] = tone
                    rows.append(row)
                reference_rows.append({"claim": label, "refs": "、".join(item["refs"])})
            tab_blocks.append({"type": "card", "title": title, "blocks": [
                {"type": "actions", "items": rows},
                table("对应证据字段与商品ID", [("claim", "主张"), ("refs", "可核对证据")], reference_rows),
            ]})
        tab_blocks.append({"type": "card", "title": "尚未知晓", "blocks": [{"type": "list", "items": card["unknowns"]}]})
        tab_blocks.append({"type": "actions", "items": [
            {"title": item["question"], "text": "改变判断的条件：" + item["changes_assessment_if"], "label": "下一步", "tone": "info"}
            for item in card["next_checks"]
        ]})
        band_counts = group.get("price_band_product_counts", {})
        if band_counts:
            tab_blocks.append(table("本方案的价格带分布", [("band", "价格档"), ("count", "自然位商品")],
                                    [{"band": str(band), "count": count} for band, count in sorted(band_counts.items(), key=lambda x: str(x[0]))]))
        shop_rows = []
        for shop in group.get("leading_shops", [])[:12]:
            shop_rows.append({
                "shop": shop["shop_name"], "candidate_products": shop["candidate_product_count"],
                "candidate_payment": rounded(shop["candidate_payment_people_sum_displayed"], 0),
                "natural_products": shop["natural_product_count_in_export"],
                "forms": "、".join(f"{name} {count}" for name, count in shop.get("natural_form_counts", {}).items()),
                "ad_products": shop.get("same_shop_ad_product_count", 0),
                "ad_appearances": shop.get("same_shop_ad_appearance_count", 0),
            })
        if shop_rows:
            tab_blocks.append(table("典型店铺的商品线与广告关联", [
                ("shop", "店铺"), ("candidate_products", "本方案商品"),
                ("candidate_payment", "本方案展示付款之和"), ("natural_products", "店内自然位商品"),
                ("forms", "店内形态布局"), ("ad_products", "同店广告商品ID"),
                ("ad_appearances", "广告位出现"),
            ], shop_rows))
        refs = [ref for field in ("observations", "supporting_evidence", "counterevidence")
                for item in card[field] for ref in item["refs"] if re.fullmatch(r"\d+", ref)]
        ids = list(dict.fromkeys(refs))
        if not ids:
            ids = group["product_ids"][:3]
        product_items = []
        for pid in ids[:5]:
            p = product_by_id.get(pid)
            if not p:
                continue
            asset_id = f"product-{pid}"
            image_path = Path(p.get("image_path") or "")
            if image_path.is_file():
                assets[asset_id] = {"path": str(image_path), "alt": p["title"], "role": "representative-product", "subject_id": pid, "evidence_level": "direct"}
            product_items.append({"asset_id": asset_id if asset_id in assets else None,
                                  "title": p["title"], "price": f"¥{rounded(p['price_yuan'], 2)}",
                                  "badge": p.get("shop_name", ""), "copy_value": pid, "copy_label": "复制商品ID",
                                  "facts": [{"label": "商品ID", "value": pid},
                                            {"label": "展示付款人数", "value": rounded(p.get("payment_people_displayed"), 0)}]})
        if product_items:
            tab_blocks.append({"type": "card", "title": "代表商品与证据ID", "blocks": [{"type": "products", "columns": 3, "items": product_items}]})
        tabs.append({"id": card["candidate_id"], "label": card["definition"].split("：")[0],
                     "badge": str(card["research_order"]["position"]), "blocks": tab_blocks})
    if "interpretation" in loaded["decision"]:
        tabs.append({"id": "narrative", "label": "完整文字结论", "blocks":
                     md_blocks(loaded["decision"]["interpretation"])})
    view("opportunities", "机会判断卡", "哪些方案值得继续拆解", "支持和反证并列，下一步用新证据改变判断", [
        {"type": "tabs", "title": "首批研究方案", "tabs": tabs},
    ])

    product_rows = [{
        "id": p["product_id"], "title": p["title"], "shop": p["shop_name"],
        "prototype": "、".join(proto["name"] for proto in prototypes if proto["style_id"] in p["product_style_ids"]) or "边界／未识图",
        "form": p.get("form") or "待确认", "variant": p.get("form_variant") or "—",
        "style": p.get("style") or "待确认",
        "task": p.get("task_audience") or "未见明确任务", "price": rounded(p.get("price_yuan"), 2),
        "band": p.get("price_band") or "—", "payment": rounded(p.get("payment_people_displayed"), 0),
        "address": p.get("listing_address") or "—", "ad": p.get("ad_appearances_same_shop", 0),
        "visual_status": p["visual_status"],
    } for p in products]
    view("evidence", "全量证据", "自然位商品与核验入口", "以下数据按商品ID唯一；页面搜索可定位商品、店铺及标签", [
        {"type": "alert", "tone": "warning", "title": "数据边界", "text": "展示付款人数统计期未知；展示价格不是经核实的实际SKU成交价；任务标签不证明买家身份。"},
        table("全部自然位商品", [("id", "商品ID"), ("title", "标题"), ("shop", "店铺"), ("prototype", "产品款式原型"),
                         ("form", "主形态"), ("variant", "子形态／配置"), ("style", "风格"), ("task", "可见任务"),
                         ("price", "现价/元"), ("band", "价格档"), ("payment", "展示付款人数"),
                         ("address", "列表地址"), ("ad", "同店广告出现"), ("visual_status", "视觉状态")], product_rows),
    ])

    source_rows = [{"module": key, "role": role, "name": info["name"], "sha256": info["sha256"]}
                   for key, roles in srcs.items() for role, info in roles.items()]
    view("method", "方法与边界", "怎样读这份报告", "样本、指标、源文件和未解问题", [
        conclusion([
            ("观察与判断", "商品、店铺和图片标签是样本证据。", "进入机会仍需评价、SKU、成本、供应商和利润核验。", "info"),
            ("当前状态", "这是一份搜索快照研究报告。", "结论随新证据修订，用户决定后续研究方向。", "warning"),
        ]),
        {"type": "list", "ordered": True, "items": [
            "广告位按出现记录与唯一商品ID分开计数；出现次数不是预算、曝光或转化。",
            "标题词根属于商家页面表述，可交叉但不可相加；材料真实性需要商品详情和实物复核。",
            "地址是搜索列表字段，不能直接当作工厂、仓库或产业带。",
            "价格带由当前样本现价经对数 Jenks 拟合，跨搜索词需重新计算。",
            f"视觉任务标签描述图片支持的器型/用途，不证明实际购买者。{pop['visual_uncertain']} 件边界商品不进入候选聚合。",
            "这是一张搜索结果快照，不提供市场增长、市场份额、真实利润或供应链能力。",
        ]},
        table("本报告来源校验", [("module", "模块"), ("role", "角色"), ("name", "文件"), ("sha256", "SHA-256")], source_rows),
    ])

    report = {
        "contract": "compact-workbench@1.0",
        "meta": {"title": manifest["title"], "subtitle": manifest["subject"],
                 "footer": ("开发模式审阅稿｜" if manifest.get("mode") == "development" else "研究报告｜")
                           + "结论用于决定进一步研究顺序，不构成入场或采购决定。",
                 "source_payload_sha256": evidence["cleaned_workbook_sha256"],
                 "artifact_binding": {
                     "prototype_labels_sha256": srcs["visual"]["labels"]["sha256"],
                     "prototype_summary_sha256": srcs["visual"]["prototypes"]["sha256"],
                     "comparison_evidence_sha256": srcs["decision"]["evidence"]["sha256"],
                     "opportunity_cards_sha256": srcs["decision"]["cards"]["sha256"],
                 },
                 "external_images": "allow_https"},
        "shell": {"brand_mark": "研", "brand_title": "搜索选品研究", "brand_subtitle": manifest["subject"],
                  "nav_label": "研究章节", "search": True, "search_placeholder": "搜索当前章节",
                  "date_range": manifest.get("date_label", "搜索结果快照"), "sidebar_tabs": True,
                  "reading_path": [{"view_id": id_, "label": label} for id_, label in [
                      ("overview", "结论"), ("advertising", "广告"), ("title_roots", "词根"),
                      ("geography", "地址"), ("price", "价格"), ("visual", "形态"),
                      ("candidates", "组合"), ("opportunities", "机会"), ("evidence", "证据")]]},
        "assets": assets,
        "views": views,
    }
    if output_path.exists():
        raise FileExistsError(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "views": len(views), "cards": len(cards),
                      "natural_products": len(products), "candidate_groups": len(candidates),
                      "source_artifacts": len(source_rows), "assets": len(assets)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.manifest, args.output)


if __name__ == "__main__":
    main()
