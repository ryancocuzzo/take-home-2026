# Process

Vertical-slice delivery: build and validate one complete end-to-end slice before adding depth. The pipeline was always in a working state; scope cuts were informed by actual output quality, not speculation.

---

## MVP1 — End-to-end happy path

Target: ~4.5 hours. One working pipeline, one working UI, valid Products for all pages.

### Time budget

| Phase | Est. | Gate |
|-------|------|------|
| Models + structured extraction | 1h | Extraction works for JSON-LD and script blob sources |
| Taxonomy pre-filter + LLM assembler | 1h | All pages produce a valid Product |
| Seed script + API | 30m | API serves the extracted products |
| React catalog + PDP | 1.5h | Catalog and product detail pages work with real data |
| README + system design | 20m | Someone else can clone and run it |

### Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Nike/Article HTML is sparse (JS-rendered) | Use whatever's in the raw HTML; LLM produces valid-if-sparse Product |
| LLM picks wrong category | `Category` validator catches; retry once with error appended |
| LLM structured output parse error | Return partial product; log and continue |
| OpenRouter model unavailable | Fall back to `openai/gpt-4o-mini` |
| Frontend time overrun | Cut variants display — catalog + PDP with image/price/description is the minimum bar |

### Quirks found during eval runs

| Page | Symptom | Cause | Fix |
|------|---------|-------|-----|
| LLBean | `price = 0.0` | Pass 1 only read `itemprop` from `<meta>` tags; LLBean uses `<span itemprop="price" content="29.95">` | Extended `_SignalParser` to emit for any element with both `itemprop` and `content` attributes |
| Article | `price = 0.0` | Price is only in a DOM `<span class="regularPrice">` — no structured data | Resolved in Pass 2 DOM extraction |
| A Day's March | `ValidationError` on `compare_at_price` | LLM returned `"170\xa0USD"` instead of a bare float | Added `_coerce_price_string` validator on `Price` |
| Ace Hardware | `APIConnectionError` in eval tests | `@lru_cache` on `AsyncOpenAI` client bound it to the first event loop; subsequent `asyncio.run()` calls in the same process got a new loop but the cached client held connections from the closed loop | Removed `@lru_cache` — client is cheap to create; fresh instance per call |
| LLBean | `brand = ""` | `brand_candidates` was empty; `page_url` was `None`; LLM had nothing to infer from | Updated system prompt to infer brand from description/title/domain when `brand_candidates` is empty |
| Allbirds | `variants = []` | `iter_assigned_json_blobs` missed `var meta = {...}` (Shopify); `_should_skip_raw_attribute` silently dropped list/dict values | Extended blob extraction to match `var/let/const`; added `structured_passthrough_keys` |

---

## MVP2 — Platform model hardening

Builds on MVP1 by closing the biggest architecture gaps: canonical model boundaries and identity.

### Canonical commerce model

Split the product-centric shape into explicit entities:
- `Product` — canonical identity + attributes
- `Merchant` — seller identity
- `Offer` — merchant-scoped price, availability, shipping, promo

One canonical `Product` can hold multiple `Offer`s from different merchants. API responses keep product-level and offer-level attributes separate.

### Entity resolution and identity

Two-tier matching strategy for cross-merchant dedupe:
- Tier 1 (deterministic): UPC/GTIN exact match → auto-match
- Tier 2 (probabilistic fallback): title + brand similarity threshold when GTIN is absent

Match evidence and confidence are stored per product, not just a boolean. All thresholds are configurable via env vars without code changes.

**Why not more signals now:** Keeps implementation and debugging cost low while still deduplicating obvious non-GTIN duplicates. Defers `normalized_attribute_overlap` and `image_hash_similarity` to when corpus size and failure modes justify the added complexity.

**Why `networkx`:** Connected components — grouping matched pairs into clusters (A↔B and B↔C → all three in one group) — requires graph traversal. Hand-rolling DFS was ~25 lines of hard-to-follow state management. `networkx.connected_components` does it in two lines.

---

## MVP3 — Query, reliability, and eval gates

Next phase. Key items:

- **Deterministic query surface + semantic rerank** — structured filters (`category`, `brand`, `price`, variant attributes) first, semantic reranking second. Explicit filter-then-rank, not model-only retrieval.
- **Idempotent reprocessing** — idempotency key per input (content hash); process only on change; safe backfill/reindex without taking reads offline.
- **Quality gates** — golden set per retailer, CI fails on meaningful score regressions, new retailers don't silently degrade existing ones.
