#!/usr/bin/env python3
"""Versioned Compact Commerce UI ViewModel renderer."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import pathlib
import re
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parent
CONTRACT = "compact-workbench@1.0"
CLI_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def slug(value: Any) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-")
    if not candidate:
        raise ValueError(f"Invalid empty identifier: {value!r}")
    return candidate


def mime_for(blob: bytes) -> str:
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"<svg") or b"<svg" in blob[:256]:
        return "image/svg+xml"
    raise ValueError("Unsupported image format; use JPEG, PNG, GIF, WebP, or SVG")


def normalize_assets(raw: Any, input_dir: pathlib.Path) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        items = [dict(value, id=key) for key, value in raw.items()]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("assets must be an object or array")
    result: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
            raise ValueError("each asset requires id and path")
        asset_id = str(item["id"])
        if asset_id in result:
            raise ValueError(f"duplicate asset id: {asset_id}")
        value = str(item["path"])
        if re.match(r"https?://", value, re.I):
            raise ValueError(f"remote rendering asset is forbidden: {asset_id}")
        path = pathlib.Path(value).expanduser()
        if not path.is_absolute():
            path = input_dir / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"asset not found: {asset_id} -> {path}")
        blob = path.read_bytes()
        mime = mime_for(blob)
        result[asset_id] = {
            "src": f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}",
            "alt": str(item.get("alt", "")),
            "role": str(item.get("role", "content")),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
    return result


class Renderer:
    def __init__(self, document: dict[str, Any], assets: dict[str, dict[str, str]]) -> None:
        self.document = document
        self.assets = assets
        self.external_images = str((document.get("meta") or {}).get("external_images", "forbid"))
        self.tab_counter = 0

    def render_blocks(self, blocks: Any) -> str:
        if blocks is None:
            return ""
        if not isinstance(blocks, list):
            raise ValueError("blocks must be an array")
        return "".join(self.render_block(block) for block in blocks)

    def render_block(self, block: Any) -> str:
        if not isinstance(block, dict):
            raise ValueError("every block must be an object")
        kind = block.get("type")
        if kind == "conclusion":
            return self.render_conclusion(block)
        if kind == "alert":
            tone = slug(block.get("tone", "warning"))
            title = f"<strong>{esc(block.get('title'))}</strong> " if block.get("title") else ""
            return f'<section class="alert tone-{tone} searchable">{title}<span>{esc(block.get("text", ""))}</span></section>'
        if kind == "metrics":
            columns = max(1, min(8, int(block.get("columns", 4))))
            variant = slug(block.get("variant", "default"))
            items = "".join(self.render_metric(item, variant) for item in block.get("items", []))
            return f'<section class="metrics metrics-{columns} variant-{variant}">{items}</section>'
        if kind == "grid":
            columns = max(1, min(4, int(block.get("columns", 2))))
            children = "".join(self.render_block(item) for item in block.get("items", []))
            return f'<section class="module-grid grid-{columns}">{children}</section>'
        if kind == "card":
            title = esc(block.get("title", ""))
            meta = esc(block.get("meta", ""))
            head = f'<div class="card-head"><h2>{title}</h2><span>{meta}</span></div>' if title or meta else ""
            body = self.render_blocks(block.get("blocks", []))
            extra = slug(block.get("variant", "default"))
            return f'<article class="card card-{extra} searchable">{head}<div class="card-body">{body}</div></article>'
        if kind == "list":
            ordered = bool(block.get("ordered"))
            tag = "ol" if ordered else "ul"
            items = "".join(f'<li class="searchable">{esc(item)}</li>' for item in block.get("items", []))
            return f'<{tag} class="content-list">{items}</{tag}>'
        if kind == "callout":
            return f'<div class="callout searchable">{esc(block.get("text", ""))}</div>'
        if kind == "text":
            values = block.get("paragraphs")
            if values is None:
                values = [block.get("text", "")]
            return '<div class="prose">' + "".join(f'<p class="searchable">{esc(value)}</p>' for value in values) + "</div>"
        if kind == "table":
            return self.render_table(block)
        if kind == "tabs":
            return self.render_tabs(block)
        if kind == "products":
            return self.render_products(block)
        if kind == "stats":
            items = "".join(f'<div class="mini-stat searchable"><span>{esc(x.get("label", ""))}</span><b>{esc(x.get("value", "—"))}</b></div>' for x in block.get("items", []))
            return f'<div class="mini-stats">{items}</div>'
        if kind == "badge":
            tone = slug(block.get("tone", "info"))
            return f'<span class="tag tone-{tone}">{esc(block.get("text", ""))}</span>'
        if kind == "button":
            label = esc(block.get("label", "打开"))
            if block.get("target_view"):
                return f'<button class="text-button" type="button" data-open-view="{esc(slug(block["target_view"]))}">{label}</button>'
            if block.get("url"):
                return f'<button class="text-button" type="button" data-url="{esc(block["url"])}">{label}</button>'
            raise ValueError("button requires target_view or url")
        if kind == "actions":
            rows = []
            for index, item in enumerate(block.get("items", []), 1):
                rows.append(f'<div class="action-row searchable"><span class="action-rank">{index}</span><div><b>{esc(item.get("title", ""))}</b><p>{esc(item.get("text", ""))}</p></div><span class="tag tone-{esc(slug(item.get("tone", "info")))}">{esc(item.get("label", ""))}</span></div>')
            return '<div class="action-list">' + "".join(rows) + "</div>"
        if kind == "empty":
            return f'<div class="empty">{esc(block.get("text", "暂无数据"))}</div>'
        raise ValueError(f"unsupported block type: {kind!r}")

    def render_conclusion(self, block: dict[str, Any]) -> str:
        items = block.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError("conclusion requires at least two structured items")
        valid_tones = {"info", "positive", "warning", "danger"}
        valid_emphasis = {"normal", "strong", "italic", "strong-italic"}
        cards = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"].strip():
                raise ValueError("each conclusion item requires a nonempty label")
            segments = item.get("segments")
            if not isinstance(segments, list) or not segments:
                raise ValueError("each conclusion item requires text segments")
            tone = item.get("tone", "info")
            if tone not in valid_tones:
                raise ValueError(f"unsupported conclusion tone: {tone!r}")
            rendered_segments = []
            for segment in segments:
                if not isinstance(segment, dict) or not isinstance(segment.get("text"), str) or not segment["text"]:
                    raise ValueError("each conclusion segment requires nonempty text")
                emphasis = segment.get("emphasis", "normal")
                segment_tone = segment.get("tone")
                if emphasis not in valid_emphasis or (segment_tone is not None and segment_tone not in valid_tones):
                    raise ValueError("unsupported conclusion emphasis or tone")
                classes = ["conclusion-segment", f"emphasis-{emphasis}"]
                if segment_tone is not None:
                    classes.append(f"conclusion-color-{segment_tone}")
                rendered_segments.append(f'<span class="{" ".join(classes)}">{esc(segment["text"])}</span>')
            note = f'<div class="conclusion-note">{esc(item["note"])}</div>' if item.get("note") else ""
            cards.append(
                f'<article class="conclusion-item conclusion-tone-{tone} searchable">'
                f'<h3>{esc(item["label"])}</h3>'
                f'<p class="conclusion-copy">{"".join(rendered_segments)}</p>{note}</article>'
            )
        title = esc(block.get("title") or "核心结论")
        return f'<section class="card conclusion-card"><div class="card-head"><h2>{title}</h2></div><div class="conclusion-grid">{"".join(cards)}</div></section>'

    def render_metric(self, item: dict[str, Any], variant: str) -> str:
        tone = slug(item.get("tone", "info"))
        badge = f'<span class="metric-badge tone-{tone}">{esc(item.get("badge"))}</span>' if item.get("badge") else ""
        return f'<article class="card metric metric-{variant} searchable"><div class="metric-label"><span>{esc(item.get("label", ""))}</span>{badge}</div><div class="metric-value">{esc(item.get("value", "—"))}</div><div class="metric-note">{esc(item.get("note", ""))}</div></article>'

    def render_table(self, block: dict[str, Any]) -> str:
        columns = block.get("columns", [])
        if not columns:
            raise ValueError("table requires columns")
        labels = [column.get("label", column.get("key", "")) if isinstance(column, dict) else column for column in columns]
        head = "".join(f"<th>{esc(label)}</th>" for label in labels)
        rows = []
        for row in block.get("rows", []):
            if isinstance(row, dict):
                values = [row.get(column.get("key")) if isinstance(column, dict) else row.get(str(column)) for column in columns]
            else:
                values = row
            cells = "".join(f"<td>{self.render_cell(value)}</td>" for value in values)
            rows.append(f'<tr class="searchable">{cells}</tr>')
        title = esc(block.get("title", ""))
        meta = esc(block.get("meta", ""))
        headbar = f'<div class="card-head"><h2>{title}</h2><span>{meta}</span></div>' if title or meta else ""
        return f'<article class="card table-card">{headbar}<div class="table-wrap"><table class="data-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></article>'

    def render_cell(self, value: Any) -> str:
        if not isinstance(value, dict):
            return esc(value if value is not None else "—")
        text = esc(value.get("text", "—"))
        image_url = str(value.get("image_url", "")).strip()
        if image_url:
            if self.external_images != "allow_https":
                raise ValueError("table cell image_url requires meta.external_images=allow_https")
            if not re.fullmatch(r'''https://[^\s"'<>]+''', image_url):
                raise ValueError("table cell image_url must be an HTTPS URL")
            text = (
                '<div class="cell-product">'
                f'<div class="cell-thumb"><img src="{esc(image_url)}" alt="{esc(value.get("alt") or value.get("text", ""))}" '
                'loading="lazy" referrerpolicy="no-referrer" data-remote-image>'
                '<div class="image-empty" hidden>加载失败</div></div>'
                f'<span>{text}</span></div>'
            )
        if value.get("badge"):
            text += f' <span class="tag tone-{esc(slug(value.get("tone", "info")))}">{esc(value["badge"])}</span>'
        actions = []
        if value.get("url"):
            actions.append(f'<button class="text-button compact" type="button" data-url="{esc(value["url"])}">{esc(value.get("action_label", "打开"))}</button>')
        if value.get("copy_value"):
            actions.append(f'<button class="text-button compact copy-button" type="button" data-copy="{esc(value["copy_value"])}">{esc(value.get("copy_label", "复制"))}</button>')
        if actions:
            text += f'<div class="inline-actions">{"".join(actions)}</div>'
        return text

    def render_tabs(self, block: dict[str, Any]) -> str:
        self.tab_counter += 1
        group = f"tabs-{self.tab_counter}"
        tabs = block.get("tabs", [])
        if not tabs:
            return self.render_block({"type": "empty", "text": block.get("empty_text", "暂无分类")})
        buttons = []
        panels = []
        for index, tab in enumerate(tabs):
            tab_id = slug(tab.get("id", f"tab-{index+1}"))
            suffix = f" · {esc(tab.get('badge'))}" if tab.get("badge") not in (None, "") else ""
            buttons.append(f'<button type="button" data-tab-target="{tab_id}" class="{"active" if index == 0 else ""}">{esc(tab.get("label", tab_id))}{suffix}</button>')
            hidden = "" if index == 0 else " hidden"
            panels.append(f'<div class="tab-panel" data-tab="{tab_id}"{hidden}>{self.render_blocks(tab.get("blocks", []))}</div>')
        title = esc(block.get("title", ""))
        meta = esc(block.get("meta", ""))
        head = f'<div class="card-head"><h2>{title}</h2><span>{meta}</span></div>' if title or meta else ""
        return f'<section class="card tabs-card" data-tabs="{group}">{head}<div class="tab-buttons">{"".join(buttons)}</div>{"".join(panels)}</section>'

    def render_products(self, block: dict[str, Any]) -> str:
        columns = max(1, min(4, int(block.get("columns", 3))))
        items = block.get("items", [])
        if not items:
            return '<div class="empty">暂无候选商品</div>'
        page_size = block.get("page_size")
        if page_size is None:
            products = "".join(self.render_product(item) for item in items)
            return f'<div class="product-grid product-grid-{columns}">{products}</div>'
        page_size = max(1, int(page_size))
        options = block.get("sort_options", [])
        option_html = "".join(
            f'<option value="{esc(option["key"])}" data-direction="{esc(option.get("direction", "desc"))}">{esc(option["label"])}</option>'
            for option in options
        )
        cards = "".join(
            f'<div class="gallery-entry" data-source-order="{index}" '
            f'data-sort-values="{esc(json.dumps(item.get("sort_values", {}), ensure_ascii=False, separators=(",", ":")))}">'
            f'{self.render_product(item)}</div>'
            for index, item in enumerate(items)
        )
        controls = (
            '<div class="gallery-controls">'
            f'<label>排序<select data-gallery-sort><option value="source">原始顺序</option>{option_html}</select></label>'
            f'<span data-gallery-count>{len(items)} 件</span>'
            '<div class="gallery-pager"><button type="button" data-page-prev>上一页</button>'
            '<span data-page-status></span><button type="button" data-page-next>下一页</button></div>'
            '</div>'
        )
        bottom = ('<div class="gallery-controls gallery-controls-bottom"><span data-gallery-count-bottom></span>'
                  '<div class="gallery-pager"><button type="button" data-page-prev-bottom>上一页</button>'
                  '<span data-page-status-bottom></span><button type="button" data-page-next-bottom>下一页</button>'
                  '</div></div>')
        return (f'<section class="product-gallery" data-product-gallery data-page-size="{page_size}">'
                f'{controls}<div class="product-grid product-grid-{columns}" data-gallery-grid>{cards}</div>'
                f'{bottom}'
                '</section>')

    def render_product(self, item: dict[str, Any]) -> str:
        asset_id = str(item.get("asset_id", ""))
        asset = self.assets.get(asset_id)
        image_url = str(item.get("image_url", "")).strip()
        item_url = str(item.get("item_url", "")).strip()
        if item_url and not re.fullmatch(r'''https://[^\s"'<>]+''', item_url):
            raise ValueError("product item_url must be an HTTPS URL")
        if asset:
            image = (
                f'<div class="product-media"><img src="{asset["src"]}" '
                f'alt="{esc(item.get("alt") or asset.get("alt", ""))}"></div>'
            )
        elif image_url:
            if self.external_images != "allow_https":
                raise ValueError("product image_url requires meta.external_images=allow_https")
            if not re.fullmatch(r'''https://[^\s"'<>]+''', image_url):
                raise ValueError("product image_url must be an HTTPS URL")
            image = (
                f'<div class="product-media"><img src="{esc(image_url)}" alt="{esc(item.get("alt") or item.get("title", ""))}" '
                'loading="lazy" referrerpolicy="no-referrer" data-remote-image>'
                '<div class="image-empty" hidden>图片加载失败</div></div>'
            )
        else:
            image = '<div class="product-media"><div class="image-empty">图片未提供</div></div>'
        if item_url:
            image = f'<a class="product-media-link" href="{esc(item_url)}" target="_blank" rel="noopener noreferrer" aria-label="打开商品：{esc(item.get("title", ""))}">{image}</a>'
        title = esc(item.get("title", ""))
        if item_url:
            title = f'<a class="product-title-link" href="{esc(item_url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
        tone = slug(item.get("tone", "positive"))
        facts = "".join(f'<div class="fact"><span>{esc(fact.get("label", ""))}</span><b>{esc(fact.get("value", "—"))}</b></div>' for fact in item.get("facts", []))
        evidence = f'<div class="evidence">{esc(item.get("evidence"))}</div>' if item.get("evidence") else ""
        actions = []
        if item.get("url"):
            actions.append(f'<button class="open-button" type="button" data-url="{esc(item["url"])}">{esc(item.get("action_label", "打开详情"))}</button>')
        if item.get("copy_value"):
            actions.append(f'<button class="open-button copy-button" type="button" data-copy="{esc(item["copy_value"])}">{esc(item.get("copy_label", "复制链接"))}</button>')
        if item_url:
            actions.append(f'<button class="open-button copy-button" type="button" data-copy="{esc(item_url)}">复制链接</button>')
        action = f'<div class="product-actions">{"".join(actions)}</div>' if actions else ""
        return f'<article class="card product-card searchable">{image}<div class="product-body"><div class="product-title">{title}</div><div class="product-meta"><span class="price">{esc(item.get("price", "—"))}</span><span class="tag tone-{tone}">{esc(item.get("badge", ""))}</span></div><div class="facts">{facts}</div>{evidence}{action}</div></article>'


def validate_viewmodel(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("ViewModel root must be an object")
    if document.get("contract") != CONTRACT:
        raise ValueError(f"contract must be {CONTRACT}")
    meta = document.get("meta")
    if not isinstance(meta, dict) or not meta.get("title"):
        raise ValueError("meta.title is required")
    views = document.get("views")
    if not isinstance(views, list) or len(views) < 2:
        raise ValueError("views must contain at least two top-level views")
    ids = [slug(view.get("id")) for view in views if isinstance(view, dict)]
    if len(ids) != len(views):
        raise ValueError("every view must be an object with an id")
    if len(ids) != len(set(ids)):
        raise ValueError("view ids must be unique")
    reading_path = (document.get("shell") or {}).get("reading_path", [])
    for item in reading_path:
        if slug(item.get("view_id")) not in ids:
            raise ValueError(f"reading path references unknown view: {item.get('view_id')}")
    for view in views:
        if not view.get("label") or not view.get("title"):
            raise ValueError(f"view {view.get('id')} requires label and title")
        if not isinstance(view.get("blocks", []), list):
            raise ValueError(f"view {view.get('id')} blocks must be an array")
    return document


def render_file(input_value: pathlib.Path | str, output_value: pathlib.Path | str) -> dict[str, Any]:
    input_path = pathlib.Path(input_value).expanduser().resolve()
    output_path = pathlib.Path(output_value).expanduser().resolve()
    if not input_path.is_file():
        raise ValueError(f"input not found: {input_path}")
    if output_path.exists():
        raise ValueError(f"refusing to overwrite existing output: {output_path}")
    document = validate_viewmodel(json.loads(input_path.read_text(encoding="utf-8")))
    assets = normalize_assets(document.get("assets"), input_path.parent)
    views = document["views"]
    shell = document.get("shell", {})
    sidebar_tabs = bool(shell.get("sidebar_tabs"))

    def primary_tabs(view: dict[str, Any]) -> list[dict[str, Any]]:
        for block in view.get("blocks", []):
            if isinstance(block, dict) and block.get("type") == "tabs":
                return block.get("tabs", [])
        return []

    nav_groups = []
    for view in views:
        view_id = slug(view["id"])
        children = primary_tabs(view) if sidebar_tabs else []
        child_html = ""
        if children:
            child_buttons = []
            for index, tab in enumerate(children):
                tab_id = slug(tab.get("id", f"tab-{index + 1}"))
                badge = tab.get("badge")
                badge_html = f'<span class="nav-child-badge">{esc(badge)}</span>' if badge not in (None, "") else ""
                child_buttons.append(
                    f'<button type="button" class="nav-child" data-child-view="{esc(view_id)}" data-child-tab="{esc(tab_id)}">'
                    f'<span>{esc(tab.get("label", tab_id))}</span>{badge_html}</button>'
                )
            child_html = f'<div class="nav-children" data-nav-children="{esc(view_id)}">{"".join(child_buttons)}</div>'
        chevron = '<span class="nav-chevron" aria-hidden="true">⌄</span>' if children else ""
        nav_groups.append(
            f'<div class="nav-group" data-nav-group="{esc(view_id)}">'
            f'<button type="button" class="nav-parent" data-view-target="{esc(view_id)}"><span class="nav-dot"></span><span>{esc(view["label"])}</span>{chevron}</button>'
            f'{child_html}</div>'
        )
    nav = "".join(nav_groups)

    reading_items = []
    for index, item in enumerate(shell.get("reading_path", []), 1):
        tab_attr = f' data-reading-tab="{esc(slug(item["tab_id"]))}"' if item.get("tab_id") else ""
        reading_items.append(
            f'<button type="button" data-reading-view="{esc(slug(item["view_id"]))}"{tab_attr}>'
            f'<span class="reading-step">{index}</span><span>{esc(item["label"])}</span></button>'
        )
    reading_path = (
        '<nav class="reading-path" id="readingPath" aria-label="报告阅读路径">'
        '<b>阅读路径</b><div class="reading-items">' + '<span class="reading-arrow">→</span>'.join(reading_items) + '</div></nav>'
        if reading_items else ""
    )

    renderer = Renderer(document, assets)
    rendered_views = []
    for index, view in enumerate(views):
        hidden = "" if index == 0 else " hidden"
        badge = view.get("badge")
        badge_html = ""
        if badge:
            badge_html = f'<span class="tag tone-{esc(slug(badge.get("tone", "info")))}">{esc(badge.get("text", ""))}</span>' if isinstance(badge, dict) else f'<span class="tag tone-info">{esc(badge)}</span>'
        heading = f'<div class="page-heading"><div><div class="eyebrow">{esc(view.get("eyebrow", ""))}</div><h1>{esc(view["title"])}</h1><p>{esc(view.get("subtitle", ""))}</p></div>{badge_html}</div>'
        content = renderer.render_blocks(view.get("blocks", []))
        rendered_views.append(f'<section class="view" data-view="{esc(slug(view["id"]))}" id="view-{esc(slug(view["id"]))}" tabindex="-1"{hidden}>{heading}{content}</section>')

    meta = document["meta"]
    status = "".join(f"<div>{esc(line)}</div>" for line in shell.get("status", []))
    search = '<input class="search" id="search" type="search" placeholder="{}">'.format(esc(shell.get("search_placeholder", "搜索当前视图"))) if shell.get("search", True) else ""
    date = f'<div class="date-chip" id="dateRange">{esc(shell.get("date_range", ""))}</div>' if shell.get("date_range") else ""
    replacements = {
        "__TITLE__": esc(meta["title"]),
        "__CLI_VERSION__": esc(CLI_VERSION),
        "__CONTRACT__": esc(CONTRACT),
        "__EXTERNAL_IMAGE_POLICY__": esc(str(meta.get("external_images", "forbid"))),
        "__BRAND_MARK__": esc(shell.get("brand_mark", "CI")),
        "__BRAND_TITLE__": esc(shell.get("brand_title", meta["title"])),
        "__BRAND_SUBTITLE__": esc(shell.get("brand_subtitle", "Commerce Insight")),
        "__TOP_TITLE__": esc(meta["title"]),
        "__TOP_META__": esc(meta.get("subtitle", "")),
        "__NAV_LABEL__": esc(shell.get("nav_label", "报告视图")),
        "__NAV__": nav,
        "__BODY_CLASS__": "sidebar-tabs" if sidebar_tabs else "",
        "__READING_PATH__": reading_path,
        "__STATUS__": status,
        "__TOOLS__": search + date,
        "__VIEWS__": "".join(rendered_views),
        "__FOOTER__": esc(meta.get("footer", "")),
        "__VIEW_IDS__": json.dumps([slug(view["id"]) for view in views], ensure_ascii=False),
    }
    template = (ROOT / "templates" / "workbench.html").read_text(encoding="utf-8")
    for marker, value in replacements.items():
        if marker not in template:
            raise ValueError(f"template marker missing: {marker}")
        template = template.replace(marker, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template, encoding="utf-8")
    return {
        "ok": True,
        "output": str(output_path),
        "cli_version": CLI_VERSION,
        "contract": CONTRACT,
        "views": len(views),
        "assets_embedded": len(assets),
        "bytes": output_path.stat().st_size,
    }
