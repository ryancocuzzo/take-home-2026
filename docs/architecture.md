# Architecture

This document covers the component-level design of the extraction pipeline. For a high-level overview, see the [README](../README.md).

## Pipeline Overview

```
Raw HTML → Pass 1 (structured signals) → ExtractionContext → Taxonomy pre-filter
                                                           → LLM assembler → Product
```

Each stage has a single responsibility and a clean interface. Passes produce candidates; the assembler resolves them. This separation means any pass can be replaced or extended without touching the others.

---

## Pass 1: Structured Signal Extraction

**Module:** `backend/extract/`

Pulls from three signal sources in priority order, all parsed unconditionally — no site detection.

**JSON-LD** is the richest source when present. It's explicit, typed, and standardized (schema.org). Most e-commerce sites include it for SEO. The parser walks all `@graph` nodes and standalone objects, extracting fields via a declarative mapping table (`MappingRules`).

**Meta tags** (Open Graph, Twitter Cards, standard `<meta>`) are a reliable fallback for title, description, and primary image. Nearly universal across sites.

**Script blobs** handle the case where a site bundles product state into JavaScript — `window.__INITIAL_STATE__ = {...}` or Next.js `__NEXT_DATA__`. The parser uses a generic regex pattern (`identifier = {json}`) that covers most SPAs without site-specific logic. `application/json` script tags are also parsed.

All image URLs are resolved to absolute and deduplicated by normalized URL (resize parameters stripped via `UrlNormalizer`). Deduplication happens here, not in the LLM.

### Trade-offs

This pass is cheap and deterministic but produces *candidates*, not a product. It doesn't pick the best title or resolve ambiguity — that's the LLM's job. The split matters: deterministic code shouldn't do semantic reasoning, and LLMs shouldn't do URL parsing.

### Failure modes

- **JS-rendered pages** (fetched via curl): JSON-LD and meta tags are usually still in the raw HTML. Script blobs may be absent if the bundle loads asynchronously. Output is sparse but valid.
- **Malformed JSON** in script blobs: caught and skipped silently. Not fatal.
- **Relative image URLs** without a page URL: resolved best-effort; may be incorrect if the base path is unusual.

---

## ExtractionContext

**Module:** `models.py`

The intermediate candidate bag passed between passes and into the assembler. It holds lists — title might have three candidates, images might have fifteen. Nothing is resolved yet.

This design decouples extraction passes from assembly. Either can change independently. The context keeps candidate fields loosely typed (`list[str]` for unresolved text candidates) while preserving structured variation dimensions via `OptionGroup`.

```python
class ExtractionContext(BaseModel):
    title_candidates: list[str]
    description_candidates: list[str]
    brand_candidates: list[str]
    price_candidates: list[str]
    currency_candidates: list[str]
    image_url_candidates: list[str]
    category_hint_candidates: list[str]
    key_feature_candidates: list[str]
    option_group_candidates: list[OptionGroup]
    raw_attributes: dict[str, Any]
```

### Failure modes

- **Empty context** (all passes fail): the assembler receives empty candidate lists. The LLM will return a nearly-empty Product. `name` and `price` are required — if truly absent, the pipeline raises and the product is skipped.

---

## Taxonomy Pre-filter

**Module:** `backend/taxonomy/`

Google's product taxonomy has ~5,600 categories. Passing all of them to the LLM every call is expensive and noisy. The pre-filter reduces this to ~20 candidates using BM25 scoring against the product title, brand, and top breadcrumb terms.

BM25 improves on raw token overlap in two ways:
- **Term saturation:** repeating a word gives diminishing returns (a category with "shoes shoes shoes" doesn't score 3x).
- **Document-length normalization:** short category labels aren't penalized for being short.

The index is built once per unique category set and cached via `@lru_cache`. Query tokens are drawn from title candidates (capped at 3), brand candidates (capped at 2), and category hints (capped at 3) to prevent any single noisy signal from dominating.

If the top candidate scores 0 (zero vocabulary overlap), the filter returns a diverse spread of top-level taxonomy segments as a broader fallback.

### Trade-offs

BM25 is keyword-based — it won't rank "Apparel & Accessories > Shoes" above "Apparel & Accessories > Clothing" for a sneaker unless the word "shoes" appears in the signals. The pre-filter only needs to get the right answer *into the top 20*; the LLM makes the final selection.

Alternatives considered:
- **scikit-learn TF-IDF:** easy to implement, great community support, but pulls in numpy + scipy — massive dependencies for one function.
- **Hand-rolled scoring:** no dependencies, but means maintaining non-trivial ranking math.
- **Semantic embeddings:** better recall, but adds latency and an embedding model dependency. BM25 covers the use case.

### Failure modes

- **No vocabulary overlap:** fallback to broad segments. The LLM picks the closest one — may be imprecise but will be valid.
- **Brand name matches unrelated category tokens:** surfaces irrelevant candidates. Rarely matters — the LLM ignores bad candidates when better ones are present.

---

## LLM Assembler

**Module:** `backend/assemble/`

A single async call to `gemini-2.0-flash-lite` using structured output (`text_format=Product`). The prompt provides the full `ExtractionContext` as JSON and the top 20 category candidates as a numbered list.

The LLM is responsible for:
- Selecting the best title, description, and brand from candidates
- Picking the exact category string from the numbered list
- Building `Variant` objects from option groups (capped at 50)
- Normalizing price strings into `Price`
- Inferring brand from context when `brand_candidates` is empty

The LLM is *not* responsible for HTML parsing, URL resolution, or deduplication. Those are done before it sees anything.

### Prompt design

System message carries invariant rules; user message carries variable data (numbered category list + ExtractionContext JSON). Stable rules separated from per-request data makes prompt changes easy to diff and test.

The category list is numbered and the model is instructed to copy the chosen string character-for-character. This minimizes the paraphrasing that would fail the taxonomy validator.

### Retry strategy

On `ValidationError`, retry once with the error message appended to the prompt. One retry covers the common case (category string mismatch). A retry loop would hide systematic prompt problems that need fixing, not more attempts.

### Trade-offs

`gemini-2.0-flash-lite` costs ~$0.005/call. If quality degrades on complex pages, the escalation path is flash-full, not a pipeline rewrite. Structured output is reliable on modern models but not perfect — the retry mechanism is the safety net.

### Failure modes

- **Structured output parse error:** retry once; if still failing, the error propagates.
- **LLM hallucinating image URLs:** prompt explicitly forbids this. Still possible — downstream image loading would 404.
- **Wrong category after retry:** logged and skipped. The Pydantic validator is the gate.

---

## Storage

**Module:** `data/products/`

Flat JSON files at `data/products/{id}.json` where `id = sha256(url)[:12]`. No database. The seed script writes them; the API reads them.

This is correct for the current scope (7 products). A database would add setup complexity, migrations, and a dependency for no benefit at this scale. The trade-off inverts at ~10K products where scan time and concurrent write safety matter.

---

## API

**Module:** `backend/api/`

Two read-only routes:
- `GET /products` — reads all JSON files, returns `list[ProductSummary]`
- `GET /products/{id}` — reads one file, returns `Product` (or 404)

The API layer contains zero business logic. Extraction lives in `backend/extract/`; the API is HTTP plumbing.

---

## Frontend

**Module:** `frontend/`

Next.js 16 with React 19 server components and shadcn/ui. Two pages:

- **Catalog** (`/`): responsive grid of `ProductCard` components. Each card shows image, brand, name, and price. Data fetched server-side from `GET /products`.
- **Product detail** (`/products/[id]`): `ImageGallery` with thumbnail navigation, `PriceDisplay` with sale price support, description, key features, color swatches, and category. Data fetched server-side from `GET /products/{id}`.

All data fetching happens in server components — no client-side API calls, no CORS configuration needed. The `NEXT_PUBLIC_API_URL` env var defaults to `http://localhost:8000`.
