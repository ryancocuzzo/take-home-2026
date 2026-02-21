"""
Seed script: runs the extraction pipeline for all products and writes
structured JSON to data/products/{id}.json.

Usage:
    uv run python seed.py
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from backend.assemble import assemble_product
from backend.corpus import DATA_DIR, PAGES, PRODUCTS_DIR
from backend.extract import extract_dom_signals, extract_structured_signals
from backend.taxonomy import select_category_candidates
from models import Product

logger = logging.getLogger(__name__)


def product_id(filename: str, url: str | None) -> str:
    key = url if url is not None else Path(filename).stem
    return hashlib.sha256(key.encode()).hexdigest()[:12]


async def seed_page(filename: str, url: str | None) -> tuple[str, Product]:
    html = (DATA_DIR / filename).read_text()
    context = extract_structured_signals(html, page_url=url)
    extract_dom_signals(html, context, page_url=url)
    candidates = select_category_candidates(context)
    product = await assemble_product(context, candidates)
    pid = product_id(filename, url)
    return pid, product


def _write_product(pid: str, product: Product) -> None:
    out_path = PRODUCTS_DIR / f"{pid}.json"
    out_path.write_text(product.model_dump_json(indent=2))
    logger.info("Wrote %s", out_path.name)


async def seed_all() -> dict[str, Product]:
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Seeding %d pages...", len(PAGES))
    results = await asyncio.gather(
        *[seed_page(filename, url) for filename, url in PAGES],
        return_exceptions=True,
    )

    seeded: dict[str, Product] = {}
    for (filename, _), result in zip(PAGES, results):
        if isinstance(result, BaseException):
            logger.error("Failed to seed %s: %s", filename, result)
            continue
        pid, product = result
        _write_product(pid, product)
        seeded[pid] = product

    logger.info("Seeded %d/%d products.", len(seeded), len(PAGES))
    return seeded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed_all())
