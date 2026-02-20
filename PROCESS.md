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
- [ ] All 5 pages produce a valid Product (no validation errors)
- [ ] Every product has a category that exists in the taxonomy file
- [ ] Every product has at least one image
- [ ] AI cost per product is under 1¢ (check model pricing if unsure)

**Watch for:**
- Nike and Article HTML is JS-rendered — raw HTML will be sparse. That's fine. Valid-but-sparse beats over-engineering.
- If the LLM picks a wrong category, the `Category` validator will catch it. Retry once with the error appended. If it fails twice, move on — fix the prompt later.
- Don't try to perfect extraction quality here. MVP2 exists for that reason.

#### Phase 2 · API + seed

Seed script runs pipeline for all 5 pages and writes JSON. FastAPI serves read-only routes.

**Done gate:**
- [ ] Running the seed script creates 5 product JSON files
- [ ] Catalog endpoint returns all 5 products
- [ ] Product detail endpoint returns full product data for a given ID
- [ ] Requesting a product that doesn't exist returns 404

**Watch for:**
- No `POST /extract` in MVP1. Seed script handles extraction. Don't build what you don't need yet.

#### Phase 3 · Frontend

Catalog grid at `/`, PDP at `/products/:id`. Vite + React + TypeScript + shadcn.

**Done gate:**
- [ ] Catalog shows all 5 products (image, name, brand, price)
- [ ] Clicking a product card opens the product detail page
- [ ] Product detail page shows image gallery, price (and sale price if applicable), description
- [ ] Back navigation returns to catalog
- [ ] No console errors

**Watch for:**
- If running long, cut variants display first. Catalog + PDP with image/price/description is the minimum bar.
- Don't build loading skeletons or error boundaries — that's MVP3.

#### Phase 4 · README + system design

Setup instructions (backend + frontend). 1–2 paragraph system design write-up in your own words.

**Done gate:**
- [ ] Someone can clone the repo, follow the README, and get the app running
- [ ] System design explains how extraction works and why it's split into multiple passes

---

### Sanity checks (run before calling MVP1 done)

- [ ] Product JSON loads and validates without errors
- [ ] API returns data in the format the frontend expects
- [ ] No hardcoded file paths or API keys in committed code
- [ ] `.env.example` exists if env vars are required
- [ ] Only the 5 provided HTML files are used as test data — no invented fixtures

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

---

## MVP2 — Extraction depth (deferred)

Builds on MVP1 with richer extraction quality, not new surface area.

- **Pass 2: DOM extraction** — image priority ladder, option group parsing
- **Richer variants** — cartesian product from option groups, per-variant price/availability
- **Image deduplication** — strip resize params, normalize URLs, rank by resolution
- **Frontend: VariantsPanel** — attribute pill selectors
- **Frontend: ImageGallery upgrade** — full-res zoom, better thumbnails

---

## MVP3 — Polish and completeness (deferred)

- `POST /extract` API endpoint
- Skeleton loading states and error boundaries
- Responsive layout tuning
- `AttributesTable` for `raw_attributes`
- Taxonomy fallback to broad segments on zero overlap
- Empty states for missing data
- Edge case hardening for sparse HTML pages
