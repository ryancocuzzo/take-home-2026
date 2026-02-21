"""
DOM signal extraction (Pass 2).

Enriches an ExtractionContext with signals that live in the visible HTML
structure rather than in structured data blobs: price text, product option
groups (sizes, fits, etc.), and availability indicators.

No LLM is involved. All extraction is deterministic.
"""

import re
from collections import defaultdict
from html import unescape
from html.parser import HTMLParser

from models import ExtractionContext, OptionGroup, OptionValue

# Dimension names that indicate non-product selectors (image carousels,
# geography pickers, survey questions, etc.)
_NON_PRODUCT_DIMENSIONS: frozenset[str] = frozenset(
    {"Thumbnail", "Country", "Quantity", "Qty", "State", "Language"}
)

# Minimum number of distinct values required before we treat a dimension
# as a meaningful OptionGroup (a single value is not a choice).
_MIN_OPTION_VALUES = 2

# Regex patterns for deriving (dimension, value) from aria-label text on
# interactive elements (buttons, inputs).
#
# Pattern A: "<Dimension> Option: <Value>"
#   e.g. "Size Option: Large", "Item Option: Regular"
_OPTION_LABEL_RE = re.compile(r"^(.+?)\s+Option:\s+(.+)$", re.IGNORECASE)

# Pattern B: "Select <dimension> <value>"
#   e.g. "Select size 8", "Select size 8.5"
_SELECT_LABEL_RE = re.compile(r"^Select\s+(\w+)\s+(.+)$", re.IGNORECASE)

# Schema.org availability URL → short token
# e.g. "https://schema.org/InStock" → "InStock"
_SCHEMA_ORG_PREFIX = "https://schema.org/"


class _DomSignalParser(HTMLParser):
    """
    Single-pass HTML parser that collects three categories of DOM signals:

    - price_texts: raw text content from elements whose class contains "price"
    - option_signals: (dimension, value) tuples from aria-label patterns
    - availability: normalised availability string from itemprop="availability"
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.price_texts: list[str] = []
        self.option_signals: list[tuple[str, str]] = []
        self.availability: str | None = None

        # Stack of open elements being buffered for price text extraction.
        # Each entry is a dict with a "text" accumulator.
        self._price_stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}

        self._collect_price_signals(tag, attrs_dict)
        self._collect_option_signals(tag, attrs_dict)
        self._collect_availability(attrs_dict)

    def handle_data(self, data: str) -> None:
        for frame in self._price_stack:
            frame["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if self._price_stack and self._price_stack[-1]["tag"] == tag.lower():
            frame = self._price_stack.pop()
            text = frame["text"].strip()
            if text:
                self.price_texts.append(text)

    # ------------------------------------------------------------------
    # Signal collectors
    # ------------------------------------------------------------------

    def _collect_price_signals(self, tag: str, attrs: dict[str, str]) -> None:
        """Push elements that likely contain a price onto the text-buffer stack."""
        itemprop = attrs.get("itemprop", "")
        data_price = attrs.get("data-price", "")
        class_val = attrs.get("class", "")

        if itemprop.lower() == "price":
            # Prefer content attribute (machine-readable); fall back to text.
            content = attrs.get("content", "")
            if content:
                self.price_texts.append(content)
                return
            self._price_stack.append({"tag": tag.lower(), "text": ""})
        elif data_price:
            self.price_texts.append(data_price)
        elif "price" in class_val.lower():
            self._price_stack.append({"tag": tag.lower(), "text": ""})

    def _collect_option_signals(self, tag: str, attrs: dict[str, str]) -> None:
        """Extract (dimension, value) pairs from interactive element aria-labels."""
        aria_label = attrs.get("aria-label", "").strip()
        if not aria_label:
            return

        m = _OPTION_LABEL_RE.match(aria_label)
        if m:
            dimension = m.group(1).strip().title()
            value = m.group(2).strip()
            self.option_signals.append((dimension, value))
            return

        m = _SELECT_LABEL_RE.match(aria_label)
        if m:
            dimension = m.group(1).strip().title()
            value = m.group(2).strip()
            self.option_signals.append((dimension, value))

    def _collect_availability(self, attrs: dict[str, str]) -> None:
        """Capture the first itemprop=availability content attribute seen."""
        if self.availability is not None:
            return
        if attrs.get("itemprop", "").lower() == "availability":
            content = attrs.get("content", "").strip()
            if content:
                token = content.removeprefix(_SCHEMA_ORG_PREFIX)
                self.availability = token


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def extract_dom_signals(
    html: str,
    context: ExtractionContext,
    page_url: str | None = None,  # reserved for future relative-URL resolution
) -> None:
    """
    Pass 2: enrich *context* with signals extracted from visible HTML structure.

    Modifies *context* in place. Safe to call on any HTML including empty strings.
    """
    parser = _DomSignalParser()
    parser.feed(html)

    _apply_price_signals(parser.price_texts, context)
    _apply_option_groups(parser.option_signals, context)
    _apply_availability(parser.availability, context)


def _apply_price_signals(price_texts: list[str], context: ExtractionContext) -> None:
    """Add non-empty, deduplicated price strings to price_candidates."""
    candidates: list[str] = []
    for raw in price_texts:
        cleaned = raw.strip()
        if cleaned:
            candidates.append(cleaned)
    context.add_candidates("price_candidates", candidates)


def _apply_option_groups(
    signals: list[tuple[str, str]], context: ExtractionContext
) -> None:
    """
    Group (dimension, value) signals into OptionGroups and add them to context.

    Filters out known non-product dimensions and groups with fewer than
    _MIN_OPTION_VALUES distinct values.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    seen_values: dict[str, set[str]] = defaultdict(set)

    for dimension, value in signals:
        if dimension in _NON_PRODUCT_DIMENSIONS:
            continue
        if value not in seen_values[dimension]:
            grouped[dimension].append(value)
            seen_values[dimension].add(value)

    for dimension, values in grouped.items():
        if len(values) < _MIN_OPTION_VALUES:
            continue
        group = OptionGroup(
            dimension=dimension,
            options=[OptionValue(value=v) for v in values],
        )
        context.add_option_group(group)


def _apply_availability(availability: str | None, context: ExtractionContext) -> None:
    """Store availability signal in raw_attributes if present."""
    if availability:
        context.add_raw_attribute("dom_availability", availability)
