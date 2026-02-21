# Discussion Guide

Quick-reference for the system discussion. Crisp answers to the questions most likely to come up.

---

## The pitch (2 sentences)

This is a generalized product data extraction pipeline: given raw HTML from any product page, it produces a validated `Product` with no site-specific logic anywhere in the codebase. The hard problems are that product data is scattered across JSON-LD, meta tags, JS blobs, and the DOM with no consistency between sites, and the output category must exactly match one of Google's 5,600 taxonomy entries.

---

## Why multi-pass, not LLM-everything?

This is the most likely first question. Three reasons:

**1. Cost and scale.** A modern product page can be 500KB+ of HTML. Token cost is linear with input size. At $0.005/call for the current model, LLM-everything on 500KB HTML would be 100× more expensive per product — and would scale to hundreds of millions of dollars at 50M products. Deterministic parsing is effectively free.

**2. Reproducibility.** Deterministic bugs (wrong price extracted, missing images) are reproducible and fixable without an API key. If the LLM handles everything, every failure looks the same from the outside, and root-causing requires expensive LLM calls.

**3. Division of labor.** The LLM is good at semantic disambiguation: "which of these three title candidates is the most accurate?" It is not better than a regex at pulling a float out of a JSON-LD `"price"` field. Don't use a model for work that deterministic code does better, faster, and reproducibly.

**The split:** Pass 1 and Pass 2 do all the parsing. The LLM resolves ambiguity and handles the things that genuinely require reasoning (semantic category selection, brand inference from context, variant assembly from sparse signals).

---

## Key decisions — quick reference

| Decision | Reasoning |
|----------|-----------|
| Multi-pass pipeline | Deterministic extraction is cheap and testable without an API key. LLM only does semantic work. |
| `ExtractionContext` as candidate bag | Multiple passes write candidates; nothing is resolved prematurely. Passes are fully independent. |
| BM25 for taxonomy pre-filter | `rank_bm25` is a focused dependency. scikit-learn pulls in numpy+scipy for one function. Embeddings add latency and a model dependency for marginal improvement when the LLM makes the final call. |
| Category by index, not free text | LLM occasionally paraphrases category strings (e.g. "Trousers" vs "Pants"). Outputting a 1-based index and mapping it post-response eliminates that failure mode entirely. |
| Single retry on `ValidationError` | One retry covers the common case (category mismatch, price format). A loop hides systematic prompt bugs that need fixing, not more attempts. |
| `gemini-2.0-flash-lite` at ~$0.005/call | Sufficient quality for structured assembly. Escalation path is flash-full, not a pipeline rewrite. |
| `networkx` for identity clustering | `nx.connected_components` handles transitive matching (A↔B and B↔C → one cluster) in 2 lines vs ~25 lines of DFS state management. |
| Flat JSON files for storage | Correct at 7 products. Acknowledged trade-off — inverts at ~10K where indexed queries and concurrent writes matter. |
| No site-specific logic anywhere | Zero conditionals on domain, XPath selectors, or page-specific prompt hints. The system must generalize to unseen sites. Any conditional would break this guarantee. |

---

## Bugs worth discussing

These are the most interesting because each one revealed a real design constraint. See [decisions.md](decisions.md) for the full list with causes and fixes.

### 1. `@lru_cache` on `AsyncOpenAI` client

Cached the AI client to avoid recreating it. But `asyncio.run()` creates a new event loop each call in the test suite, and the cached client held connections from the closed loop → `RuntimeError: Event loop is closed` during httpx cleanup. **Fix:** removed the cache — fresh client per call, correctly scoped to the active loop. The "optimization" was a correctness bug. Only surfaced in tests (multiple `asyncio.run()` calls per process), not in the seed script (single `asyncio.run()` total).

### 2. Shopify variants not extracted (Allbirds)

`iter_assigned_json_blobs` only matched `window.__FOO__` patterns. Shopify uses `var meta = {...}`. Separately, `_should_skip_raw_attribute` silently dropped list/dict values from `raw_attributes`, so even when the blob was found, the `variants` array was discarded. **Fix:** extended regex to cover `var/let/const` assignments; added `structured_passthrough_keys` to preserve list/dict values as JSON-serialized strings for the LLM.

### 3. L.L.Bean price extracted as $0.00

Pass 1 only read `itemprop` from `<meta>` tags. L.L.Bean uses `<span itemprop="price" content="29.95">` — a non-meta element. **Fix:** extended the signal parser to emit for any element with both `itemprop` and `content` attributes. Generic fix — covers any site using microdata-style markup on non-meta elements.

### 4. LLM returned `"170\xa0USD"` for `compare_at_price`

Non-breaking space and currency code instead of a bare float. The Pydantic `float` validator rejected it. **Fix:** `_coerce_price_string` field validator on `Price` extracts the first numeric token from any string. Defensive at the model boundary, not relying on the LLM always formatting correctly.

### 5. Variants are a partial snapshot, not a full product matrix

`product.colors` comes from swatch data — all colors the product line offers. `product.variants` comes from the active variant blob on the scraped page — only sizes for the one color that was loaded. The correct model would be `colorways: [{color, image_urls, sizes}]`, but building that requires fetching each color's page separately (22 API calls for Allbirds alone). Deferred. The UI only shows non-color variant attributes to avoid implying all sizes apply to all colors.

---

## Scaling answer (key points)

See README system design for the full write-up. Quick summary:

**What scales today:**
- Pipeline is linear in cost (~$0.005/product) — 50M products is ~$250K in inference, viable for a batch job
- BM25 index is built once and cached — negligible overhead at any corpus size
- Async pipeline with `asyncio.gather` parallelizes naturally

**What breaks at scale:**
- Flat JSON → need Postgres with JSONB (or a document store) at ~10K products for indexed queries and concurrent writes
- `asyncio.gather` → need a distributed task queue (Celery, Cloud Tasks) with rate limiting against upstream sites and the LLM provider
- HTML fetching is out of scope here (we work from pre-fetched files) — at scale it's the real bottleneck: politeness controls, retry logic, change detection, deduplication
- Identity resolution is O(n²) pairwise comparisons — needs blocking/LSH strategies at scale

**Agentic API additions:**
- Structured filters (`?category=&brand=&price_max=&in_stock=true`) backed by indexed fields
- Semantic search endpoint (NL query → filtered + reranked results, not model-only retrieval)
- Webhook/streaming for new products as they're extracted (no polling required)
- Comparison endpoint: structured diff between products for "compare these two" flows
- OpenAPI spec + typed SDKs so agent frameworks (LangChain, Vercel AI SDK) can call the API as a tool with zero glue code

---

## What I'd tackle next

In priority order if this became a real product:

1. **Idempotent processing** — content hash as idempotency key; skip unchanged pages; safe reindex without taking reads offline
2. **Canonical commerce model** — split `Product` into `Product` (identity) + `Merchant` + `Offer` (merchant-scoped price/availability/promo/shipping). The current schema has `offers` on `Product` but extraction still produces legacy product-level fields.
3. **Query surface** — deterministic filters first (category, brand, price, variant attributes), then semantic rerank on the filtered set. Never model-only retrieval for a shopping catalog.
4. **Field-level provenance** — `(value, source, confidence)` on extraction outputs; answers "why this category/price/title?" in debugging and internal tooling
5. **Eval regression gate** — golden outputs per retailer, CI fails on meaningful score regressions; adding a new retailer doesn't silently degrade existing ones

---

## What was cut and why

| Item | Decision | Reason |
|------|----------|--------|
| Semantic embeddings for taxonomy | Cut | BM25 covers the use case. Embeddings add latency and a model dependency for marginal recall improvement when LLM makes the final call. |
| Per-variant image/price linking | Cut | Requires fetching each color's page. Diminishing return — most sites don't expose this in structured data. |
| Full microdata graph traversal | Partial | Added for `itemprop`+`content` elements. Full traversal is significant parser complexity for limited additional signal. |
| Evidence/provenance tracking | Deferred | No user-facing payoff at this scope; first step for MVP3. |
| `POST /extract` endpoint | Deferred | Seed script handles extraction. API stays read-only — no additional contract complexity needed for evaluation. |
| Pass 2 DOM image priority ladder | Deferred | Image coverage from Pass 1 is sufficient for the corpus. Heuristic image laddering is meaningful work with diminishing returns past a certain depth. |
