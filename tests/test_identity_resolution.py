import unittest
from unittest.mock import patch

from backend.identity import IdentityResolver, IdentityResolverConfig
from models import Category, Price, Product


_CATEGORY = "Hardware > Tool Accessories > Drill & Screwdriver Accessories"


def _make_product(
    *,
    name: str,
    brand: str,
    image_url: str,
    description: str = "",
    key_features: list[str] | None = None,
    colors: list[str] | None = None,
) -> Product:
    return Product(
        name=name,
        price=Price(price=129.0, currency="USD"),
        description=description or name,
        key_features=key_features or [],
        image_urls=[image_url],
        category=Category(name=_CATEGORY),
        brand=brand,
        colors=colors or [],
        variants=[],
    )


class TestIdentityResolution(unittest.TestCase):
    def test_high_confidence_match_with_shared_gtin(self) -> None:
        left = _make_product(
            name="DeWalt 20V Cordless Drill",
            brand="DeWalt",
            image_url="https://cdn.example.com/dewalt-drill-main.jpg",
            key_features=["UPC 012345678901", "Compact body"],
            colors=["Yellow"],
        )
        right = _make_product(
            name="DEWALT Cordless Drill 20V",
            brand="DEWALT",
            image_url="https://cdn.example.com/dewalt-drill-angle.jpg",
            key_features=["GTIN: 012345678901", "Compact body"],
            colors=["Yellow"],
        )

        resolver = IdentityResolver(
            IdentityResolverConfig(
                match_threshold=0.80,
                title_brand_min_similarity=0.62,
            )
        )
        resolved = resolver.assign_canonical_products({"p1": left, "p2": right})

        self.assertEqual(
            resolved["p1"].canonical_product_id,
            resolved["p2"].canonical_product_id,
        )
        self.assertIsNotNone(resolved["p1"].match_decision)
        assert resolved["p1"].match_decision is not None
        self.assertTrue(resolved["p1"].match_decision.matched)
        upc_evidence = next(
            e
            for e in resolved["p1"].match_decision.evidence
            if e.signal == "upc_gtin_exact_match"
        )
        self.assertTrue(upc_evidence.matched)
        self.assertEqual(upc_evidence.score, 1.0)

    def test_low_confidence_non_match(self) -> None:
        left = _make_product(
            name="DeWalt Cordless Drill",
            brand="DeWalt",
            image_url="https://cdn.example.com/dewalt-drill.jpg",
            key_features=["20V battery", "Compact"],
            colors=["Yellow"],
        )
        right = _make_product(
            name="Nike Air Force 1 Sneakers",
            brand="Nike",
            image_url="https://cdn.example.com/nike-af1.jpg",
            key_features=["Leather upper", "Rubber outsole"],
            colors=["White"],
        )

        resolver = IdentityResolver()
        resolved = resolver.assign_canonical_products({"left": left, "right": right})

        self.assertNotEqual(
            resolved["left"].canonical_product_id,
            resolved["right"].canonical_product_id,
        )
        self.assertIsNotNone(resolved["left"].match_decision)
        assert resolved["left"].match_decision is not None
        self.assertFalse(resolved["left"].match_decision.matched)
        self.assertLess(
            resolved["left"].match_decision.confidence,
            resolved["left"].match_decision.threshold,
        )

    def test_canonical_ids_are_stable_across_input_order(self) -> None:
        product_a = _make_product(
            name="Allbirds Dasher 2",
            brand="Allbirds",
            image_url="https://cdn.example.com/allbirds-dasher2.jpg",
            key_features=["SKU 100000000001"],
        )
        product_b = _make_product(
            name="Allbirds Dasher 2 Running Shoe",
            brand="Allbirds",
            image_url="https://cdn.example.com/allbirds-dasher2-side.jpg",
            key_features=["GTIN 100000000001"],
        )
        product_c = _make_product(
            name="Article Pilar Floor Lamp",
            brand="Article",
            image_url="https://cdn.example.com/article-pilar.jpg",
        )

        resolver = IdentityResolver()
        first = resolver.assign_canonical_products({"a": product_a, "b": product_b, "c": product_c})
        second = resolver.assign_canonical_products({"c": product_c, "b": product_b, "a": product_a})

        self.assertEqual(
            first["a"].canonical_product_id,
            second["a"].canonical_product_id,
        )
        self.assertEqual(
            first["b"].canonical_product_id,
            second["b"].canonical_product_id,
        )
        self.assertEqual(
            first["c"].canonical_product_id,
            second["c"].canonical_product_id,
        )

    def test_canonical_ids_stay_stable_when_names_drift(self) -> None:
        first_run = {
            "p1": _make_product(
                name="Miller Trousers",
                brand="A Day's March",
                image_url="https://cdn.example.com/miller-v1.jpg",
            ),
            "p2": _make_product(
                name="Pilar Floor Lamp - White Terrazzo",
                brand="Article",
                image_url="https://cdn.example.com/pilar-v1.jpg",
            ),
        }
        second_run = {
            "p1": _make_product(
                name="Miller Trousers - Relaxed Fit",
                brand="A Days March",
                image_url="https://cdn.example.com/miller-v2.jpg",
            ),
            "p2": _make_product(
                name="Pilar Floor Lamp, White Terrazzo",
                brand="Article",
                image_url="https://cdn.example.com/pilar-v2.jpg",
            ),
        }

        resolver = IdentityResolver()
        first = resolver.assign_canonical_products(first_run)
        second = resolver.assign_canonical_products(second_run)

        self.assertEqual(
            first["p1"].canonical_product_id,
            second["p1"].canonical_product_id,
        )
        self.assertEqual(
            first["p2"].canonical_product_id,
            second["p2"].canonical_product_id,
        )

    def test_thresholds_are_configurable_via_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "IDENTITY_MATCH_THRESHOLD": "0.93",
                "IDENTITY_TITLE_BRAND_MIN_SIMILARITY": "0.70",
            },
            clear=False,
        ):
            config = IdentityResolverConfig.from_env()

        self.assertEqual(config.match_threshold, 0.93)
        self.assertEqual(config.title_brand_min_similarity, 0.70)
