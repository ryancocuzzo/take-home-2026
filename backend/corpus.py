"""
Paths and page registry for the sample product corpus.

Single source of truth for:
- DATA_DIR    — directory containing the raw HTML pages
- PRODUCTS_DIR — directory where seeded product JSON files are written/read
- PAGES        — the 7 product pages in the corpus (filename, canonical URL or None)
"""

from pathlib import Path

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
PRODUCTS_DIR: Path = DATA_DIR / "products"

# (html_filename, canonical_page_url | None)
# llbean.html has no canonical URL embedded in the HTML, so None is used as key.
PAGES: list[tuple[str, str | None]] = [
    ("ace.html", "https://www.acehardware.com/departments/tools/power-tools/cordless-drills/2385458"),
    ("llbean.html", None),
    ("nike.html", "https://www.nike.com/t/air-force-1-07-lv8-shoes"),
    ("article.html", "https://www.article.com/product/pilar-lamp"),
    ("adaysmarch.html", "https://www.adaysmarch.com/products/miller-trousers"),
    ("therealreal-gucci-bag.html", "https://www.therealreal.com/products/women/handbags/crossbody-bags/gucci-double-g-marmont-small-tkmwf"),
    ("allbirds-shoe.html", "https://www.allbirds.com/products/mens-dasher-nz"),
]
