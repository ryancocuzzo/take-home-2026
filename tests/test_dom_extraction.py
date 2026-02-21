"""Tests for DOM signal extraction (Pass 2)."""

import unittest

from backend.corpus import DATA_DIR
from backend.extract.dom_extraction import extract_dom_signals
from models import ExtractionContext


def _load_html(name: str) -> str:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Test data not found: {path}")
    return path.read_text()


def _context_with_dom(filename: str, page_url: str | None = None) -> ExtractionContext:
    """Return an ExtractionContext enriched only by DOM extraction (no Pass 1)."""
    context = ExtractionContext(page_url=page_url)
    extract_dom_signals(_load_html(filename), context, page_url=page_url)
    return context


def _get_option_group(context: ExtractionContext, dimension: str):
    return next(
        (g for g in context.option_group_candidates if g.dimension.lower() == dimension.lower()),
        None,
    )


class TestDomPriceFallback(unittest.TestCase):

    def test_article_dom_price_candidate_is_nonzero(self) -> None:
        """Article page: DOM extraction finds the regularPrice span and adds a non-zero price."""
        context = _context_with_dom("article.html")

        self.assertTrue(
            context.price_candidates,
            "Expected at least one price candidate from DOM extraction",
        )
        # At least one candidate should contain a non-zero numeric value
        self.assertTrue(
            any("349" in p for p in context.price_candidates),
            f"Expected '349' in price_candidates, got {context.price_candidates}",
        )

    def test_price_deduplication(self) -> None:
        """The same price text appearing in multiple elements is deduplicated."""
        context = _context_with_dom("article.html")

        # All price values should be unique strings after merge_unique
        self.assertEqual(
            len(context.price_candidates),
            len(set(context.price_candidates)),
            "Duplicate price candidates should be deduplicated",
        )

    def test_empty_html_produces_no_price_candidates(self) -> None:
        context = ExtractionContext()
        extract_dom_signals("", context)
        self.assertEqual(context.price_candidates, [])


class TestDomOptionGroups(unittest.TestCase):

    def test_llbean_size_option_group(self) -> None:
        """LLBean page: 'Size Option: X' buttons produce a Size OptionGroup."""
        context = _context_with_dom("llbean.html")

        size_group = _get_option_group(context, "Size")
        self.assertIsNotNone(size_group, "Expected a Size OptionGroup from LLBean DOM")
        assert size_group is not None
        values = [o.value for o in size_group.options]
        self.assertIn("Large", values)
        self.assertIn("Small", values)
        self.assertGreaterEqual(len(values), 3)

    def test_llbean_item_option_group(self) -> None:
        """LLBean page: 'Item Option: X' buttons produce a second OptionGroup dimension."""
        context = _context_with_dom("llbean.html")

        item_group = _get_option_group(context, "Item")
        self.assertIsNotNone(item_group, "Expected an Item OptionGroup from LLBean DOM")
        assert item_group is not None
        values = [o.value for o in item_group.options]
        self.assertIn("Regular", values)
        self.assertIn("Tall", values)

    def test_allbirds_size_option_group(self) -> None:
        """Allbirds page: 'Select size X' buttons produce a Size OptionGroup."""
        context = _context_with_dom("allbirds-shoe.html")

        size_group = _get_option_group(context, "Size")
        self.assertIsNotNone(size_group, "Expected a Size OptionGroup from Allbirds DOM")
        assert size_group is not None
        values = [o.value for o in size_group.options]
        self.assertIn("8", values)
        self.assertIn("10", values)
        self.assertIn("12", values)
        self.assertGreaterEqual(len(values), 5)

    def test_minimum_two_values_required(self) -> None:
        """A dimension with only one value is not promoted to an OptionGroup."""
        html = '<button aria-label="Size Option: Large"></button>'
        context = ExtractionContext()
        extract_dom_signals(html, context)
        self.assertEqual(context.option_group_candidates, [])

    def test_empty_html_produces_no_option_groups(self) -> None:
        context = ExtractionContext()
        extract_dom_signals("", context)
        self.assertEqual(context.option_group_candidates, [])


class TestDomFalsePositiveFilter(unittest.TestCase):

    def test_article_produces_no_option_groups(self) -> None:
        """Article page: country selector listbox does not produce an OptionGroup."""
        context = _context_with_dom("article.html")
        self.assertEqual(
            context.option_group_candidates,
            [],
            f"Expected no option groups for Article, got {context.option_group_candidates}",
        )

    def test_nike_produces_no_option_groups(self) -> None:
        """Nike page: thumbnail radio inputs do not produce OptionGroups."""
        context = _context_with_dom("nike.html")
        # Thumbnail is in the non-product filter list
        thumbnail_group = _get_option_group(context, "Thumbnail")
        self.assertIsNone(thumbnail_group, "Thumbnail radio group should be filtered out")

    def test_non_product_dimension_names_are_blocked(self) -> None:
        """Known non-product dimensions (Country, Quantity, etc.) are filtered out."""
        html = """
        <button aria-label="Country Option: USA"></button>
        <button aria-label="Country Option: Canada"></button>
        <button aria-label="Quantity Option: 1"></button>
        <button aria-label="Quantity Option: 2"></button>
        """
        context = ExtractionContext()
        extract_dom_signals(html, context)
        self.assertEqual(context.option_group_candidates, [])

    def test_product_dimension_passes_through(self) -> None:
        """Valid product dimensions are not incorrectly filtered."""
        html = """
        <button aria-label="Size Option: Small"></button>
        <button aria-label="Size Option: Medium"></button>
        <button aria-label="Size Option: Large"></button>
        """
        context = ExtractionContext()
        extract_dom_signals(html, context)
        size_group = _get_option_group(context, "Size")
        self.assertIsNotNone(size_group)


class TestDomAvailability(unittest.TestCase):

    def test_schema_org_instock_is_normalised(self) -> None:
        """itemprop=availability with a schema.org URL is stripped to the token."""
        html = '<link itemprop="availability" content="https://schema.org/InStock">'
        context = ExtractionContext()
        extract_dom_signals(html, context)
        self.assertEqual(context.raw_attributes.get("dom_availability"), "InStock")

    def test_short_availability_value_stored_as_is(self) -> None:
        """Non-URL availability values are stored directly."""
        html = '<link itemprop="availability" content="OutOfStock">'
        context = ExtractionContext()
        extract_dom_signals(html, context)
        self.assertEqual(context.raw_attributes.get("dom_availability"), "OutOfStock")

    def test_no_availability_leaves_raw_attributes_unchanged(self) -> None:
        context = ExtractionContext()
        extract_dom_signals("<div>no availability here</div>", context)
        self.assertNotIn("dom_availability", context.raw_attributes)


class TestDomOptionGroupMerging(unittest.TestCase):

    def test_add_option_group_merges_same_dimension(self) -> None:
        """add_option_group merges into an existing group of the same dimension."""
        html = """
        <button aria-label="Size Option: Small"></button>
        <button aria-label="Size Option: Medium"></button>
        """
        context = ExtractionContext()
        extract_dom_signals(html, context)
        # Add another group with overlapping + new values
        from models import OptionGroup, OptionValue
        context.add_option_group(
            OptionGroup(dimension="Size", options=[
                OptionValue(value="Medium"),  # duplicate
                OptionValue(value="Large"),   # new
            ])
        )
        size_group = _get_option_group(context, "Size")
        self.assertIsNotNone(size_group)
        assert size_group is not None
        values = [o.value for o in size_group.options]
        self.assertIn("Small", values)
        self.assertIn("Medium", values)
        self.assertIn("Large", values)
        self.assertEqual(values.count("Medium"), 1, "Medium should appear exactly once")
