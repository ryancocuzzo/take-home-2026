"""Unit tests for extraction components (script blob parsing, mapping)."""

import json
import unittest

from backend.extract.mapping import MappingRules, collect_candidates_from_node
from backend.extract.script_blob import iter_assigned_json_blobs
from models import ExtractionContext


class TestScriptBlobVarAssignment(unittest.TestCase):
    """var/let/const assignments are extracted (Shopify, etc.)."""

    def test_var_assignment_extracts_json_blob(self) -> None:
        script = 'var meta = {"product": {"variants": [{"id": 1, "public_title": "8"}]}};'
        blobs = iter_assigned_json_blobs(script)
        self.assertGreaterEqual(len(blobs), 1)
        self.assertIn("product", blobs[0])
        self.assertEqual(blobs[0]["product"]["variants"][0]["public_title"], "8")

    def test_window_double_underscore_still_works(self) -> None:
        script = 'window.__NEXT_DATA__ = {"props": {"pageProps": {}}};'
        blobs = iter_assigned_json_blobs(script)
        self.assertGreaterEqual(len(blobs), 1)
        self.assertIn("props", blobs[0])


class TestMappingStructuredPassthrough(unittest.TestCase):
    """variants, options etc. are JSON-serialized into raw_attributes."""

    def test_variants_nested_under_product_passthrough(self) -> None:
        node = {"product": {"variants": [{"id": 1, "public_title": "8"}]}}
        ctx = ExtractionContext()
        collect_candidates_from_node(node, ctx, MappingRules())

        self.assertIn("variants", ctx.raw_attributes)
        variants = json.loads(ctx.raw_attributes["variants"])
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["public_title"], "8")

    def test_options_passthrough(self) -> None:
        node = {"options": [{"name": "Size", "values": ["S", "M", "L"]}]}
        ctx = ExtractionContext()
        collect_candidates_from_node(node, ctx, MappingRules())

        self.assertIn("options", ctx.raw_attributes)
        options = json.loads(ctx.raw_attributes["options"])
        self.assertEqual(options[0]["name"], "Size")
