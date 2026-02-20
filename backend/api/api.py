"""
Read-only product API.
"""

from fastapi import FastAPI, HTTPException

from backend.corpus import PRODUCTS_DIR
from models import Product, ProductSummary
from pathlib import Path

app = FastAPI(title="Product Catalog API")


def _load_product(path: Path) -> Product:
    return Product.model_validate_json(path.read_text())


@app.get("/products", response_model=list[ProductSummary])
def list_products() -> list[ProductSummary]:
    if not PRODUCTS_DIR.exists():
        return []
    summaries: list[ProductSummary] = []
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        product = _load_product(path)
        summaries.append(
            ProductSummary(
                id=path.stem,
                name=product.name,
                brand=product.brand,
                price=product.price,
                category=product.category,
                image_url=product.image_urls[0] if product.image_urls else None,
            )
        )
    return summaries


@app.get("/products/{product_id}", response_model=Product)
def get_product(product_id: str) -> Product:
    path = PRODUCTS_DIR / f"{product_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return _load_product(path)
