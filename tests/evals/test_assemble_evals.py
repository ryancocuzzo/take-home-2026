"""
Eval tests for the full extraction pipeline: Pass 1 → taxonomy pre-filter → LLM assembler.

These tests make real LLM calls and cost money (~$0.01 total for all pages).
They are marked `slow` and excluded from normal CI.

Run manually:
    uv run pytest tests/evals/ -v -m slow -s

The -s flag ensures the cost summary printed by conftest.py is visible.
"""

import asyncio

import pytest

from backend.assemble.assemble import assemble_product
from backend.corpus import DATA_DIR, PAGES
from backend.extract.structured_extraction import extract_structured_signals
from backend.taxonomy.prefilter import select_category_candidates
from models import VALID_CATEGORIES, Product

# price_in_structured_data=False means price is DOM-only (requires Pass 2); skip that assertion.
_PRICE_IN_STRUCTURED_DATA: dict[str, bool] = {
    "ace.html": True,
    "llbean.html": True,
    "nike.html": True,
    "article.html": False,  # Price is in DOM only (<span class="regularPrice">), not in structured data — Pass 2 gap
    "adaysmarch.html": True,
    "therealreal-gucci-bag.html": False,  # Price in data-amount on afterpay element, not in meta/JSON-LD/script blobs
    "allbirds-shoe.html": True,  # og:price:amount meta tag
}

# (filename, page_url, price_in_structured_data)
_PAGES: list[tuple[str, str | None, bool]] = [
    (filename, url, _PRICE_IN_STRUCTURED_DATA[filename]) for filename, url in PAGES
]


def _run_pipeline(filename: str, page_url: str | None) -> Product:
    html = (DATA_DIR / filename).read_text()
    context = extract_structured_signals(html, page_url=page_url)
    candidates = select_category_candidates(context)
    return asyncio.run(assemble_product(context, candidates))


_COST_BUDGET_PER_PRODUCT = 0.01  # $0.01 = 1¢


@pytest.mark.slow
@pytest.mark.parametrize(
    "filename,page_url,price_in_structured_data",
    _PAGES,
    ids=[p[0] for p in _PAGES],
)
def test_pipeline_produces_valid_product(
    filename: str,
    page_url: str | None,
    price_in_structured_data: bool,
    usage_accumulator,
) -> None:
    """Full pipeline produces a validated Product for each of the 7 test pages."""
    records_before = len(usage_accumulator.records)
    product = _run_pipeline(filename, page_url)
    cost = sum(r.cost for r in usage_accumulator.records[records_before:])

    assert isinstance(product, Product), f"{filename}: result is not a Product"
    assert product.name, f"{filename}: product.name is empty"
    if price_in_structured_data:
        assert product.price.price > 0, f"{filename}: price.price must be > 0"
    assert product.category.name in VALID_CATEGORIES, (
        f"{filename}: category '{product.category.name}' not in taxonomy"
    )
    assert len(product.image_urls) >= 1, f"{filename}: no images"
    assert product.brand, f"{filename}: brand is empty"
    assert cost < _COST_BUDGET_PER_PRODUCT, (
        f"{filename}: LLM cost ${cost:.6f} exceeds {_COST_BUDGET_PER_PRODUCT * 100:.0f}¢ budget"
    )
