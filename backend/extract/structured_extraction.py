import json
from collections.abc import Callable
from typing import Any

from models import ExtractionContext

from .html_signals import MetaSignal, ScriptSignal, extract_html_signals
from .mapping import (
    MappingRules,
    collect_breadcrumb_hints,
    collect_candidates_from_node,
    iter_jsonld_nodes,
)
from .script_blob import iter_assigned_json_blobs
from .urls import UrlNormalizer


def extract_structured_signals(
    html_text: str,
    page_url: str | None = None,
    *,
    mapping_rules: MappingRules | None = None,
    url_normalizer: UrlNormalizer | None = None,
) -> ExtractionContext:
    """
    Extract product signals from HTML using structured data sources.
    
    This is the first pass of extraction (Pass 1). It pulls from three sources:
    1) JSON-LD (schema.org structured data)
    2) Meta tags (og:*, twitter:*, standard meta)
    3) Embedded script blobs (window.__FOO__ = {...}, application/json scripts)
    
    Args:
        html_text: Raw HTML content from the product page
        page_url: Optional page URL for resolving relative image URLs
        mapping_rules: Optional custom mapping rules (defaults to standard rules)
        url_normalizer: Optional custom URL normalizer (defaults to standard normalizer)
    
    Returns:
        ExtractionContext with candidate lists for title, price, images, etc.
        The context contains *candidates* (multiple possibilities), not resolved values.
    
    Example:
        ```python
        # Basic usage - just pass HTML
        html = (DATA_DIR / "nike.html").read_text()  # DATA_DIR from backend.corpus
        context = extract_structured_signals(html)
        
        # Check what was extracted
        print(context.title_candidates)  # ["Nike Air Force 1", "Air Force 1 '07 LV8"]
        print(context.image_url_candidates)  # ["https://...", "https://..."]
        print(context.price_candidates)  # ["129.00", "$129"]
        
        # With page URL for relative image resolution
        context = extract_structured_signals(
            html,
            page_url="https://www.nike.com/gb/t/air-force-1-07-lv8-shoes"
        )
        # Now relative URLs like "/images/product.jpg" become absolute
        ```
    """
    rules = mapping_rules or MappingRules()
    normalizer = url_normalizer or UrlNormalizer()

    context = ExtractionContext(page_url=page_url)
    scripts, meta_tags = extract_html_signals(html_text)
    image_transform = _image_transform(normalizer=normalizer, page_url=page_url)

    _extract_json_ld(scripts=scripts, context=context, rules=rules, image_transform=image_transform)
    _extract_meta_tags(
        meta_tags=meta_tags, context=context, rules=rules, image_transform=image_transform
    )
    _extract_script_blobs(
        scripts=scripts, context=context, rules=rules, image_transform=image_transform
    )
    return context


def _extract_json_ld(
    scripts: list[ScriptSignal],
    context: ExtractionContext,
    rules: MappingRules,
    image_transform: Callable[[str], str],
) -> None:
    for script in scripts:
        script_type = script.attrs.get("type", "").strip().lower()
        if script_type != "application/ld+json":
            continue
        payload = _safe_json_loads(script.body)
        if payload is None:
            continue
        for node in iter_jsonld_nodes(payload):
            collect_candidates_from_node(
                node=node, sink=context, rules=rules, image_transform=image_transform
            )
            collect_breadcrumb_hints(node=node, sink=context)


def _extract_meta_tags(
    meta_tags: list[MetaSignal],
    context: ExtractionContext,
    rules: MappingRules,
    image_transform: Callable[[str], str],
) -> None:
    for meta in meta_tags:
        field_name = rules.meta_key_to_field.get(meta.key)
        if not field_name:
            continue
        content = meta.content.strip()
        if not content:
            continue
        value = image_transform(content) if field_name == "image_url_candidates" else content
        context.add_candidates(field_name, [value])


def _extract_script_blobs(
    scripts: list[ScriptSignal],
    context: ExtractionContext,
    rules: MappingRules,
    image_transform: Callable[[str], str],
) -> None:
    for script in scripts:
        script_type = script.attrs.get("type", "").strip().lower()
        if script_type == "application/json":
            payload = _safe_json_loads(script.body)
            if payload is not None:
                collect_candidates_from_node(
                    node=payload, sink=context, rules=rules, image_transform=image_transform
                )

        for blob in iter_assigned_json_blobs(script.body):
            collect_candidates_from_node(
                node=blob, sink=context, rules=rules, image_transform=image_transform
            )


def _safe_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _image_transform(normalizer: UrlNormalizer, page_url: str | None) -> Callable[[str], str]:
    return lambda raw: normalizer.canonicalize(raw, page_url=page_url)
