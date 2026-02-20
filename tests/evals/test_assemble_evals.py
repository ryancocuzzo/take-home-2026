"""
Eval tests for the full extraction pipeline: Pass 1 → taxonomy pre-filter → LLM assembler.

These tests make real LLM calls and cost money (~$0.01 total for all 5 pages).
They are marked `slow` and excluded from normal CI.

Run manually:
    uv run pytest tests/evals/ -v -m slow -s

The -s flag ensures the cost summary printed by conftest.py is visible.
"""

import asyncio
from pathlib import Path

import pytest

from backend.assemble import assemble_product
from backend.extract.structured_extraction import extract_structured_signals
from backend.taxonomy.prefilter import select_category_candidates
from models import VALID_CATEGORIES, Product

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# (filename, page_url, price_in_structured_data)
# price_in_structured_data=False means price is DOM-only (requires Pass 2); skip that assertion.
_PAGES: list[tuple[str, str | None, bool]] = [
    (
        "ace.html",
        "https://www.acehardware.com/departments/tools/power-tools/cordless-drills/2385458",
        True,
    ),
    ("llbean.html", None, True),
    ("nike.html", "https://www.nike.com/t/air-force-1-07-lv8-shoes", True),
    (
        "article.html",
        "https://www.article.com/product/pilar-lamp",
        False,  # Price is in DOM only (<span class="regularPrice">), not in structured data — Pass 2 gap
    ),
    ("adaysmarch.html", "https://www.adaysmarch.com/products/miller-trousers", True),
]


def _run_pipeline(filename: str, page_url: str | None) -> Product:
    html = (DATA_DIR / filename).read_text()
    context = extract_structured_signals(html, page_url=page_url)
    candidates = select_category_candidates(context)
    return asyncio.run(assemble_product(context, candidates))


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
    usage_accumulator,  # ensures session accumulator is active
) -> None:
    """Full pipeline produces a validated Product for each of the 5 test pages."""
    product = _run_pipeline(filename, page_url)

    assert isinstance(product, Product), f"{filename}: result is not a Product"
    assert product.name, f"{filename}: product.name is empty"
    if price_in_structured_data:
        assert product.price.price > 0, f"{filename}: price.price must be > 0"
    assert product.category.name in VALID_CATEGORIES, (
        f"{filename}: category '{product.category.name}' not in taxonomy"
    )
    assert len(product.image_urls) >= 1, f"{filename}: no images"
    assert product.brand, f"{filename}: brand is empty"
