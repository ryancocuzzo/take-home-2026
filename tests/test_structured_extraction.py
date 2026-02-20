"""Tests for structured extraction (Pass 1: JSON-LD, meta tags, script blobs)."""

import unittest

from backend.corpus import DATA_DIR, PAGES
from backend.extract.structured_extraction import extract_structured_signals
from models import ExtractionContext


def _load_html(name: str) -> str:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Test data not found: {path}")
    return path.read_text()


class TestStructuredExtraction(unittest.TestCase):
    """Extraction behavior that matters to the domain."""

    def test_ace_extracts_from_schema_org_json_ld(self) -> None:
        """Ace Hardware page: extraction pulls product data from schema.org JSON-LD block."""
        html = _load_html("ace.html")

        context = extract_structured_signals(
            html, page_url="https://www.acehardware.com/departments/tools/power-tools/cordless-drills/2385458"
        )

        self.assertIn("DeWalt", context.title_candidates)
        self.assertIn("129.00", context.price_candidates)
        self.assertIn("DeWalt", context.brand_candidates)
        self.assertGreaterEqual(len(context.image_url_candidates), 1)
        self.assertGreaterEqual(len(context.description_candidates), 1)

    def test_llbean_extracts_from_initial_state_blob(self) -> None:
        """L.L.Bean page: extraction pulls product data from embedded window.__INITIAL_STATE__ blob."""
        html = _load_html("llbean.html")

        context = extract_structured_signals(html)

        self.assertTrue(
            any("Carefree" in t or "Henley" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_nike_extracts_from_next_data_script(self) -> None:
        """Nike page: extraction pulls from __NEXT_DATA__ script (Next.js)."""
        html = _load_html("nike.html")

        context = extract_structured_signals(html)

        self.assertTrue(
            any("Air Force" in t or "Nike" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertIn("Nike", context.brand_candidates)
        self.assertGreaterEqual(len(context.price_candidates), 1)
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_article_extracts_from_meta_tags(self) -> None:
        """Article page: extraction pulls from meta tags (og:*, twitter:*)."""
        html = _load_html("article.html")

        context = extract_structured_signals(html)

        self.assertTrue(
            any("Pilar" in t or "Lamp" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertIn("Article", context.brand_candidates)
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_adaysmarch_extracts_product_signals(self) -> None:
        """A Day's March page: extraction produces product candidates."""
        html = _load_html("adaysmarch.html")

        context = extract_structured_signals(html)

        self.assertTrue(
            any("Miller" in t or "Trousers" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_all_five_pages_produce_extraction_context(self) -> None:
        """All 5 pages produce a valid ExtractionContext without error."""
        for name, _ in PAGES:
            with self.subTest(page=name):
                html = _load_html(name)
                context = extract_structured_signals(html)

                self.assertIsInstance(context, ExtractionContext)
                self.assertGreaterEqual(
                    len(context.title_candidates) + len(context.image_url_candidates),
                    1,
                    f"{name}: expected at least title or image candidates",
                )

    def test_page_url_resolves_relative_image_urls(self) -> None:
        """Relative and protocol-relative image URLs are canonicalized when page_url is provided."""
        html = _load_html("ace.html")

        context = extract_structured_signals(
            html, page_url="https://www.acehardware.com/departments/tools/power-tools/cordless-drills/2385458"
        )

        for url in context.image_url_candidates:
            self.assertTrue(
                url.startswith("https://"),
                f"Expected absolute HTTPS URL, got: {url}",
            )

    def test_empty_html_returns_empty_candidates(self) -> None:
        """Empty or minimal HTML returns valid context with empty candidates."""
        context = extract_structured_signals("")

        self.assertIsInstance(context, ExtractionContext)
        self.assertEqual(context.title_candidates, [])
        self.assertEqual(context.image_url_candidates, [])
