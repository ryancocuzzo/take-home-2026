import re
from typing import Any, Literal
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator

# Load categories once at module level
CATEGORIES_FILE = Path(__file__).parent / "categories.txt"
VALID_CATEGORIES = set()
if CATEGORIES_FILE.exists():
    with open(CATEGORIES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                VALID_CATEGORIES.add(line)

class Category(BaseModel):
    # A category from Google's Product Taxonomy
    # https://www.google.com/basepages/producttype/taxonomy.en-US.txt
    name: str

    @field_validator("name")
    @classmethod
    def validate_name_exists(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"Category '{v}' is not a valid category in categories.txt")
        return v

class Price(BaseModel):
    price: float
    currency: str
    compare_at_price: float | None = None

    @field_validator("price", "compare_at_price", mode="before")
    @classmethod
    def _coerce_price_string(cls, v: object) -> object:
        """
        Extract a numeric value from LLM output that may include currency symbols,
        codes, or non-breaking spaces (e.g. "170\xa0USD", "$29.95", "EUR 49").
        """
        if v is None or isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            match = re.search(r"\d+(?:[.,]\d+)?", v.replace("\xa0", " "))
            if match:
                return float(match.group().replace(",", "."))
        return v


class OptionValue(BaseModel):
    value: str
    available: bool = True
    price_delta: float | None = None


class OptionGroup(BaseModel):
    dimension: str  # e.g. "Size", "Color", "Material"
    options: list[OptionValue]


class Variant(BaseModel):
    name: str
    attributes: dict[str, str] = Field(default_factory=dict)
    price: Price | None = None
    availability: str | None = None


class Merchant(BaseModel):
    name: str
    merchant_id: str | None = None


class Offer(BaseModel):
    merchant: Merchant
    price: Price
    availability: str | None = None
    shipping: str | None = None
    promo: str | None = None
    source_url: str | None = None


class MatchEvidence(BaseModel):
    signal: Literal[
        "upc_gtin_exact_match",
        "title_brand_similarity",
    ]
    score: float = Field(ge=0.0, le=1.0)
    matched: bool
    details: dict[str, Any] = Field(default_factory=dict)


class MatchDecision(BaseModel):
    candidate_product_id: str | None = None
    matched: bool
    confidence: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    evidence: list[MatchEvidence] = Field(default_factory=list)


class Product(BaseModel):
    name: str
    price: Price
    description: str
    key_features: list[str]
    image_urls: list[str]
    video_url: str | None = None
    category: Category
    brand: str
    colors: list[str]
    variants: list[Variant] = Field(default_factory=list)
    offers: list[Offer] = Field(default_factory=list)
    canonical_product_id: str | None = None
    match_decision: MatchDecision | None = None

    @model_validator(mode="after")
    def _ensure_offer_exists(self) -> "Product":
        """
        Backward-compatible bridge: if upstream extraction populates legacy
        product-level brand/price fields but omits offers, synthesize a primary
        offer so API consumers can rely on merchant-scoped offer data.
        """
        if self.offers:
            return self
        self.offers = [
            Offer(
                merchant=Merchant(name=self.brand),
                price=self.price,
            )
        ]
        return self


class ProductSummary(BaseModel):
    id: str
    name: str
    brand: str
    price: Price
    category: Category
    image_url: str | None = None


class ExtractionContext(BaseModel):
    """
    Intermediate candidate bag produced by deterministic extraction passes.
    The LLM assembler resolves these into a final Product.
    """

    page_url: str | None = None

    # Core product signals
    title_candidates: list[str] = Field(default_factory=list)
    description_candidates: list[str] = Field(default_factory=list)
    brand_candidates: list[str] = Field(default_factory=list)
    price_candidates: list[str] = Field(default_factory=list)
    currency_candidates: list[str] = Field(default_factory=list)
    image_url_candidates: list[str] = Field(default_factory=list)

    # Secondary enrichment signals
    category_hint_candidates: list[str] = Field(default_factory=list)
    key_feature_candidates: list[str] = Field(default_factory=list)

    # Structured variation dimensions (Color, Size, Material, etc.)
    # Each OptionGroup represents one axis of product variation with its available values.
    option_group_candidates: list[OptionGroup] = Field(default_factory=list)

    # Raw passthrough attributes for LLM reasoning (debug overflow)
    raw_attributes: dict[str, Any] = Field(default_factory=dict)

    _CANDIDATE_FIELDS = {
        "title_candidates",
        "description_candidates",
        "brand_candidates",
        "price_candidates",
        "currency_candidates",
        "image_url_candidates",
        "category_hint_candidates",
        "key_feature_candidates",
    }

    def add_candidates(self, field_name: str, values: list[str]) -> None:
        if field_name not in self._CANDIDATE_FIELDS:
            raise ValueError(f"Unknown candidate field: {field_name}")
        self.merge_unique(field_name, values)

    def add_raw_attribute(self, key: str, value: str | int | float | bool) -> None:
        self.raw_attributes[key] = value

    def add_option_group(self, group: OptionGroup) -> None:
        """
        Add an OptionGroup, merging into an existing group of the same dimension
        (case-insensitive) rather than creating a duplicate.
        """
        for existing in self.option_group_candidates:
            if existing.dimension.lower() == group.dimension.lower():
                seen = {o.value for o in existing.options}
                for opt in group.options:
                    if opt.value not in seen:
                        existing.options.append(opt)
                        seen.add(opt.value)
                return
        self.option_group_candidates.append(group)

    def merge_unique(self, field_name: str, values: list[str]) -> None:
        """
        Append unique non-empty string values into a list field while preserving order.
        """
        existing = getattr(self, field_name)
        seen = set(existing)
        for value in values:
            if not isinstance(value, str):
                continue
            cleaned = value.strip()
            if not cleaned or cleaned in seen:
                continue
            existing.append(cleaned)
            seen.add(cleaned)