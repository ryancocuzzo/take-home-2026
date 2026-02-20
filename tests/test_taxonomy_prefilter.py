"""Tests for taxonomy pre-filter (TF-IDF + cosine)."""

import unittest

from backend.taxonomy.prefilter import select_category_candidates
from models import ExtractionContext


class TestTaxonomyPrefilter(unittest.TestCase):
    def test_ranks_relevant_footwear_categories_for_nike_like_context(self) -> None:
        # Arrange
        categories = [
            "Apparel & Accessories > Clothing",
            "Apparel & Accessories > Shoes",
            "Furniture > Lighting",
            "Sporting Goods > Exercise & Fitness > Boxing & Martial Arts",
        ]
        context = ExtractionContext(
            title_candidates=["Nike Air Force 1 Men's Shoes"],
            brand_candidates=["Nike"],
            category_hint_candidates=["Shoes"],
        )

        # Act
        ranked = select_category_candidates(context, categories=categories, top_k=3)

        # Assert
        self.assertIn("Apparel & Accessories > Shoes", ranked[:2])

    def test_category_hints_improve_retrieval_relevance(self) -> None:
        # Arrange
        categories = [
            "Apparel & Accessories > Clothing",
            "Furniture > Lighting",
            "Home & Garden > Lamps",
        ]
        context = ExtractionContext(
            title_candidates=["Pilar lamp"],
            brand_candidates=["Article"],
            category_hint_candidates=["Lighting"],
        )

        # Act
        ranked = select_category_candidates(context, categories=categories, top_k=3)

        # Assert
        self.assertEqual(ranked[0], "Furniture > Lighting")

    def test_returns_deterministic_top_level_fallback_for_zero_overlap(self) -> None:
        # Arrange
        categories = [
            "Animals & Pet Supplies > Pet Supplies > Dog Supplies",
            "Apparel & Accessories > Clothing",
            "Apparel & Accessories > Shoes",
            "Home & Garden > Decor",
        ]
        context = ExtractionContext(
            title_candidates=["zzqv unknown token"],
            brand_candidates=[],
            category_hint_candidates=[],
        )

        # Act
        ranked = select_category_candidates(context, categories=categories, top_k=4)

        # Assert
        self.assertEqual(
            ranked[:3],
            ["Animals & Pet Supplies", "Apparel & Accessories", "Home & Garden"],
        )

    def test_respects_top_k_and_returns_unique_taxonomy_values(self) -> None:
        # Arrange
        categories = [
            "Apparel & Accessories > Shoes",
            "Apparel & Accessories > Shoes",
            "Apparel & Accessories > Clothing",
            "Home & Garden > Decor",
        ]
        context = ExtractionContext(
            title_candidates=["men shoes"],
            brand_candidates=["nike"],
            category_hint_candidates=[],
        )

        # Act
        ranked = select_category_candidates(context, categories=categories, top_k=2)

        # Assert
        self.assertEqual(len(ranked), 2)
        self.assertEqual(len(set(ranked)), 2)
        self.assertTrue(all(category in set(categories) for category in ranked))


if __name__ == "__main__":
    unittest.main()
