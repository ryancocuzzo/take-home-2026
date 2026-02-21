"""Tests for structured extraction (Pass 1: JSON-LD, meta tags, script blobs)."""

import unittest

from backend.corpus import DATA_DIR, PAGES
from backend.extract.structured_extraction import extract_structured_signals
from models import ExtractionContext, OptionGroup


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

    def test_therealreal_extracts_from_meta_tags(self) -> None:
        """The RealReal page: extraction pulls from meta tags (og:*, canonical)."""
        html = _load_html("therealreal-gucci-bag.html")

        context = extract_structured_signals(
            html,
            page_url="https://www.therealreal.com/products/women/handbags/crossbody-bags/gucci-double-g-marmont-small-tkmwf",
        )

        self.assertTrue(
            any("Gucci" in t or "Marmont" in t or "Double G" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_allbirds_extracts_from_meta_tags_and_script(self) -> None:
        """Allbirds page: extraction pulls from meta tags (og:*) and Shopify script blobs."""
        html = _load_html("allbirds-shoe.html")

        context = extract_structured_signals(
            html,
            page_url="https://www.allbirds.com/products/mens-dasher-nz",
        )

        self.assertTrue(
            any("Dasher" in t or "Allbirds" in t for t in context.title_candidates),
            f"Expected product title in {context.title_candidates}",
        )
        self.assertIn("Allbirds", context.brand_candidates)
        self.assertIn("140.00", context.price_candidates)
        self.assertGreaterEqual(len(context.image_url_candidates), 1)

    def test_allbirds_extracts_colors_into_option_group(self) -> None:
        """Allbirds page: color signals from data-product-object produce a Color OptionGroup."""
        html = _load_html("allbirds-shoe.html")
        context = extract_structured_signals(
            html,
            page_url="https://www.allbirds.com/products/mens-dasher-nz",
        )

        color_group = next(
            (g for g in context.option_group_candidates if g.dimension == "Color"), None
        )
        self.assertIsNotNone(color_group, "Expected a Color OptionGroup in option_group_candidates")
        assert color_group is not None
        values = [o.value for o in color_group.options]
        self.assertTrue(
            any("Blizzard" in v for v in values),
            f"Expected Blizzard colorway in Color OptionGroup, got {values}",
        )

    def test_allbirds_color_option_group_includes_swatch_colorways(self) -> None:
        """Allbirds page: data-product-color and swatch aria-labels are included in the Color OptionGroup."""
        html = _load_html("allbirds-shoe.html")
        context = extract_structured_signals(
            html,
            page_url="https://www.allbirds.com/products/mens-dasher-nz",
        )

        color_group = next(
            (g for g in context.option_group_candidates if g.dimension == "Color"), None
        )
        self.assertIsNotNone(color_group)
        assert color_group is not None
        values = [o.value for o in color_group.options]
        self.assertTrue(
            any("Auburn" in v for v in values),
            f"Expected Auburn colorway in Color OptionGroup, got {values}",
        )

    def test_allbirds_extracts_variants_into_raw_attributes(self) -> None:
        """Allbirds page: variants from var meta = {...} blob are passed through to raw_attributes."""
        import json

        html = _load_html("allbirds-shoe.html")
        context = extract_structured_signals(
            html,
            page_url="https://www.allbirds.com/products/mens-dasher-nz",
        )

        self.assertIn("variants", context.raw_attributes)
        variants = json.loads(context.raw_attributes["variants"])
        self.assertGreaterEqual(len(variants), 10)
        self.assertIn("public_title", variants[0])
        self.assertIn("8", [v["public_title"] for v in variants])

    def test_all_pages_produce_extraction_context(self) -> None:
        """All pages produce a valid ExtractionContext without error."""
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
