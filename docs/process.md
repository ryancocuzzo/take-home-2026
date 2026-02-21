# Process

Vertical-slice delivery: build and validate one complete end-to-end slice before adding depth.

Note: MVP1 was originally scoped against 5 pages from the prompt. The repository corpus now contains 7 pages, and later phases/sanity checks reflect the 7-page corpus.

---

## MVP1 — End-to-end happy path

Target: ~4.5 hours. One working pipeline, one working UI, valid Products for all 5 pages.

### Time budget

| Phase | Est. | Gate |
|-------|------|------|
| Models + structured extraction | 1h | Extraction works for both data sources (schema.org + script blobs) |
| Taxonomy pre-filter + LLM assembler | 1h | All 5 pages produce a valid Product |
| Seed script + API | 30m | API serves the 5 products |
| React catalog + PDP | 1.5h | Catalog and product detail pages work with real data |
| README + system design | 20m | Someone else can clone and run it |

If a phase runs 20+ minutes over, stop and cut scope from that phase — don't steal from later phases.

---

### Execution checklist

Work in this order. Each phase has a **done gate** — don't move on until it passes.

#### Phase 1 · Extraction pipeline

Build models, Structured Signal Extraction (Pass 1: JSON-LD + meta + script blobs), taxonomy pre-filter, LLM assembler.

**Done gate:**
- [x] Ace Hardware page: extraction pulls product data from the schema.org JSON-LD block
- [x] L.L.Bean page: extraction pulls product data from the embedded `window.__INITIAL_STATE__` blob
- [x] Nike page: extraction pulls from the `__NEXT_DATA__` script (Next.js)
- [x] All 5 pages produce a valid Product (no validation errors)
- [x] Every product has a category that exists in the taxonomy file
- [x] Every product has at least one image
- [x] AI cost per product is under 1¢ (check model pricing if unsure)

**Watch for:**
- Nike and Article HTML is JS-rendered — raw HTML will be sparse. That's fine. Valid-but-sparse beats over-engineering.
- If the LLM picks a wrong category, the `Category` validator will catch it. Retry once with the error appended. If it fails twice, move on — fix the prompt later.
- Don't try to perfect extraction quality here. MVP2 exists for that reason.

#### Phase 2 · API + seed

Seed script runs pipeline for all 5 pages and writes JSON. FastAPI serves read-only routes.

**Done gate:**
- [x] Running the seed script creates 5 product JSON files
- [x] Catalog endpoint returns all 5 products
- [x] Product detail endpoint returns full product data for a given ID
- [x] Requesting a product that doesn't exist returns 404

**Watch for:**
- No `POST /extract` in MVP1. Seed script handles extraction. Don't build what you don't need yet.

#### Phase 3 · Frontend

Catalog grid at `/`, PDP at `/products/:id`. Next.js + React + TypeScript + shadcn.

**Done gate:**
- [x] Catalog shows all 5 products (image, name, brand, price)
- [x] Clicking a product card opens the product detail page
- [x] Product detail page shows image gallery, price (and sale price if applicable), description
- [x] Back navigation returns to catalog
- [x] No console errors

**Watch for:**
- If running long, cut variants display first. Catalog + PDP with image/price/description is the minimum bar.
- Don't build loading skeletons or error boundaries — that's MVP3.

#### Phase 4 · README + system design

Setup instructions (backend + frontend). 1–2 paragraph system design write-up in your own words.

**Done gate:**
- [x] Someone can clone the repo, follow the README, and get the app running
- [x] System design explains how extraction works and why it's split into multiple passes

---

### Sanity checks (run before calling MVP1 done)

- [x] Product JSON loads and validates without errors
- [x] API returns data in the format the frontend expects
- [x] No hardcoded file paths or API keys in committed code
- [x] `.env.example` exists if env vars are required
- [x] Only the provided HTML files in the corpus are used as test data — no invented fixtures

---

### Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Nike/Article HTML is sparse (JS-rendered) | Use whatever's in raw HTML; LLM produces valid-if-sparse Product |
| LLM picks wrong category | `Category` validator catches; retry once with error appended |
| LLM structured output parse error | Return partial product; log and continue |
| Gemini flash not available via OpenRouter | Fall back to `openai/gpt-4o-mini` |
| Frontend time overrun | Cut variants display — catalog + PDP with image/price/description is the bar |

### Quirks found during eval runs

| Page | Symptom | Cause | Fix |
|------|---------|-------|-----|
| LLBean | `price = 0.0` | Pass 1 only read `itemprop` from `<meta>` tags; LLBean uses `<span itemprop="price" content="29.95">` | Extended `_SignalParser` to emit a signal for any element with both `itemprop` and `content` attributes |
| Article | `price = 0.0` | Price is only in a DOM `<span class="regularPrice">` — no structured data | Accepted as a Pass 2 gap; eval test skips the price assertion for this page |
| A Day's March | `ValidationError` on `compare_at_price` | LLM returned `"170\xa0USD"` instead of a bare float | Added `_coerce_price_string` validator on `Price` to extract the first numeric token from any string value |
| Ace Hardware | `APIConnectionError` in eval tests | `@lru_cache` on `AsyncOpenAI` client bound it to the first `asyncio.run()` event loop; subsequent `asyncio.run()` calls in the same process got a new loop but the cached client still held connections from the closed loop, causing `RuntimeError: Event loop is closed` during httpx cleanup | Removed `@lru_cache` — client is cheap to create; a fresh instance per call is correctly scoped to the active event loop |
| LLBean | `brand = ""` | `brand_candidates` was empty (L.L.Bean doesn't embed brand in structured data for their own private-label products) and `page_url` was `None`; LLM had nothing to pick from | Updated system prompt to instruct the LLM to infer brand from description/title/domain when `brand_candidates` is empty |

---

## MVP2 — Platform model hardening

Builds on MVP1 by closing the biggest architecture gaps: canonical model boundaries and identity.

### Execution checklist

#### Phase 1 · Canonical commerce model

Split the current product-centric shape into explicit entities:
- `Product` (canonical identity + attributes)
- `Merchant` (seller identity)
- `Offer` (merchant-scoped price, availability, shipping, promo)

**Done gate:**
- [x] One canonical `Product` can hold multiple `Offer`s from different merchants
- [x] API responses keep product-level attributes separate from offer-level attributes
- [x] Existing frontend still renders without schema ambiguity

#### Phase 2 · Entity resolution and identity

Use a two-tier matching strategy for cross-merchant dedupe (Option 2):
- Tier 1 (deterministic): UPC/GTIN exact match => auto-match
- Tier 2 (probabilistic fallback): title+brand similarity threshold when GTIN is absent

Store match evidence and confidence, not just a boolean decision.

**Done gate:**
- [x] Canonical product IDs are stable across reruns
- [x] Matching decisions include explainable evidence and confidence
- [x] Thresholds are configurable without code changes

**Trade-offs (why Option 2 now):**
- Keeps implementation and debugging cost low while still deduping obvious non-GTIN duplicates
- Preserves explainability with only two signals, making threshold tuning understandable
- Reduces false confidence from weak signals at this dataset size
- Defers `normalized_attribute_overlap` and `image_hash_similarity` to a later phase when corpus size and failure modes justify added complexity

**Dependency decisions:**
- `networkx` for connected components — grouping matched pairs into clusters (A matches B and B matches C → all three in one group) requires graph traversal. Hand-rolling DFS was ~25 lines of hard-to-follow state management. `networkx.connected_components` does it in two lines and is a well-known standard library for this operation. Alternatives considered: `scipy.sparse.csgraph` (pulls in numpy/scipy for one function), `dedupe` library (requires training data), union-find by hand (less readable than networkx).

---

### Sanity checks (run before calling MVP2 done)

- [x] Canonical/merchant/offer boundaries are reflected in API contracts
- [x] Re-seeding the same inputs does not create duplicate canonical products
- [x] At least one test covers a high-confidence match and one covers a low-confidence non-match

---

## MVP3 — Query, reliability, and eval gates

Adds production-facing behavior: query surfaces, reprocessing safety, and regression control.

### Execution checklist

#### Phase 1 · Deterministic query surface + semantic rerank

Add structured filtering first (`category`, `brand`, `price`, variant attrs), then semantic reranking on the filtered set.

**Done gate:**
- [ ] Query path is explicitly filter-then-rank (no model-only retrieval)
- [ ] Pagination and timeout defaults are in place
- [ ] New query types can be added without changing core extraction flow

#### Phase 2 · Reliability and reprocessing

Move from one-shot batch behavior to safe incremental processing:
- idempotency key per input (content hash)
- process only on change
- safe backfill/reindex plan

**Done gate:**
- [ ] Reprocessing unchanged inputs is a no-op
- [ ] Failed extractions can be retried without corrupting state
- [ ] Reindex/backfill can run without taking reads offline

#### Phase 3 · Quality gates (eval + drift)

Add a small golden set with per-field scoring and diff-based regression checks.

**Done gate:**
- [ ] Golden outputs exist for representative retailers
- [ ] CI fails on meaningful score regressions
- [ ] Adding a new retailer does not silently degrade existing ones

---

### Deferred improvements from earlier MVP2/MVP3 drafts

The previous extraction-fidelity and UI-polish items (e.g., additional DOM/image upgrades, `POST /extract`, variants panel, skeletons, empty states) remain valid improvement points. They are intentionally deferred in favor of platform-hardening work above.
