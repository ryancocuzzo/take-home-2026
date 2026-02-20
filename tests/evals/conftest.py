"""
Eval-suite conftest: accumulate token usage across all LLM calls and print
a cost summary at session teardown.

How it works:
- The `_log_usage` function in ai.py is called after every ai.responses() call
  and already has access to token counts and model name.
- We monkey-patch it to also push a UsageRecord into a session-level list.
- At teardown, we compute and print a cost table using the MODEL_PRICES dict
  that already lives in ai.py — no duplicated pricing data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import ai


@dataclass
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> float:
        prices = ai.MODEL_PRICES.get(self.model, {"input": 0.0, "output": 0.0})
        return (self.input_tokens / 1_000_000) * prices["input"] + (
            self.output_tokens / 1_000_000
        ) * prices["output"]


@dataclass
class _UsageAccumulator:
    records: list[UsageRecord] = field(default_factory=list)

    def push(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        model = getattr(response, "model", "unknown")
        self.records.append(
            UsageRecord(
                model=model,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            )
        )

    def print_summary(self) -> None:
        if not self.records:
            print("\n[evals] No LLM calls recorded.")
            return

        total_input = sum(r.input_tokens for r in self.records)
        total_output = sum(r.output_tokens for r in self.records)
        total_cost = sum(r.cost for r in self.records)

        print("\n" + "=" * 60)
        print(f"{'[evals] LLM cost summary':^60}")
        print("=" * 60)
        print(f"{'Call':<6} {'Model':<40} {'In tok':>7} {'Out tok':>8} {'Cost':>10}")
        print("-" * 60)
        for i, rec in enumerate(self.records, start=1):
            model_short = rec.model.split("/")[-1]
            print(
                f"{i:<6} {model_short:<40} {rec.input_tokens:>7} "
                f"{rec.output_tokens:>8} ${rec.cost:>9.6f}"
            )
        print("-" * 60)
        print(
            f"{'TOTAL':<6} {'':<40} {total_input:>7} "
            f"{total_output:>8} ${total_cost:>9.6f}"
        )
        print("=" * 60)


@pytest.fixture(scope="session")
def usage_accumulator() -> _UsageAccumulator:
    return _UsageAccumulator()


@pytest.fixture(scope="session", autouse=True)
def _patch_log_usage(usage_accumulator: _UsageAccumulator):
    """
    Wrap ai._log_usage so token counts are captured in the accumulator
    in addition to being written to the logger as normal.
    """
    original = ai._log_usage

    def patched(response) -> None:
        original(response)
        usage_accumulator.push(response)

    ai._log_usage = patched
    yield
    ai._log_usage = original
    usage_accumulator.print_summary()
