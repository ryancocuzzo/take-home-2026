# Architecture

Single source of truth for technical design. For discussion prep and decision rationale, see [design.md](design.md). For bugs and scope decisions, see [decisions.md](decisions.md).

---

## Pipeline

```
Raw HTML
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 1 · Structured Signal Extraction      (deterministic) │
│  JSON-LD  ·  meta tags  ·  script blobs                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 2 · DOM Extraction                    (deterministic) │
│  price text  ·  option groups  ·  availability              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                  ExtractionContext
              (candidate bag — nothing resolved yet)
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         │
  Taxonomy Pre-filter                   │
  BM25 → top 20 categories             │
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM Assembler                                              │
│  gemini-2.0-flash-lite · structured output                  │
│  candidates + category list → Product                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                  Validated Product (Pydantic)
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
        data/products/           FastAPI
          {id}.json         GET /products
                            GET /products/{id}
                                       │
                                       ▼
                                  Next.js UI
                             Catalog  ·  PDP
```

Each stage has a single responsibility. Passes produce candidates; the assembler resolves them. Any pass can be replaced or extended without touching the others.

---

## Pass 1 · Structured Signal Extraction

**Module:** `backend/extract/`

Pulls from three signal sources, all parsed unconditionally — no site detection.

### JSON-LD (`application/ld+json` script tags)

The richest source when present: explicit, typed, and standardized (schema.org). Most e-commerce sites embed it for SEO. The parser walks all `@graph` nodes and standalone objects. Fields are extracted via a declarative `MappingRules` table — a plain `dict[json_key → candidate_field]` — so supporting a new JSON key vocabulary is a one-line dict change, not a code branch.

`BreadcrumbList` nodes are handled separately: their item names become `category_hint_candidates`, feeding the BM25 taxonomy pre-filter.

### Meta tags (Open Graph, Twitter Cards, standard `<meta>`)

Reliable fallback for title, description, and primary image. Near-universal across sites. Parsed via `MappingRules.meta_key_to_field`.

### Script blobs

Handles sites that bundle product state into JavaScript. Two patterns covered:

- **Global assignments:** `window.__INITIAL_STATE__ = {...}`, `window.__NEXT_DATA__ = {...}` — Next.js and SPA standard (Nike, L.L.Bean)
- **Var/let/const assignments:** `var meta = {...}`, `const product = [...]` — Shopify and others

The script parser (`script_blob.py`) finds assignment patterns via regex, then extracts the JSON using a character-level balanced-bracket parser rather than a full JS parser. This keeps the dependency surface minimal while handling real-world cases.

`application/json` script tags are also parsed directly.

### Signal mapping (`MappingRules`)

`MappingRules` is the declarative config layer in `backend/extract/mapping.py`. It maps JSON keys and meta tag names to candidate fields. No branching per site — the same mapping runs over everything.

Color values across all recognized color keys (`color`, `colours`, `swatchColors`, `colorDescription`, etc.) are aggregated and emitted as a `Color` `OptionGroup` rather than flat strings.

`structured_passthrough_keys` (`variants`, `options`, `option_groups`) are JSON-serialized into `raw_attributes` so the LLM can build `Variant` objects from list/dict blobs that can't be flattened to strings.

### Failure modes

- **JS-rendered pages (fetched without a browser):** JSON-LD and meta tags are usually still in the raw HTML. Script blobs may be absent if the bundle loads asynchronously. Output is sparse but valid.
- **Malformed JSON in script blobs:** caught and skipped silently. Not fatal.
- **Relative image URLs without a page URL:** resolved best-effort; may be incorrect if the base path is unusual.

---

## Pass 2 · DOM Extraction

**Module:** `backend/extract/dom_extraction.py`

A heuristic single-pass over the raw HTML that enriches the `ExtractionContext` with signals that live in visible DOM structure rather than structured data. Runs after Pass 1 and writes to the same context. No LLM involved.

Three signal types:

1. **Price text** — elements with `itemprop="price"` (prefers `content` attribute for machine-readable value), `data-price` attributes, and elements whose `class` contains `"price"`. This covers the Article floor lamp case where price is only in a `<span class="regularPrice">` with no structured data at all.

2. **Option groups** — `(dimension, value)` pairs extracted from `aria-label` patterns on interactive elements:
   - `"Size Option: Large"` → `("Size", "Large")`
   - `"Select size 8"` → `("Size", "8")`
   Grouped into `OptionGroup`s, deduplicated, filtered for known non-product dimensions (Country, Quantity, etc.).

3. **Availability** — first `itemprop="availability"` `content` attribute seen, with the `https://schema.org/` prefix stripped to a short token (`"InStock"`).

### Failure modes

- **Sites with lazy-loaded images:** `data-src` is the catch; if images are injected purely via JS after render, they won't appear in the raw HTML. Output will be image-sparse.
- **Non-standard variant UIs (web components, canvas-rendered selectors):** option groups will be empty. `variants: []` is a valid Product.

---

## ExtractionContext · Candidate Bag

**Module:** `models.py`

The intermediate representation passed between passes and into the assembler. It holds **lists of candidates**, not resolved values. `title_candidates` might have three entries; `image_url_candidates` might have fifteen. Nothing is decided at this stage.

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

This design isolates extraction passes from assembly: any pass can be changed or replaced without touching the others or the LLM prompt. The typing is deliberately loose — strict schema mapping before the LLM resolves ambiguity would invert the dependency.

All image URLs are canonicalized (absolute, resize parameters stripped) before entering the context — deduplication and normalization happen here, not in the LLM.

### Failure modes

- **Empty context (all passes fail):** the assembler receives empty candidate lists and produces a nearly-empty Product. `name` and `price` are required fields; if truly absent, the pipeline raises and the product is skipped.

---

## Taxonomy Pre-filter · BM25

**Module:** `backend/taxonomy/prefilter.py`

Google's product taxonomy has ~5,600 categories. Passing all of them to the LLM every call is expensive and adds noise. The pre-filter narrows this to ~20 candidates using BM25 scoring.

Each category label is treated as a document. Query terms are drawn from `title_candidates` (capped at 3), `brand_candidates` (capped at 2), and `category_hint_candidates` (capped at 3). Per-field caps prevent any single noisy signal from dominating the query.

**Why BM25:**

- scikit-learn TF-IDF pulls in numpy + scipy — large dependencies for one ranking function
- Semantic embeddings add an inference step and model dependency; recall improvement is marginal when the LLM makes the final selection anyway
- `rank_bm25` is a focused single dependency; BM25's term saturation and length normalization outperform raw token overlap for short category labels

The BM25 index is built once per unique category set and cached via `@lru_cache`.

**Fallback:** if the top BM25 score is 0 (zero vocabulary overlap with every category), the filter returns a diverse spread of top-level taxonomy segments so the LLM still has a reasonable candidate list.

**The pre-filter only needs to get the right answer into the top 20.** The LLM makes the final selection.

### Failure modes

- **No vocabulary overlap:** fallback to broad segments. The LLM picks the closest — may be imprecise but will be a valid taxonomy entry.
- **Brand name matches unrelated category tokens:** surfaces irrelevant candidates. Rarely matters — the LLM ignores bad candidates when better ones are present.

---

## LLM Assembler

**Module:** `backend/assemble/assemble.py`

A single async call to `gemini-2.0-flash-lite` using structured output (`text_format=_AssembledProductDraft`). The prompt provides the full `ExtractionContext` as JSON and the top 20 category candidates as a numbered list.

**The LLM's responsibilities:**
- Select the best title, description, brand from candidates
- Infer brand from context when `brand_candidates` is empty (private-label products)
- Choose a category **by 1-based index** from the numbered list
- Build `Variant` objects from `option_group_candidates`
- Normalize price strings into `Price`

**The LLM is not responsible for:** HTML parsing, URL resolution, deduplication, or any work that deterministic code handles better and cheaper.

### Prompt design

System message carries invariant rules; user message carries variable data (numbered category list + ExtractionContext JSON). Stable rules separated from per-request data makes prompt changes easy to diff.

The category list is numbered and the model outputs a 1-based integer — `_materialize_product()` does the index-to-string lookup after the response. This eliminates the paraphrasing failure mode where the LLM slightly misspells a category string and fails Pydantic validation.

### Retry strategy

On `ValidationError`, retry once with the error message appended to the prompt. One retry covers the common case. A retry loop would hide systematic prompt problems that need fixing, not more attempts.

### Failure modes

- **Structured output parse error:** retry once; if still failing, the exception propagates.
- **LLM hallucinating image URLs:** prompt explicitly forbids it; still possible in edge cases. Downstream image loading would 404.
- **Wrong category after retry:** logged and skipped. The Pydantic validator is the gate — nothing invalid passes through.

---

## Identity Resolution

**Module:** `backend/identity/resolver.py`

Cross-merchant deduplication: given a dict of products keyed by their file ID, assigns stable `canonical_product_id`s and per-product `MatchDecision`s with explainable evidence.

### Two-tier matching

**Tier 1 — GTIN/UPC exact match (deterministic):** scans name, description, key features, and source URLs for 8–14 digit barcode-like numbers. Shared codes → automatic match, confidence floored at 0.95.

**Tier 2 — Title + brand similarity (probabilistic fallback):** `SequenceMatcher` ratio on normalized title (75% weight) and normalized brand (25% weight). Fires when GTIN is absent. Threshold configurable via `IDENTITY_TITLE_BRAND_MIN_SIMILARITY` env var (default 0.62).

### Clustering via networkx

Matched pairs are edges in a `networkx.Graph`. `nx.connected_components` groups transitively matched products: if A↔B and B↔C, all three land in one cluster. Hand-rolling DFS for this was ~25 lines of hard-to-follow state management; `networkx.connected_components` is two lines and is a well-known standard for this operation.

### Canonical IDs

`cp_<sha256(sorted_product_ids)[:16]>` — stable across reruns as long as input product IDs are deterministic (they are: `sha256(url)[:12]`).

### Configurability

All thresholds (`IDENTITY_MATCH_THRESHOLD`, `IDENTITY_TITLE_BRAND_MIN_SIMILARITY`, `IDENTITY_UPC_WEIGHT`, `IDENTITY_TITLE_BRAND_WEIGHT`) are readable from environment variables via `IdentityResolverConfig.from_env()`. Tuning doesn't require code changes.

---

## Storage

**Module:** `data/products/`

Flat JSON files at `data/products/{id}.json` where `id = sha256(url)[:12]`. No database. The seed script writes; the API reads.

Correct at this scale (7 products). A database adds setup, migrations, and a dependency for no benefit when the dataset fits in a directory scan. The trade-off inverts at ~10K products where indexed queries, concurrent write safety, and catalog-level operations (filtering, search) become necessary.

---

## API

**Module:** `backend/api/api.py`

Two read-only routes:

- `GET /products` — reads all JSON files, returns `list[ProductSummary]`
- `GET /products/{id}` — reads one file, returns `Product` (or 404)

The API layer contains zero business logic. Extraction lives in `backend/extract/`; the API is HTTP plumbing.

---

## Frontend

**Module:** `frontend/`

Next.js with React server components and shadcn/ui. Two pages:

- **Catalog (`/`):** responsive grid of `ProductCard` components. Each card shows image, brand, name, and price. Data fetched server-side from `GET /products`.
- **PDP (`/products/[id]`):** `ImageGallery` with thumbnail navigation, `PriceDisplay` with sale-price support, description, key features, color swatches, and category. Data fetched server-side from `GET /products/{id}`.

All data fetching happens in server components — no client-side API calls, no CORS configuration needed. The `NEXT_PUBLIC_API_URL` env var defaults to `http://localhost:8000`.

---

## Data Model

Key schema shapes in `models.py`:

```
Product
├── name, brand, description, key_features
├── price: Price { price, currency, compare_at_price }
├── category: Category { name }  ← validated against Google taxonomy
├── image_urls: list[str]
├── colors: list[str]
├── variants: list[Variant { name, attributes, price, availability }]
├── offers: list[Offer { merchant, price, availability, shipping, promo, source_url }]
├── canonical_product_id: str | None  ← set by IdentityResolver
└── match_decision: MatchDecision | None  ← confidence + evidence

ExtractionContext
└── *_candidates: list[str]  (title, description, brand, price, currency, image_url,
                               category_hint, key_feature)
    option_group_candidates: list[OptionGroup]
    raw_attributes: dict[str, Any]
```

`Product._ensure_offer_exists` is a backward-compatible bridge: if upstream extraction populates the legacy product-level `price` field but omits `offers`, it synthesizes a primary offer so API consumers can rely on merchant-scoped offer data regardless of extraction path.
