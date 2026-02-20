"""
Unit tests for the LLM assembler.

These tests cover the deterministic parts of backend/assemble.py:
  - build_prompt: prompt structure and content
  - assemble_product: retry logic when the first call raises ValidationError

No real LLM calls are made here. ai.responses is patched via unittest.mock.
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from backend.assemble import assemble_product, build_prompt
from models import Category, ExtractionContext, Price, Product, Variant


def _make_context(
    titles: list[str] | None = None,
    prices: list[str] | None = None,
    images: list[str] | None = None,
    brands: list[str] | None = None,
) -> ExtractionContext:
    ctx = ExtractionContext()
    if titles:
        ctx.add_candidates("title_candidates", titles)
    if prices:
        ctx.add_candidates("price_candidates", prices)
    if images:
        ctx.add_candidates("image_url_candidates", images)
    if brands:
        ctx.add_candidates("brand_candidates", brands)
    return ctx


def _make_valid_product() -> Product:
    return Product(
        name="Test Drill",
        price=Price(price=129.00, currency="USD"),
        description="A reliable cordless drill.",
        key_features=["20V battery", "Compact design"],
        image_urls=["https://example.com/drill.jpg"],
        category=Category(name="Hardware > Tool Accessories > Drill & Screwdriver Accessories"),
        brand="DeWalt",
        colors=[],
        variants=[],
    )


def _make_validation_error() -> ValidationError:
    """Produce a real ValidationError by attempting to create a Category with an invalid name."""
    try:
        Category(name="__not_a_real_category__")
    except ValidationError as exc:
        return exc
    raise AssertionError("Expected ValidationError was not raised")


class TestBuildPrompt(unittest.TestCase):
    """build_prompt is deterministic — test structure and required content."""

    def setUp(self) -> None:
        self.context = _make_context(
            titles=["Cordless Drill"],
            prices=["129.00"],
            images=["https://example.com/drill.jpg"],
            brands=["DeWalt"],
        )
        self.candidates = [
            "Hardware > Tools > Power Tools > Drills",
            "Sporting Goods > Outdoor Recreation",
        ]

    def test_returns_system_and_user_messages(self) -> None:
        messages = build_prompt(self.context, self.candidates)

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")

    def test_prompt_contains_numbered_category_list(self) -> None:
        messages = build_prompt(self.context, self.candidates)
        user_content = messages[1]["content"]

        for i, cat in enumerate(self.candidates, start=1):
            self.assertIn(f"{i}. {cat}", user_content)

    def test_prompt_contains_context_json(self) -> None:
        messages = build_prompt(self.context, self.candidates)
        user_content = messages[1]["content"]

        # The context is embedded as JSON — spot-check a known field value
        self.assertIn("Cordless Drill", user_content)
        self.assertIn("129.00", user_content)
        self.assertIn("https://example.com/drill.jpg", user_content)

    def test_system_prompt_instructs_no_url_hallucination(self) -> None:
        messages = build_prompt(self.context, self.candidates)
        system_content = messages[0]["content"]

        self.assertIn("Do NOT invent", system_content)

    def test_system_prompt_instructs_exact_category_copy(self) -> None:
        messages = build_prompt(self.context, self.candidates)
        system_content = messages[0]["content"]

        self.assertIn("character-for-character", system_content)

    def test_no_validation_error_section_by_default(self) -> None:
        messages = build_prompt(self.context, self.candidates)
        user_content = messages[1]["content"]

        self.assertNotIn("Validation error", user_content)

    def test_validation_error_appended_when_provided(self) -> None:
        error_text = "Category 'Bogus' is not valid"
        messages = build_prompt(self.context, self.candidates, validation_error=error_text)
        user_content = messages[1]["content"]

        self.assertIn(error_text, user_content)
        self.assertIn("Validation error from previous attempt", user_content)


class TestAssembleProductRetry(unittest.IsolatedAsyncioTestCase):
    """assemble_product retry logic — ai.responses is mocked."""

    def setUp(self) -> None:
        self.context = _make_context(
            titles=["Cordless Drill"],
            prices=["129.00"],
            images=["https://example.com/drill.jpg"],
        )
        self.candidates = ["Hardware > Tools > Power Tools > Drills"]

    async def test_returns_product_on_first_success(self) -> None:
        valid_product = _make_valid_product()

        with patch("backend.assemble.ai.responses", new=AsyncMock(return_value=valid_product)):
            result = await assemble_product(self.context, self.candidates)

        self.assertEqual(result.name, "Test Drill")

    async def test_retries_once_on_validation_error(self) -> None:
        valid_product = _make_valid_product()
        validation_error = _make_validation_error()

        mock_responses = AsyncMock(side_effect=[validation_error, valid_product])

        with patch("backend.assemble.ai.responses", new=mock_responses):
            result = await assemble_product(self.context, self.candidates)

        self.assertEqual(mock_responses.call_count, 2)
        self.assertEqual(result.name, "Test Drill")

    async def test_retry_prompt_contains_validation_error_text(self) -> None:
        valid_product = _make_valid_product()
        validation_error = _make_validation_error()

        mock_responses = AsyncMock(side_effect=[validation_error, valid_product])

        with patch("backend.assemble.ai.responses", new=mock_responses):
            await assemble_product(self.context, self.candidates)

        # Second call's input (messages) should contain the error string
        second_call_messages = mock_responses.call_args_list[1].args[1]
        user_content = second_call_messages[1]["content"]
        self.assertIn("Validation error from previous attempt", user_content)
        self.assertIn("__not_a_real_category__", user_content)

    async def test_propagates_exception_after_two_failures(self) -> None:
        validation_error = _make_validation_error()

        mock_responses = AsyncMock(side_effect=[validation_error, validation_error])

        with patch("backend.assemble.ai.responses", new=mock_responses):
            with self.assertRaises(ValidationError):
                await assemble_product(self.context, self.candidates)

        self.assertEqual(mock_responses.call_count, 2)
