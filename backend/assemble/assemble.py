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

import logging

from pydantic import BaseModel, Field, ValidationError

import ai
from models import ExtractionContext, Offer, Price, Product, Variant

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
- colors: derive from option_group_candidates where dimension is "Color". List all
  option values from that group. Empty list if no Color group is present.
- category_choice: choose exactly one category by 1-based index from the
  numbered list (1 = first item, 2 = second item, etc.). Do not output a
  free-form category string.
- variants: use option_group_candidates to build Variant objects. Generate ONLY
  variants that are meaningfully distinct — where availability or price differs
  across known combinations, or where the combination has a recognised proper name.
  Do NOT enumerate the full cartesian product of all dimensions.
  Each variant needs a human-readable name (e.g. "Red / M") and an attributes
  dict (e.g. {"color": "Red", "size": "M"}). If no option groups exist, return [].
"""


class _AssembledProductDraft(BaseModel):
    name: str
    price: Price
    description: str
    key_features: list[str]
    image_urls: list[str]
    video_url: str | None = None
    category_choice: int = Field(ge=1)
    brand: str
    colors: list[str]
    variants: list[Variant] = Field(default_factory=list)
    offers: list[Offer] = Field(default_factory=list)


def _materialize_product(
    draft: _AssembledProductDraft, category_candidates: list[str]
) -> Product:
    if not category_candidates:
        raise ValueError("category_candidates must not be empty")

    idx = draft.category_choice - 1
    if idx < 0 or idx >= len(category_candidates):
        raise ValueError(
            f"Invalid category_choice={draft.category_choice}; "
            f"expected 1..{len(category_candidates)}"
        )

    payload = draft.model_dump()
    payload["category"] = {"name": category_candidates[idx]}
    payload.pop("category_choice", None)
    return Product.model_validate(payload)


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
## Category candidates (choose exactly one by 1-based index)

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
        draft = await ai.responses(_MODEL, messages, text_format=_AssembledProductDraft)
        return _materialize_product(draft, category_candidates)
    except ValidationError as exc:
        logger.warning("Assembler: ValidationError on first attempt, retrying. Error: %s", exc)
        retry_messages = build_prompt(
            context, category_candidates, validation_error=str(exc)
        )
        draft = await ai.responses(
            _MODEL, retry_messages, text_format=_AssembledProductDraft
        )
        return _materialize_product(draft, category_candidates)
