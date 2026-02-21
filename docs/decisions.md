# Design Decisions & Development Notes

Engineering trade-offs, bugs encountered, and scope decisions made during development. For the high-level architecture and decision rationale, see [architecture.md](architecture.md) and [design.md](design.md).

---

## Bugs Found During Eval Runs

These are real issues discovered by running the pipeline against all product pages and inspecting output. Each led to a targeted fix — none required structural changes to the pipeline.

### `@lru_cache` on `AsyncOpenAI` client (Ace Hardware)

**Symptom:** `RuntimeError: Event loop is closed` during httpx cleanup, surfaced as `APIConnectionError` in eval tests.

**Cause:** An `@lru_cache` decorator on the `AsyncOpenAI` client constructor. The cached client was bound to the first `asyncio.run()` event loop. When pytest ran subsequent test cases (each calling `asyncio.run()`), the cached client still held connections from the now-closed loop.

**Fix:** Removed the `@lru_cache`. The client is cheap to create — a fresh instance per call is correctly scoped to the active event loop. The "optimization" was a correctness bug. The issue only manifests when multiple `asyncio.run()` calls share a process (tests), not in the seed script (one `asyncio.run()` total).

---

### L.L.Bean price extracted as $0.00

**Symptom:** `price = 0.0` on the L.L.Bean product.

**Cause:** Pass 1 only read `itemprop` from `<meta>` tags. L.L.Bean uses `<span itemprop="price" content="29.95">` — a non-meta element with both `itemprop` and `content` attributes.

**Fix:** Extended the signal parser to emit a price signal for any HTML element with both `itemprop` and `content` attributes, not just `<meta>` tags. Generic fix — covers any site using microdata-style markup on non-meta elements.

---

### Article floor lamp: price extracted as $0.00

**Symptom:** `price = 0.0` on the Article product.

**Cause:** The price exists only in a DOM `<span class="regularPrice">` — no JSON-LD, no meta tags, no structured data at all. Pass 1 has no way to see it; Pass 2 catches it via the price-class heuristic.

**Status:** Resolved in Pass 2. The eval test was updated to assert the DOM-extracted price after this was addressed.

---

### A Day's March: `ValidationError` on `compare_at_price`

**Symptom:** Pydantic `ValidationError` — `compare_at_price` received a string instead of a float.

**Cause:** The LLM returned `"170\xa0USD"` (price with a non-breaking space and currency code) instead of a bare numeric value.

**Fix:** Added a `_coerce_price_string` field validator on `Price` that extracts the first numeric token from any string value. This handles currency symbols, codes, non-breaking spaces, and other formatting the LLM might include. Defensive parsing at the model boundary — don't rely on the LLM always formatting correctly.

---

### L.L.Bean: brand extracted as empty string

**Symptom:** `brand = ""` on the L.L.Bean product.

**Cause:** `brand_candidates` was empty — L.L.Bean doesn't embed brand in structured data for their own private-label products. `page_url` was `None` (the HTML has no canonical URL), so the LLM had no signals to infer from.

**Fix:** Updated the system prompt to instruct the LLM to infer brand from description, title, or domain when `brand_candidates` is empty. For a retailer's own products, the retailer name is the brand.

---

### Allbirds: variants not extracted

**Symptom:** `variants = []` despite the page having 14 size options in a Shopify `var meta = {...}` blob.

**Cause:** Two gaps. (1) `iter_assigned_json_blobs` only matched `window.__FOO__ = {...}` patterns, not `var`/`let`/`const` assignments used by Shopify. (2) `collect_candidates_from_node` silently dropped list/dict values from `raw_attributes` — so even when the blob was found, the `variants` array was lost.

**Fix:** Extended script blob extraction to also match `var`/`let`/`const` assignments. Added `structured_passthrough_keys` (`variants`, `options`, `option_groups`) to `MappingRules` — when these keys have list/dict values, they are JSON-serialized into `raw_attributes` so the LLM can build Variant objects from them.

---

### A Day's March trousers: colors empty despite hex codes in candidates

**Symptom:** `colors = []` even though `color_candidates` contained hex codes from `swatchColors` in `data-product-object`.

**Cause:** The assembler prompt said "use color_candidates" but was too vague. The LLM sometimes ignored them.

**Fix:** Tightened the colors rule in the system prompt: list all option values from the Color `OptionGroup`, include hex codes and colorway names; empty only when candidates are truly absent.

---

### Allbirds: `colors` contained product titles instead of colorway names

**Symptom:** `colors` contained `"Men's Dasher NZ - Blizzard/Deep Navy (Blizzard Sole)"` instead of `"Blizzard/Deep Navy"`, `"Auburn"`, etc.

**Cause:** Product-title-like strings from `og:title` and variant names were leaking into `color_candidates`. The LLM followed the prompt but the input was noisy.

**Fix:** Filter `color_candidates` before assembly: drop entries starting with `Men's `, `Women's `, `Kids' `, `Unisex ` — these are product title prefixes, not color names.

---

### Variants are a partial snapshot, not a full product matrix

`product.colors` comes from swatch/colorway data on the page — it represents all colors the product line comes in. `product.variants` comes from the active variant blob on that specific URL — it only contains size/availability data for the one color that was loaded.

The correct model would be `colorways: [{color, image_urls, sizes}]`, but building that requires fetching each color's page separately — 22 API calls for Allbirds alone. Deferred.

**UI consequence:** The product detail page only shows non-color attributes (size, etc.) and omits color from the options panel, since the sizes shown only apply to the scraped color. Displaying them as product-level options would imply all colors come in all sizes, which can't be verified from a single page.

---

## Scope Decisions

### What was deferred (planned for later phases)

| Feature | Rationale |
|---------|-----------|
| Pass 2: full image priority ladder | Pass 1 image coverage is sufficient for the corpus. A heuristic `data-zoom → srcset → data-src → src` ladder improves quality but isn't needed for the happy path. |
| Rich variant selectors in UI | Requires option group data from Pass 2 DOM parsing. Without full option groups, variants come from whatever the LLM infers. |
| `POST /extract` endpoint | Seed script handles extraction. A live endpoint adds API contract complexity with no evaluation benefit. |
| Skeleton loading states | Polish. Server components render with data already fetched — loading states only matter for client-side transitions. |
| `AttributesTable` component | Displays `raw_attributes` on the PDP. Developer-facing debug tool, not part of the core product display. |
| Field-level provenance | Tracking `(value, source, confidence)` per extracted field helps debugging but has no user-facing payoff at this scope. |

### What was cut

| Feature | Rationale |
|---------|-----------|
| Semantic embedding retrieval | BM25 covers the taxonomy pre-filter use case. Embeddings add latency, a model dependency, and complexity for marginal recall improvement when the LLM makes the final call. |
| Per-variant image/price linking | Requires fetching each color's page separately. Most sites don't expose per-variant structured data. |
| Full microdata graph traversal | Partial support added (`itemprop`+`content` elements). Full traversal is significant parser work for limited additional signal. |
| Debug drawer in UI | Not asked for. Would serve only the developer, not the evaluator. |

---

## Process Decisions

### Vertical-slice delivery

Built and validated one complete end-to-end slice (HTML in → Product JSON → API → UI) before adding depth. This kept the pipeline in a working state at all times and meant scope cuts were informed by actual output quality rather than speculation.

### Why separate design.md and decisions.md

[design.md](design.md) is a discussion guide — crisp answers to architectural questions, keyed decision rationale, and scaling thinking. [decisions.md](decisions.md) (this file) is a development log — concrete bugs encountered, their root causes, and the targeted fixes. They serve different audiences at different moments.
