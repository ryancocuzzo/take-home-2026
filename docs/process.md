# Process

Vertical-slice delivery: build and validate one complete end-to-end slice before adding depth.

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
- [x] Only the 5 provided HTML files are used as test data — no invented fixtures

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

## MVP2 — Extraction fidelity and model expressiveness

Builds on MVP1 with better signal quality and a richer data model. No new surface area — every change is in the extraction and assembly pipeline.

Two root problems to fix: the LLM is over-working (it resolves conflicts, normalizes, and structures variants all from a flat candidate bag with no source context), and the data model is under-expressive (`raw_attributes: dict[str, Any]` throws away structure the HTML already encodes).

### Execution checklist

#### Phase 1 · DOM extraction pass

Add `extract_dom_signals(html, page_url)` as a deterministic Pass 2 that enriches `ExtractionContext` before the assembler runs. No LLM.

- Price fallback: `[itemprop="price"]`, `[class*="price"]` elements, `data-price` attributes — fixes Article's `price = 0.0`
- Option groups: `<select>`, `<input type="radio">` groups, swatch containers → `OptionGroup` candidates (see Phase 2)
- Availability: `[itemprop="availability"]`, `data-availability`, disabled button states

**Done gate:**
- [ ] Article page produces a non-zero price sourced from DOM
- [ ] At least 3 of the 7 pages produce one or more `OptionGroup` candidates
- [ ] No site-specific branches — structural/semantic heuristics only
- [ ] Existing Pass 1 tests still pass

**Watch for:**
- JS-rendered pages won't have much in the DOM either. Don't force it — a missing option group is fine; a wrong one isn't.

#### Phase 2 · `OptionGroup` model and structured variant assembly

Replace `raw_attributes: dict[str, Any]` with `option_groups: list[OptionGroup]` on `ExtractionContext`. New models:

```python
class OptionValue(BaseModel):
    value: str
    available: bool = True
    price_delta: float | None = None

class OptionGroup(BaseModel):
    dimension: str  # "Size", "Color", "Material", etc.
    options: list[OptionValue]
```

Assembler receives typed `OptionGroup` input, generates cartesian-product `Variant` list with named attributes and per-variant price/availability. Keep `raw_attributes` as a debug overflow field only. Cap variants at 50; log when the cap applies.

**Done gate:**
- [ ] LLBean, Nike, A Day's March produce a `Variant` list with named attributes matching their option groups
- [ ] `Variant.availability` is populated where option-level availability is known
- [ ] Assembler prompt uses `option_groups`, not the raw blob

#### Phase 3 · Signal provenance

Candidates carry their extraction source so the assembler can apply a confidence hierarchy and so we can see where each value came from.

```python
class CandidateSignal(BaseModel):
    value: str
    source: Literal["json_ld", "meta_tag", "script_blob", "dom"]
```

Candidate fields on `ExtractionContext` change from `list[str]` to `list[CandidateSignal]`. Assembler prompt renders source labels alongside values (`"json_ld: $129.00"`, `"dom: $99.00"`). Hierarchy: `json_ld > script_blob > dom > meta_tag`. `Product` model is unchanged.

**Done gate:**
- [ ] Every candidate has a non-null `source`
- [ ] Assembler prompt renders source labels
- [ ] Conflicting `json_ld` and `dom` prices resolve to `json_ld` (verified by a test with a seeded conflict)
- [ ] All existing extraction tests pass after field type change

#### Phase 4 · Image pipeline upgrade

Priority ladder: JSON-LD → `og:image` → script blob → DOM `srcset`/`data-zoom-src` → DOM `<img src>`. Resolution ranking: extract width hints from URL patterns (`_800x`, `?w=800`, `srcset`); prefer higher resolution. Canonical deduplication: deduplicate by canonical URL after stripping resize params, not raw string equality.

**Done gate:**
- [ ] No product has duplicate images
- [ ] `og:image` ranks above a DOM-scraped image of the same product
- [ ] Resolution hint is populated for at least one page that embeds width in URLs
- [ ] All 7 pages still have at least one image

---

### Sanity checks (run before calling MVP2 done)

- [ ] All 7 pages produce a valid `Product` with no `ValidationError`
- [ ] Article price > 0.0
- [ ] LLM cost per product still under 1¢
- [ ] All existing tests still pass

---

## MVP3 — Polish and completeness

- **Taxonomy fallback** — when BM25 returns no overlap, fall back to the highest-scoring broad top-level segment instead of giving the LLM an empty list
- **Sparse page warnings** — log a structured warning when fewer than 2 sources contribute to a field; assembler prompt flags low-confidence fields explicitly
- **`POST /extract`** — accepts `{ "url": "..." }` or `{ "html": "...", "url": "..." }`, runs the full pipeline, returns `Product`
- **Catalog filtering** — `GET /products?category=...&brand=...&price_max=...`
- **`VariantsPanel`** — dimension pill selectors; selecting a combination shows the active variant's price/availability
- **`AttributesTable`** — collapsible debug section on PDP for `raw_attributes`
- **Skeleton loading states and error boundaries**
- **Empty states** for missing description, images, variants, features
- **Responsive layout** — catalog collapses to single column; PDP image gallery stacks on mobile
