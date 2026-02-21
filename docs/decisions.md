# Design Decisions & Development Notes

Engineering trade-offs, bugs encountered, and scope decisions made during development.

---

## Bugs Found During Eval Runs

These are real issues discovered by running the pipeline against all 5 product pages and inspecting the output. Each one led to a targeted fix.

### L.L.Bean: price extracted as $0.00

**Symptom:** `price = 0.0` on the L.L.Bean product.

**Cause:** Pass 1 only read `itemprop` from `<meta>` tags. L.L.Bean uses `<span itemprop="price" content="29.95">` — a non-meta element with both `itemprop` and `content` attributes.

**Fix:** Extended the signal parser to emit a signal for any HTML element with both `itemprop` and `content` attributes, not just `<meta>` tags. This is generic — it covers any site using microdata-style markup on non-meta elements.

### Article: price extracted as $0.00

**Symptom:** `price = 0.0` on the Article floor lamp.

**Cause:** The price exists only in a DOM `<span class="regularPrice">` — no JSON-LD, no meta tags, no structured data at all. Pass 1 has no way to see it.

**Fix:** Accepted as a known gap. This is exactly the kind of data that Pass 2 (DOM extraction) would recover using heuristic selectors. The eval test skips the price assertion for this page. Valid-but-sparse beats over-engineering a DOM scraper for one edge case.

### A Day's March: ValidationError on compare_at_price

**Symptom:** Pydantic `ValidationError` — `compare_at_price` received a string instead of a float.

**Cause:** The LLM returned `"170\xa0USD"` (a price with a non-breaking space and currency code) instead of a bare numeric value.

**Fix:** Added a `_coerce_price_string` field validator on `Price` that extracts the first numeric token from any string value. This handles currency symbols, codes, non-breaking spaces, and other formatting the LLM might include. Defensive parsing at the model boundary rather than hoping the LLM always formats perfectly.

### Ace Hardware: APIConnectionError in eval tests

**Symptom:** `RuntimeError: Event loop is closed` during httpx cleanup, surfaced as `APIConnectionError`.

**Cause:** An `@lru_cache` decorator on the `AsyncOpenAI` client constructor. The cached client was bound to the first `asyncio.run()` event loop. When pytest ran subsequent test cases (each calling `asyncio.run()`), the cached client still held connections from the now-closed loop.

**Fix:** Removed the `@lru_cache`. The client is cheap to create — a fresh instance per call is correctly scoped to the active event loop. The "optimization" of caching was actually a correctness bug.

### L.L.Bean: brand extracted as empty string

**Symptom:** `brand = ""` on the L.L.Bean product.

**Cause:** `brand_candidates` was empty because L.L.Bean doesn't embed brand in structured data for their own private-label products. `page_url` was `None` (L.L.Bean HTML has no canonical URL), so the LLM had zero signals to work with.

**Fix:** Updated the system prompt to instruct the LLM to infer brand from description, title, or domain when `brand_candidates` is empty. For a retailer's own products, the retailer name is the brand.

### Allbirds: variants not extracted

**Symptom:** `variants = []` on the Allbirds product despite the page having 14 size options in a Shopify `var meta = {...}` blob.

**Cause:** Two gaps in Pass 1. (1) `iter_assigned_json_blobs` only matched `window.__FOO__ = {...}` patterns, not `var name = {...}` or `let`/`const` assignments used by Shopify and others. (2) `collect_candidates_from_node` only stored primitive values in `raw_attributes`; list/dict values like `variants` were silently dropped by `_should_skip_raw_attribute`.

**Fix:** Extended script blob extraction to also match `var`/`let`/`const` assignments. Added `structured_passthrough_keys` (variants, options, option_groups) to `MappingRules` — when these keys have list/dict values, they are JSON-serialized into `raw_attributes` so the LLM can build Variant objects. Regex + balanced-bracket extraction was chosen over a full JS parser; BeautifulSoup is irrelevant here since the problem is parsing *within* JavaScript, not HTML.

### A Day's March trousers: colors empty despite hex codes in color_candidates

**Symptom:** `colors = []` on the trousers product even though `color_candidates` contained hex codes (e.g. `#888888`) from `swatchColors` in `data-product-object`.

**Cause:** The assembler prompt said "use color_candidates" but was too vague. The LLM sometimes ignored them or returned empty.

**Fix:** Tightened the colors rule in the system prompt: list all options from `color_candidates`, include hex codes and colorway names, empty only when candidates are empty.

### Variants are a partial snapshot, not the full product matrix

`product.colors` comes from swatch/colorway data on the page — it represents all colors the product line comes in. `product.variants` comes from the active variant blob on that same page — it only contains size/availability data for the one color that was loaded. We have no data on which sizes Auburn comes in, or which images belong to which color.

The correct model would be `colorways: [{color, image_urls, sizes}]`, but building that requires fetching each color's page separately — 22 API calls for Allbirds alone. Deferred.

**UI consequence:** The "Available options" section only shows non-color attributes (size, etc.) and omits color entirely, since the sizes shown only apply to the scraped color. Displaying them as product-level options would imply all colors come in all sizes, which we can't verify.

### Allbirds: colors were product titles instead of colorway names

**Symptom:** `colors` contained entries like `"Men's Dasher NZ - Blizzard/Deep Navy (Blizzard Sole)"` instead of `"Blizzard/Deep Navy (Blizzard Sole)"`, `"Auburn"`, etc.

**Cause:** Product-title-like strings (from og:title, variant names, etc.) were ending up in `color_candidates`. The LLM followed the prompt but the candidates were noisy.

**Fix:** Filter `color_candidates` before assembly: drop entries that start with `Men's `, `Women's `, `Kids' `, `Unisex ` — these are product title prefixes, not color names.

---

## Scope Decisions

### What was deferred (not cut)

These are features explicitly planned for later phases. They have clear designs but weren't needed for the core pipeline.

| Feature | Phase | Rationale |
|---------|-------|-----------|
| Pass 2: DOM extraction | MVP2 | Image priority ladder and option group parsing improve quality but aren't needed for the happy path. Pass 1 covers the structured data that most sites provide. |
| Rich variant selectors | MVP2 | Requires option group data from Pass 2. Without it, variants come from whatever the LLM can infer from raw attributes. |
| `POST /extract` endpoint | MVP3 | The seed script handles extraction. A live endpoint adds API contract complexity for no evaluation benefit. |
| Skeleton loading states | MVP3 | Polish. The server components render with data already fetched — loading states only matter for client-side transitions. |
| `AttributesTable` component | MVP3 | Displays `raw_attributes` on the PDP. Nice-to-have but not part of the core product display. |

### What was cut

These were considered and deliberately excluded.

| Feature | Rationale |
|---------|-----------|
| Semantic embedding retrieval | BM25 covers the taxonomy pre-filter use case. Embeddings add latency, a model dependency, and complexity for marginal recall improvement when the LLM makes the final call anyway. |
| Per-variant image/price linking | Requires mining per-variant data from script blobs. Diminishing return — most sites don't expose this in structured data. |
| Full microdata graph traversal | Partial support added (elements with `itemprop` + `content`). Full graph traversal is a significant parser for limited additional signal. |
| Evidence/provenance tracking | Tracking which source each candidate came from would help debugging but has no user-facing payoff at this scope. |
| Debug drawer in UI | Not asked for. Would only serve the developer, not the evaluator. |

---

## Process Decisions

### Vertical-slice delivery

Built and validated one complete end-to-end slice (HTML in → Product JSON → API → UI) before adding depth. This means the pipeline was always in a working state, and scope cuts were informed by actual output quality rather than speculation.

### Why separate design.md and process.md

[design.md](design.md) captures the *what and why* of the architecture. [process.md](process.md) captures the *how and when* of execution — time budgets, done gates, risks. Keeping them separate means the design doc stays useful as a reference after the project is done, while the process doc is a snapshot of the build approach.
