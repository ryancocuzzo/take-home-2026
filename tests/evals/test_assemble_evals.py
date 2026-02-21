"""
Eval tests for the full extraction pipeline:
Pass 1 (structured) + Pass 2 (DOM) → taxonomy pre-filter → LLM assembler.

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
from backend.extract.dom_extraction import extract_dom_signals
from backend.extract.structured_extraction import extract_structured_signals
from backend.taxonomy.prefilter import select_category_candidates
from models import VALID_CATEGORIES, Product

def _run_pipeline(filename: str, page_url: str | None) -> Product:
    html = (DATA_DIR / filename).read_text()
    context = extract_structured_signals(html, page_url=page_url)
    extract_dom_signals(html, context, page_url=page_url)
    candidates = select_category_candidates(context)
    return asyncio.run(assemble_product(context, candidates))


_COST_BUDGET_PER_PRODUCT = 0.01  # $0.01 = 1¢


@pytest.mark.slow
@pytest.mark.parametrize(
    "filename,page_url",
    PAGES,
    ids=[p[0] for p in PAGES],
)
def test_pipeline_produces_valid_product(
    filename: str,
    page_url: str | None,
    usage_accumulator,
) -> None:
    """Full pipeline produces a validated Product for each of the 7 test pages."""
    records_before = len(usage_accumulator.records)
    product = _run_pipeline(filename, page_url)
    cost = sum(r.cost for r in usage_accumulator.records[records_before:])

    assert isinstance(product, Product), f"{filename}: result is not a Product"
    assert product.name, f"{filename}: product.name is empty"
    assert product.price.price > 0, f"{filename}: price.price must be > 0"
    assert product.category.name in VALID_CATEGORIES, (
        f"{filename}: category '{product.category.name}' not in taxonomy"
    )
    assert len(product.image_urls) >= 1, f"{filename}: no images"
    assert product.brand, f"{filename}: brand is empty"
    assert len(product.offers) >= 1, f"{filename}: expected at least one offer"
    assert product.offers[0].merchant.name, f"{filename}: offer merchant is empty"
    assert product.offers[0].price.price > 0, f"{filename}: offer price must be > 0"
    assert cost < _COST_BUDGET_PER_PRODUCT, (
        f"{filename}: LLM cost ${cost:.6f} exceeds {_COST_BUDGET_PER_PRODUCT * 100:.0f}¢ budget"
    )
