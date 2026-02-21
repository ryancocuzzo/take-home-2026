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
from backend.identity import IdentityResolver, IdentityResolverConfig
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


# ---------------------------------------------------------------------------
# Identity done gates (MVP2 Phase 2)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_seeded_products_include_identity_evidence_and_confidence(
    seeded_product_ids: list[str],
) -> None:
    expected_signals = {
        "upc_gtin_exact_match",
        "title_brand_similarity",
    }
    assert seeded_product_ids, "No products were seeded"

    for pid in seeded_product_ids:
        product_path = PRODUCTS_DIR / f"{pid}.json"
        product = Product.model_validate_json(product_path.read_text())

        assert product.canonical_product_id, f"{pid}: canonical_product_id is missing"
        assert product.canonical_product_id.startswith("cp_"), (
            f"{pid}: canonical_product_id must use cp_ prefix"
        )
        assert product.match_decision is not None, f"{pid}: match_decision is missing"
        assert 0.0 <= product.match_decision.confidence <= 1.0

        signals = {e.signal for e in product.match_decision.evidence}
        assert signals == expected_signals, (
            f"{pid}: expected evidence for {expected_signals}, got {signals}"
        )


@pytest.mark.slow
def test_canonical_product_ids_are_stable_across_reruns(
    seeded_product_ids: list[str],
) -> None:
    first_run_ids: dict[str, str] = {}
    for pid in seeded_product_ids:
        product_path = PRODUCTS_DIR / f"{pid}.json"
        product = Product.model_validate_json(product_path.read_text())
        assert product.canonical_product_id is not None
        first_run_ids[pid] = product.canonical_product_id

    second_seeded = asyncio.run(seed_all())
    second_run_ids = {
        pid: product.canonical_product_id for pid, product in second_seeded.items()
    }

    for pid, canonical_id in first_run_ids.items():
        assert pid in second_run_ids, f"{pid}: missing in second seed run"
        assert second_run_ids[pid] == canonical_id, (
            f"{pid}: canonical product ID changed between reruns"
        )


@pytest.mark.slow
def test_identity_thresholds_are_configurable_without_code_changes(
    seeded_product_ids: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products: dict[str, Product] = {}
    for pid in seeded_product_ids:
        product_path = PRODUCTS_DIR / f"{pid}.json"
        products[pid] = Product.model_validate_json(product_path.read_text())

    monkeypatch.setenv("IDENTITY_MATCH_THRESHOLD", "0.99")
    config = IdentityResolverConfig.from_env()
    resolver = IdentityResolver(config)
    resolved = resolver.assign_canonical_products(products)

    for product in resolved.values():
        assert product.match_decision is not None
        assert product.match_decision.threshold == 0.99
