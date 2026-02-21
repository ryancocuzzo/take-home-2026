import json
from dataclasses import dataclass, field
from urllib.parse import unquote
from typing import Any, Callable, Protocol

from models import OptionGroup, OptionValue


class CandidateSink(Protocol):
    def add_candidates(self, field_name: str, values: list[str]) -> None: ...
    def add_raw_attribute(self, key: str, value: str | int | float | bool) -> None: ...
    def add_option_group(self, group: OptionGroup) -> None: ...


@dataclass(frozen=True)
class MappingRules:
    json_key_to_field: dict[str, str] = field(
        default_factory=lambda: {
            "name": "title_candidates",
            "title": "title_candidates",
            "productName": "title_candidates",
            "headline": "title_candidates",
            "description": "description_candidates",
            "shortDescription": "description_candidates",
            "metaDescription": "description_candidates",
            "subtitle": "description_candidates",
            "brand": "brand_candidates",
            "brandName": "brand_candidates",
            "vendor": "brand_candidates",
            "manufacturer": "brand_candidates",
            "price": "price_candidates",
            "salePrice": "price_candidates",
            "currentPrice": "price_candidates",
            "listPrice": "price_candidates",
            "compareAtPrice": "price_candidates",
            "priceCurrency": "currency_candidates",
            "currency": "currency_candidates",
            "currencyCode": "currency_candidates",
            "image": "image_url_candidates",
            "images": "image_url_candidates",
            "imageUrl": "image_url_candidates",
            "imageUrls": "image_url_candidates",
            "primaryImage": "image_url_candidates",
            "category": "category_hint_candidates",
            "productType": "category_hint_candidates",
            "breadcrumb": "category_hint_candidates",
            "positiveNotes": "key_feature_candidates",
            "keyFeatures": "key_feature_candidates",
            "features": "key_feature_candidates",
            "highlights": "key_feature_candidates",
            "benefits": "key_feature_candidates",
        }
    )
    # JSON keys whose values are color strings; collected and emitted as a
    # Color OptionGroup rather than a flat candidate list.
    color_keys: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "color", "colour", "colors", "colourways",
            "colorDescription", "colorName", "hues", "swatchColors",
        })
    )
    meta_key_to_field: dict[str, str] = field(
        default_factory=lambda: {
            "og:title": "title_candidates",
            "twitter:title": "title_candidates",
            "title": "title_candidates",
            "description": "description_candidates",
            "og:description": "description_candidates",
            "twitter:description": "description_candidates",
            "og:image": "image_url_candidates",
            "twitter:image": "image_url_candidates",
            "image": "image_url_candidates",
            "og:brand": "brand_candidates",
            "brand": "brand_candidates",
            "product:brand": "brand_candidates",
            "product:price:amount": "price_candidates",
            "og:price:amount": "price_candidates",
            "price": "price_candidates",
            "product:price:currency": "currency_candidates",
            "og:price:currency": "currency_candidates",
            "pricecurrency": "currency_candidates",
        }
    )
    # Keys whose list/dict values should be JSON-serialized into raw_attributes
    # (e.g. variants, options) so the LLM can build Variant objects.
    structured_passthrough_keys: frozenset[str] = field(
        default_factory=lambda: frozenset({"variants", "options", "option_groups"})
    )


def collect_candidates_from_node(
    node: Any,
    sink: CandidateSink,
    rules: MappingRules,
    image_transform: Callable[[str], str] | None = None,
) -> None:
    # Extract known keys into candidate lists
    for key, field_name in rules.json_key_to_field.items():
        values = _collect_values_for_key(node, key)
        if image_transform and field_name == "image_url_candidates":
            values = [image_transform(v) for v in values]
        sink.add_candidates(field_name, values)

    # Collect color values across all color keys and emit as a Color OptionGroup
    color_values: list[str] = []
    for key in rules.color_keys:
        color_values.extend(
            _decode_color_value(v) for v in _collect_values_for_key(node, key)
        )
    if color_values:
        _emit_color_option_group(color_values, sink)

    # Capture structured passthrough (variants, options) — JSON-serialize for LLM
    for key in rules.structured_passthrough_keys:
        value = _find_structured_value(node, key)
        if value is not None:
            sink.add_raw_attribute(key, json.dumps(value))

    # Capture remaining primitive attributes (skip JSON-LD metadata and already-extracted keys)
    if isinstance(node, dict):
        known_keys = set(rules.json_key_to_field.keys()) | set(rules.color_keys)
        for key, value in node.items():
            if _should_skip_raw_attribute(key, value, known_keys):
                continue
            sink.add_raw_attribute(key, value)


def _emit_color_option_group(color_values: list[str], sink: CandidateSink) -> None:
    """Deduplicate color values and emit as a Color OptionGroup if there are 2+."""
    seen: set[str] = set()
    options: list[OptionValue] = []
    for raw in color_values:
        value = raw.strip()
        if value and value not in seen:
            seen.add(value)
            options.append(OptionValue(value=value))
    if len(options) >= 2:
        sink.add_option_group(OptionGroup(dimension="Color", options=options))


def _decode_color_value(value: str) -> str:
    """URL-decode color values (e.g. Blizzard%2FDeep%20Navy -> Blizzard/Deep Navy)."""
    try:
        return unquote(value, errors="replace")
    except Exception:
        return value


def _find_structured_value(node: Any, target_key: str) -> list | dict | None:
    """Recursively find first list or dict value for target_key. Returns None if not found."""
    if isinstance(node, dict):
        if target_key in node:
            val = node[target_key]
            if isinstance(val, (list, dict)) and len(str(val)) < 100_000:
                return val
        for v in node.values():
            found = _find_structured_value(v, target_key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_structured_value(item, target_key)
            if found is not None:
                return found
    return None


def _should_skip_raw_attribute(key: str, value: Any, known_keys: set[str]) -> bool:
    """Skip JSON-LD metadata and keys we already extracted into candidates."""
    if key.startswith("@"):  # JSON-LD metadata (@type, @context, etc.)
        return True
    if key in known_keys:  # Already extracted into candidate lists
        return True
    if not isinstance(value, (str, int, float, bool)):  # Only capture primitives
        return True
    return False


def collect_breadcrumb_hints(node: Any, sink: CandidateSink) -> None:
    if not isinstance(node, dict):
        return
    if node.get("@type") != "BreadcrumbList":
        return
    elements = node.get("itemListElement")
    if not isinstance(elements, list):
        return
    names: list[str] = []
    for element in elements:
        if isinstance(element, dict) and isinstance(element.get("name"), str):
            names.append(element["name"])
    sink.add_candidates("category_hint_candidates", names)


def iter_jsonld_nodes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, list):
            return [node for node in graph if isinstance(node, dict)]
        return [payload]
    if isinstance(payload, list):
        return [node for node in payload if isinstance(node, dict)]
    return []


def _collect_values_for_key(node: Any, target_key: str) -> list[str]:
    values: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == target_key:
                    values.extend(_flatten_scalar_strings(value))
                walk(value)
            return
        if isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(node)
    return values


def _flatten_scalar_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        flattened: list[str] = []
        for key in ("name", "value", "url", "text"):
            nested = value.get(key)
            if isinstance(nested, str):
                flattened.append(nested)
        return flattened
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_scalar_strings(item))
        return flattened
    return []
