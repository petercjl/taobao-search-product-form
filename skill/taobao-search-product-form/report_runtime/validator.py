#!/usr/bin/env python3
"""Deterministic contract checks for commerce-ui HTML artifacts."""

from __future__ import annotations

import pathlib
import re


REQUIRED = {
    "responsive viewport": r'<meta\s+name=["\']viewport["\']',
    "generator metadata": r'<meta\s+name=["\']generator["\']\s+content=["\']commerce-ui/',
    "contract metadata": r'<meta\s+name=["\']commerce-ui-contract["\']\s+content=["\']compact-workbench@1\.0["\']',
    "external image policy": r'<meta\s+name=["\']commerce-ui-external-images["\']\s+content=["\'](?:forbid|allow_https)["\']',
    "left navigation": r'class=["\'][^"\']*sidebar',
    "lower-left status": r'id=["\']sideStatus["\']',
    "upper-right tools": r'class=["\'][^"\']*tools',
    "modular cards": r'class=["\'][^"\']*card',
    "mobile rule": r'@media\s*\(max-width:',
    "print rule": r'@media\s+print',
    "view targets": r'<[^>]+\bdata-view-target=["\'][^"\']+',
    "independent views": r'<[^>]+\bdata-view=["\'][^"\']+',
    "view router": r'function\s+showView\s*\(',
}

FORBIDDEN = {
    "unresolved template marker": r'__[A-Z][A-Z0-9_]+__|\{\{[^}]+\}\}',
    "private home path": r'/Users/[^/]+/|[A-Za-z]:\\Users\\[^\\]+\\',
    "credential-like value": r'(?i)(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}',
    "top-level anchor scrolling": r'scrollIntoView\s*\(',
}


def validate_file(path_value: pathlib.Path | str) -> dict:
    path = pathlib.Path(path_value).expanduser().resolve()
    errors: list[str] = []
    if not path.is_file():
        return {"ok": False, "path": str(path), "errors": ["file not found"]}
    text = path.read_text(encoding="utf-8")
    for label, pattern in REQUIRED.items():
        if not re.search(pattern, text, re.I):
            errors.append(f"missing {label}")
    for label, pattern in FORBIDDEN.items():
        if re.search(pattern, text):
            errors.append(f"found {label}")

    targets = re.findall(r'<[^>]+\bdata-view-target=["\']([^"\']+)', text, re.I)
    views = re.findall(r'<[^>]+\bdata-view=["\']([^"\']+)', text, re.I)
    if len(targets) < 2:
        errors.append("fewer than two top-level view targets")
    if len(views) < 2:
        errors.append("fewer than two independent views")
    if len(targets) != len(set(targets)):
        errors.append("duplicate top-level view targets")
    if len(views) != len(set(views)):
        errors.append("duplicate independent view ids")
    if set(targets) != set(views):
        errors.append(f"view target/view mismatch: targets={sorted(set(targets))}, views={sorted(set(views))}")

    initially_visible = len(re.findall(r'<section\s+class=["\'][^"\']*\bview\b[^"\']*["\'][^>]*\bdata-view=["\'][^"\']+["\'](?![^>]*\bhidden\b)[^>]*>', text, re.I))
    if initially_visible != 1:
        errors.append(f"expected exactly one initially visible view, found {initially_visible}")

    if 'class="card conclusion-card"' in text:
        conclusion_items = re.findall(r'<article\s+class="conclusion-item\s+conclusion-tone-(?:info|positive|warning|danger)\s+searchable"', text)
        if len(conclusion_items) < 2:
            errors.append("structured conclusion has fewer than two items")
        if not re.search(r'class="conclusion-segment[^\"]*emphasis-(?:strong|strong-italic)', text):
            errors.append("structured conclusion has no bold emphasis")
        if not re.search(r'class="conclusion-segment[^\"]*emphasis-(?:italic|strong-italic)', text):
            errors.append("structured conclusion has no italic emphasis")
        if not re.search(r'class="conclusion-segment[^\"]*conclusion-color-(?:info|positive|warning|danger)', text):
            errors.append("structured conclusion has no color emphasis")

    sizes = [float(x) for x in re.findall(r'font-size\s*:\s*(\d+(?:\.\d+)?)px', text, re.I)]
    if sizes and min(sizes) < 12:
        errors.append(f"font size below 12px found: {min(sizes):g}px")
    if not re.search(r'font-size\s*:\s*13px', text, re.I):
        errors.append("missing 13px body/table baseline")

    policy_match = re.search(r'<meta\s+name=["\']commerce-ui-external-images["\']\s+content=["\']([^"\']+)', text, re.I)
    external_images_approved = bool(policy_match and policy_match.group(1) == "allow_https")
    remote_dependencies = re.findall(r'<([a-z0-9]+)\b[^>]*\b(src|href)=["\'](https?://[^"\']+)', text, re.I)
    invalid_remote = [item for item in remote_dependencies if not item[2].startswith("https://") or
                      (item[0].lower(), item[1].lower()) not in {("img", "src"), ("a", "href")}]
    if invalid_remote:
        errors.append(f"found {len(invalid_remote)} unsupported remote rendering dependency(s)")

    images = re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)', text, re.I)
    external_images = [src for src in images if src.startswith("https://")]
    invalid_images = [src for src in images if not src.startswith("data:image/") and not src.startswith("https://")]
    if external_images and not external_images_approved:
        errors.append(f"found {len(external_images)} unapproved external image asset(s)")
    if invalid_images:
        errors.append(f"found {len(invalid_images)} invalid image asset(s)")
    product_links = re.findall(r'<a\b[^>]*class="product-(?:media|title)-link"[^>]*>', text)
    if product_links and any('target="_blank"' not in link or 'rel="noopener noreferrer"' not in link for link in product_links):
        errors.append("product external links require new-tab noopener noreferrer")
    galleries = re.findall(r'<section\s+class="product-gallery"[^>]*\bdata-product-gallery\b[^>]*>', text)
    if galleries:
        if not re.search(r'function\s+updateGallery\s*\(', text):
            errors.append("product gallery pagination runtime missing")
        if text.count('data-gallery-sort') < len(galleries) or text.count('data-page-next') < len(galleries):
            errors.append("product gallery controls missing")

    return {
        "ok": not errors,
        "path": str(path),
        "contract": "compact-workbench@1.0",
        "view_count": len(views),
        "image_count": len(images),
        "external_image_count": len(external_images),
        "product_link_count": len(product_links),
        "external_images_approved": external_images_approved,
        "product_gallery_count": len(galleries),
        "errors": errors,
    }
