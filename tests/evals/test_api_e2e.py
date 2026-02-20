"""
E2E tests for Phase 2: seed script + API.

These tests make real LLM calls (via the seed fixture) and are therefore marked
`slow`. Run them manually:

    uv run pytest tests/evals/test_api_e2e.py -v -m slow -s
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.corpus import PAGES, PRODUCTS_DIR
from models import Product, ProductSummary
from seed import seed_all

# ---------------------------------------------------------------------------
# Session fixture: seed once, share across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def seeded_product_ids(usage_accumulator) -> list[str]:
    """
    Run the full pipeline for all pages (real LLM calls), write JSON files,
    and return the list of IDs that were successfully seeded.
    """
    seeded = asyncio.run(seed_all())
    return list(seeded.keys())


# ---------------------------------------------------------------------------
# Done gate 1: seed creates JSON files for all pages
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_seed_creates_json_files_for_all_pages(seeded_product_ids: list[str]) -> None:
    json_files = list(PRODUCTS_DIR.glob("*.json"))
    expected = len(PAGES)
    assert len(json_files) == expected, (
        f"Expected {expected} product JSON files in {PRODUCTS_DIR}, found {len(json_files)}"
    )


# ---------------------------------------------------------------------------
# Done gate 2: catalog endpoint returns all products
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_catalog_returns_all_products(seeded_product_ids: list[str]) -> None:
    with TestClient(app) as client:
        response = client.get("/products")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    expected = len(PAGES)
    assert len(data) == expected, f"Expected {expected} products, got {len(data)}"

    for item in data:
        summary = ProductSummary.model_validate(item)
        assert summary.id
        assert summary.name
        assert summary.brand


# ---------------------------------------------------------------------------
# Done gate 3: product detail returns full product for a known ID
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_product_detail_returns_full_product(seeded_product_ids: list[str]) -> None:
    assert seeded_product_ids, "No products were seeded"
    first_id = seeded_product_ids[0]

    with TestClient(app) as client:
        response = client.get(f"/products/{first_id}")

    assert response.status_code == 200
    product = Product.model_validate(response.json())
    assert product.name
    assert product.price.price > 0
    assert product.brand
    assert product.category.name


# ---------------------------------------------------------------------------
# Done gate 4: unknown product ID returns 404
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_unknown_product_returns_404(seeded_product_ids: list[str]) -> None:
    with TestClient(app) as client:
        response = client.get("/products/doesnotexist000")

    assert response.status_code == 404
