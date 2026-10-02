#!/usr/bin/env python3
"""Map three-axis visual evidence to the pinned workbench contract.

This script writes a ViewModel only; the bundled runtime owns HTML rendering and QA.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def title_count(label, count):
    return f"{label} · {count}件"


def build(args):
    detail = load(args.labels)
    summary = load(args.summary)
    plan = load(args.plan)
    if len(detail["records"]) != summary["reviewed_products"]:
        raise ValueError("detail and summary product counts disagree")
    products = detail["records"]
    subject = args.subject.strip() or "搜索商品"
    qa_note = args.qa_note.strip()
    uncertain_count = sum(p["status"] == "uncertain" for p in products)
    product_lookup = {p["product_id"]: p for p in products}
    manifest = load(plan["source_manifest"])
    source_lookup = {str(p["product_id"]): p for p in manifest["products"]}
    assets = {}
    for p in products:
        assets[f"p{p['product_id']}"] = {"path": p["image_path"], "alt": f"商品 {p['product_id']} 主图",
                                         "role": "source-product-image", "subject_id": p["product_id"],
                                         "evidence_level": "direct"}

    def product_card(p):
        form = p["form"]["label"] or "款式待确认"
        style = p["style"]["label"] or "风格未归类"
        audience = p["audience"]["label"] or "人群证据不足"
        source = source_lookup[p["product_id"]]
        evidence = p["visible_evidence"]
        if p["style"].get("physical_delta"):
            evidence += "｜风格落点：" + p["style"]["physical_delta"]
        if p["audience"].get("physical_delta"):
            evidence += "｜任务适配：" + p["audience"]["physical_delta"]
        return {"asset_id": f"p{p['product_id']}", "title": f"N{p['source_rank']} · {p['product_id']}",
                "price": f"¥{source.get('price', 0):.2f}" if source.get("price") is not None else "价格未给出",
                "badge": "边界待确认" if p["status"] == "uncertain" else "图片试打标",
                "tone": "warning" if p["status"] == "uncertain" else "info",
                "facts": [{"label": "款式", "value": form}, {"label": "风格", "value": style},
                          {"label": "人群/任务", "value": audience}],
                "evidence": evidence, "copy_value": p["product_id"], "copy_label": "复制商品ID"}

    def sample_cards(axis, group, maximum=3):
        return [product_card(p) for p in products if p[axis]["label"] == group][:maximum]

    def group_view(axis, label, title, subtitle):
        counts = summary["axes"][axis]["canonical_counts"]
        rows = [[name, str(count), "、".join(summary["axes"][axis]["examples"].get(name, []))]
                for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
        tabs = [{"id": f"{axis}-{i+1}", "label": name, "badge": str(count),
                 "blocks": [{"type": "products", "columns": 3, "items": sample_cards(axis, name)}]}
                for i, (name, count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])))]
        return {"id": axis, "label": label, "eyebrow": "三维打标", "title": title, "subtitle": subtitle,
                "blocks": [{"type": "alert", "tone": "info",
                            "text": f"本维度已归类 {sum(counts.values())} 件，未归类 {summary['axes'][axis]['unclassified_products']} 件；下方为各组代表图片。"},
                           {"type": "table", "title": "标签分布", "columns": ["标签", "件数", "代表商品ID"], "rows": rows},
                           {"type": "tabs", "title": "逐类看图", "tabs": tabs}]}

    audience_counts = summary["axes"]["audience"]["canonical_counts"]
    proposal_rows = []
    for name, count in sorted(audience_counts.items(), key=lambda item: (-item[1], item[0])):
        members = [p for p in products if p["audience"]["label"] == name]
        forms = Counter(p["form"]["label"] or "边界待定" for p in members)
        deltas = list(dict.fromkeys(p["audience"].get("physical_delta", "") for p in members))
        proposal_rows.append([name, str(count), "、".join(f"{form} {n}" for form, n in forms.most_common()),
                              "；".join(x for x in deltas[:2] if x)])
    many_styles = []
    by_form = defaultdict(Counter)
    for p in products:
        if p["form"]["label"] and p["style"]["label"]:
            by_form[p["form"]["label"]][p["style"]["label"]] += 1
    for form, styles in by_form.items():
        if len(styles) >= 2:
            many_styles.append([form, str(sum(styles.values())),
                                "、".join(f"{style} {count}" for style, count in styles.most_common())])

    model = {
        "contract": "compact-workbench@1.0",
        "meta": {"title": f"{subject}三维打标｜{len(products)}品审核版",
                 "subtitle": f"款式 × 产品风格 × 任务型人群；自然位{len(products)}个商品的开发模式样例",
                 "footer": "图片来自已提供的淘宝搜索导出；标签为待审核试打标，不代表全市场或实际购买人群。",
                 "source_payload_sha256": digest(args.labels)},
        "shell": {"brand_mark": "选", "brand_title": "商品形态审核", "brand_subtitle": "三维标签与可选货方案",
                  "nav_label": "审核路径", "search": True, "search_placeholder": "搜索当前页面的商品ID或标签",
                  "status": ["开发模式 · 待审核", f"{len(products)}件自然位商品", "结构/风格/任务三维"],
                  "sidebar_tabs": True,
                  "reading_path": [{"view_id": "overview", "label": "先看试打标边界"},
                                   {"view_id": "form", "label": "再看结构款式"},
                                   {"view_id": "style", "label": "比较产品风格"},
                                   {"view_id": "audience", "label": "核对人群任务"},
                                   {"view_id": "propositions", "label": "审视候选商品方案"},
                                   {"view_id": "all", "label": "逐品核对"}]},
        "assets": assets,
        "views": [
            {"id": "overview", "label": "结论与范围", "eyebrow": "待审核试跑", "title": "三维标签如何服务选款",
             "subtitle": "当前只验证打标和聚合逻辑，不宣布市场机会。",
             "blocks": [
                 {"type": "conclusion", "title": "先看三项判断", "items": [
                     {"label": "款式", "tone": "info", "segments": [{"text": "结构款式", "emphasis": "strong"}, {"text": "是基础分类；颜色不会单独拆出一个锅型。"}]},
                     {"label": "风格", "tone": "positive", "segments": [{"text": "同一结构款可以形成不同的产品风格方案", "emphasis": "strong", "tone": "positive"}],
                      "note": "风格必须对应锅体、手柄、表面等可见产品设计差异。"},
                     {"label": "人群", "tone": "warning", "segments": [{"text": "目标人群是使用任务假设", "emphasis": "strong"},
                          {"text": "，不是已验证的真实买家。", "emphasis": "italic", "tone": "warning"}],
                      "note": "证据不足的商品保留空标签。"}]},
                 {"type": "metrics", "columns": 4, "items": [
                     {"label": "商品图片", "value": str(len(products)), "note": f"占清洗自然位 {len(products)}/{plan['scope']['manifest_natural_total']}"},
                     {"label": "结构款式", "value": str(len(summary["axes"]["form"]["canonical_counts"])), "note": f"{uncertain_count}件目标边界待确认"},
                     {"label": "风格已归类", "value": str(sum(summary["axes"]["style"]["canonical_counts"].values())), "note": "其余保留未归类"},
                     {"label": "任务人群候选", "value": str(sum(audience_counts.values())), "note": "图片线索支持，仍需市场验证"}]},
                 {"type": "alert", "title": "样本口径", "tone": "warning",
                  "text": f"只选已清洗自然位的前{len(products)}个商品，并非随机抽样。品牌和排序可能造成偏斜；本页件数不是搜索市场份额。"},
                 {"type": "list", "title": "读这份报告的顺序", "ordered": True,
                  "items": ["先看每个维度的标签与代表图片，确认边界是否符合选款认知。",
                            "再看同一结构款的风格差异，以及针对任务的产品结构变化。",
                            "最后在逐品页核对全部50张图；有争议的标签回到原始观察，不直接修改聚合结果。"]}
             ]},
            group_view("form", "款式", "结构款式分类", f"主款式每商品最多一个；{uncertain_count}件目标范围待确认。"),
            group_view("style", "风格", "产品设计风格", "仅用产品本身的形状、色彩、表面和部件；促销画面风格不入类。"),
            group_view("audience", "人群", "目标任务人群候选", "标签指向使用任务及具体产品适配，不推断实际买家人口属性。"),
            {"id": "propositions", "label": "候选商品方案", "eyebrow": "三维交叉", "title": "标签怎样变成可做的货",
             "subtitle": "这些只是待研究的商品方案，不是投资、采购或入场建议。",
             "blocks": [
                 {"type": "alert", "tone": "info", "text": "下表只列样本中实际出现、且标注了产品侧变化的任务方向；稀少不等于有需求空缺。"},
                 {"type": "table", "title": "任务驱动的候选方案", "columns": ["任务人群", "样本件数", "基础款式", "实际产品变化"], "rows": proposal_rows},
                 {"type": "table", "title": "同款式的风格分化", "columns": ["基础款式", "有风格标签的件数", "可见风格"], "rows": many_styles},
                 {"type": "callout", "text": "下一步需按商品ID联接价格、付款人数、店铺及广告位，再判断哪些组合有真实市场信号；图片本身不能证明白牌机会。"}]},
            {"id": "all", "label": f"{len(products)}品逐项审核", "eyebrow": "完整证据", "title": "逐商品核对图片与标签",
             "subtitle": "按自然位源排序；每张卡同时显示款式、风格、人群任务与可见依据。",
             "blocks": [{"type": "alert", "tone": "warning", "text": qa_note or "识图次数、复核例外与并发能力以本次运行台账为准。"},
                        {"type": "products", "columns": 3, "items": [product_card(p) for p in products]}]},
            {"id": "method", "label": "口径与限制", "eyebrow": "方法", "title": "什么被标注，什么仍未知",
             "subtitle": "三维可并行选款，证据等级不同。",
             "blocks": [{"type": "list", "ordered": True,
                         "items": ["款式是可见几何与结构的分类；主款式每个目标商品最多一个。",
                                   "风格由至少两项产品本体线索支持，并写明可改变的产品设计部位。",
                                   "人群是使用任务假设；必须有任务线索和可落到商品上的适配点。",
                                   f"{uncertain_count}件目标边界待确认，等待上游目标范围决定是否纳入。",
                                   "图片字样属于商家主张，不等于性能已验证；付款人数亦有不明时间窗口。",
                                   "语义识图的实际并发量与重复阅读情况应按本次运行记录披露；不由图片下载并发推断。"]}]}
        ]}
    output = Path(args.output).resolve()
    with output.open("x", encoding="utf-8") as stream:
        json.dump(model, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"viewmodel": str(output), "views": len(model["views"]),
                      "assets": len(assets), "products": len(products)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--subject", default="搜索商品")
    parser.add_argument("--qa-note", default="")
    build(parser.parse_args())
