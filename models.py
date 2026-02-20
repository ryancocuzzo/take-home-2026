from typing import Any
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

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
    # If a product is on sale, this is the original price
    compare_at_price: float | None = None

# This is the final product schema that you need to output. 
# You may add additional models as needed.
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
    variants: list[Any] # TODO (@dev): Define variant model


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
    color_candidates: list[str] = Field(default_factory=list)

    # Raw passthrough attributes for LLM reasoning
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
        "color_candidates",
    }

    def add_candidates(self, field_name: str, values: list[str]) -> None:
        if field_name not in self._CANDIDATE_FIELDS:
            raise ValueError(f"Unknown candidate field: {field_name}")
        self.merge_unique(field_name, values)

    def add_raw_attribute(self, key: str, value: str | int | float | bool) -> None:
        self.raw_attributes[key] = value

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