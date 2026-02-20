"""
LLM assembler: resolves ExtractionContext candidates into a validated Product.

This is the final step of the extraction pipeline. It takes the candidate bag
produced by Pass 1 (structured signal extraction) and the top-k category
candidates from the taxonomy pre-filter, and asks the LLM to produce a single
coherent Product using structured output.

Retry strategy: if Pydantic raises a ValidationError during parsing (most
commonly because the LLM chose a category string not in the taxonomy), the
error is appended to the prompt and the call is retried once. Any failure after
the retry propagates to the caller.
"""

import json
import logging

from pydantic import ValidationError

import ai
from models import ExtractionContext, Product

logger = logging.getLogger(__name__)

_MODEL = "google/gemini-2.0-flash-lite-001"

_SYSTEM_PROMPT = """\
You are a product data assembler. You will be given structured signals extracted
from a product page and a numbered list of plausible taxonomy categories.

Your job is to produce a single, valid Product object.

Rules:
- name: choose the most accurate and complete title from title_candidates.
- description: choose or lightly combine the best description from description_candidates.
- brand: choose the most credible brand from brand_candidates. If brand_candidates
  is empty or unhelpful, infer the brand from other signals (description, title,
  page URL domain, or breadcrumbs). For a retailer's own private-label products,
  the retailer name is the brand.
- price: parse the best price string from price_candidates into a numeric float.
  Use currency_candidates to determine the currency code (e.g. "USD", "GBP").
  If a sale price and original price are both present, set compare_at_price to the higher value.
- image_urls: use only URLs from image_url_candidates. Do NOT invent or modify URLs.
- key_features: extract a concise list of bullet-point features from key_feature_candidates
  or the description. Empty list is acceptable if none are present.
- colors: list ALL available color options from color_candidates. Include hex codes (e.g. #888888), colorway names (e.g. Red, Grey/Blue), and swatch names. Exclude entries that are product titles or variant names (e.g. "Product Name - Color / Size"). Deduplicate similar colors (e.g. "Red/White" and "White/Red" are the same). Empty list only if color_candidates is empty.
- category: you MUST choose the exact string of one item from the numbered
  category list provided. Copy it character-for-character. Do not paraphrase.
- variants: if option groups (e.g. sizes, colours) are present in raw_attributes,
  build Variant objects from them. Each variant needs a human-readable name
  (e.g. "Red / M") and an attributes dict (e.g. {"color": "Red", "size": "M"}).
  Cap variants at 50. If no option groups exist, return an empty list.
"""


def build_prompt(
    context: ExtractionContext,
    category_candidates: list[str],
    *,
    validation_error: str | None = None,
) -> list[dict]:
    """
    Build the message list for the LLM call.

    Returns a two-element list: system message + user message.
    If validation_error is provided it is appended so the model can self-correct.
    """
    numbered = "\n".join(
        f"{i + 1}. {cat}" for i, cat in enumerate(category_candidates)
    )

    user_content = f"""\
## Category candidates (choose exactly one, copy the string verbatim)

{numbered}

## Extraction signals (JSON)

{context.model_dump_json(indent=2)}
"""

    if validation_error:
        user_content += f"""
## Validation error from previous attempt — fix this

{validation_error}
"""

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def assemble_product(
    context: ExtractionContext,
    category_candidates: list[str],
) -> Product:
    """
    Assemble a validated Product from extraction signals and category candidates.

    Makes one structured LLM call. On ValidationError, retries once with the
    error appended to the prompt. Any exception after the retry propagates.
    """
    messages = build_prompt(context, category_candidates)

    try:
        return await ai.responses(_MODEL, messages, text_format=Product)
    except ValidationError as exc:
        logger.warning("Assembler: ValidationError on first attempt, retrying. Error: %s", exc)
        retry_messages = build_prompt(
            context, category_candidates, validation_error=str(exc)
        )
        return await ai.responses(_MODEL, retry_messages, text_format=Product)
