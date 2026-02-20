# Design

> **MVP annotations:** Each component is tagged **[MVP1]**, **[MVP2]**, or **[MVP3]**.
> MVP1 is the end-to-end happy path. MVP2 adds extraction depth. MVP3 adds polish.

## What this solves

Given raw HTML for an arbitrary product detail page, produce a fully structured `Product` — name, price, images, variants, category, attributes — without any site-specific logic. The output must conform to a strict schema validated at runtime.

The hard parts: product data is scattered across JSON-LD, meta tags, embedded JS blobs, and the DOM with no consistency between sites. Category must match Google's 5,600-line taxonomy exactly. Variants have no standard representation.

---

## Workflow

### MVP1 pipeline

```
Raw HTML
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 1 · Structured Extraction            [MVP1]           │
│  JSON-LD → meta tags → script blobs                         │
│  Deterministic. No LLM. Cheap.                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                  ExtractionContext
              (intermediate bag of candidates)
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
  Taxonomy Pre-filter          (context passed through)
  token overlap → top 20            [MVP1]
  category candidates
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM Assembler                             [MVP1]           │
│  Structured output → Product                                │
│  Selects best candidates, assigns category, builds variants │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                    Product (JSON)
                           │
               ┌───────────┴───────────┐
               │                       │
               ▼                       ▼
        data/products/            FastAPI [MVP1]
          {id}.json            /products (read-only)
                                       │
                                       ▼
                                  React UI [MVP1]
                             Catalog  ·  PDP
```

### MVP2 addition

```
Pass 1 output
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 2 · DOM Extraction                   [MVP2]           │
│  Image priority ladder → option groups → visible text       │
│  Heuristic. Fills gaps left by Pass 1.                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
              ExtractionContext (enriched)
```

### MVP3 addition

```
  POST /extract endpoint                     [MVP3]
  Skeleton states, error boundaries          [MVP3]
  Responsive polish                          [MVP3]
```

---

## Components

### Pass 1 — Structured extraction [MVP1]

Pulls from three signal sources in priority order: JSON-LD, meta tags, embedded script blobs. All three are parsed unconditionally — there's no site detection.

JSON-LD is the richest source when present. It's explicit, typed, and standardized. Meta tags are a reliable fallback for title, description, and primary image. Script blobs handle the case where a site bundles its full product state into `window.__INITIAL_STATE__` or similar — LLBean is an example. The pattern (`window.__FOO__ = {...}`) is generic enough to cover most SPAs without any site-specific logic.

All image URLs are resolved to absolute and deduplicated by normalized URL (resize params stripped). Deduplication happens here, not in the LLM.

**Trade-offs:** This pass is cheap and deterministic but produces *candidates*, not a product. It doesn't try to pick the best title or resolve ambiguity — that's the LLM's job. The split matters: don't ask deterministic code to do semantic reasoning.

**Failure modes:**
- JS-rendered pages (fetched via curl): JSON-LD and meta are usually still present in the raw HTML. Script blobs may be absent if the bundle loads asynchronously. Output is sparse but valid.
- Malformed JSON in script blobs: caught and skipped, not a fatal error.
- Relative image URLs with unusual base paths: resolved against the page URL; if the URL wasn't provided, images may resolve incorrectly.

---

### Pass 2 — DOM extraction [MVP2]

A heuristic pass that runs after Pass 1 and fills in what structured data missed. Two jobs: images and option groups.

Images follow a priority ladder (`data-zoom` → `srcset` max resolution → `data-src` → `src`). URLs containing `large / hires / 2048 / 1024` are ranked above thumbnails. Nav icons, logos, and tracking pixels (inferred from URL path or small dimensions) are filtered out.

Option groups are extracted from `<select>`, radio/checkbox groups, and basic ARIA listboxes. This covers the vast majority of variant selectors without trying to reverse-engineer every possible chip/toggle pattern.

**Trade-offs:** Heuristics are fragile by nature. The ladder covers the common patterns; it won't cover every site. The deliberate choice is to stop before it becomes a maintenance burden — DOM heuristics past a certain depth cost more to maintain than the edge cases justify.

**Failure modes:**
- Sites with lazy-loaded images: `data-src` is the catch; if images are injected purely via JS after render, they won't appear in the raw HTML at all. Output will be image-sparse.
- Non-standard variant UIs (custom web components, canvas-rendered): option groups will be empty. Variants are modeled from whatever option groups exist; if none, `variants` is `[]`, which is valid.

---

### ExtractionContext [MVP1]

The intermediate bag passed between passes and into the assembler. It holds *lists of candidates*, not resolved values. Title might have three candidates; images might have fifteen. Nothing is decided yet.

This design isolates the extraction passes from the assembly step. Either pass can be changed or replaced without touching the other or the LLM prompt.

**Trade-offs:** It's intentionally loose — `dict` for attributes, plain strings for price candidates. Strict typing here would require mapping every site's structure to a schema before the LLM has had a chance to resolve it, which inverts the dependency.

**Failure modes:**
- Empty context (all passes fail): assembler receives empty candidate lists. LLM will return a nearly empty Product. The `name` and `price` fields are required; if truly absent, the pipeline raises and the product is skipped.

---

### Taxonomy pre-filter [MVP1]

`categories.txt` has ~5,600 lines. Passing all of them to the LLM every call is expensive and noisy. The pre-filter reduces this to ~20 candidates using token overlap between the product title, brand, and top breadcrumb term.

This is ~10 lines of Python: tokenize, score by overlap count, return top 20. No library needed. If the top candidate has zero overlap (completely unrecognized product), the filter returns top-level category segments as a broader fallback.

**Trade-offs:** Token overlap is a blunt instrument. It won't rank "Apparel & Accessories > Shoes" above "Apparel & Accessories > Clothing" for a sneaker — the LLM makes that call. The pre-filter only needs to get the right answer into the top 20, not rank it first.

**Failure modes:**
- No overlap with any category: fallback to broad segments. The LLM will pick the closest one, which may be imprecise but will be valid.
- Brand name matches unrelated category tokens: might surface irrelevant candidates. Rarely matters — the LLM ignores bad candidates when better ones are present.

---

### LLM assembler [MVP1]

A single async call to `gemini-2.0-flash-lite` using structured output (`text_format=Product`). The prompt provides the full `ExtractionContext` as JSON and the top 20 category candidates as a numbered list.

The LLM is responsible for: selecting the best title, description, and brand from candidates; picking the exact category string from the candidate list; building `Variant` objects from option groups (cartesian product, capped at 50); normalizing price strings into `Price`.

The LLM is *not* responsible for HTML parsing, URL resolution, or deduplication. Those are done before the LLM sees anything.

If the `Category` validator raises (LLM chose a string not in the taxonomy), the call retries once with the validation error appended to the prompt.

**Trade-offs:** Structured output is reliable on modern models but not perfect. The retry-once strategy handles transient failures without building a full retry loop that would hide systematic prompt issues. Flash-lite is cheap (~$0.005/call); if quality degrades on complex pages, the escalation path is flash-full, not a rewrite.

**Failure modes:**
- Structured output parse error: retry once; if still failing, return partial product with empty `key_features` and `variants`.
- LLM hallucates an image URL not in the context: prompt explicitly instructs it not to; still possible. Downstream image loading will 404.
- Wrong category after retry: logged and skipped. The validator is the gate — nothing invalid passes through.

---

### Storage — flat JSON files [MVP1]

`data/products/{id}.json` where `id = sha256(url)[:12]`. No database. The seed script writes these; the API reads them.

**Trade-offs:** Correct for this scope. A database would add setup, migrations, and a dependency for no benefit when the dataset is six products. The tradeoff inverts at ~10,000 products where scan time and concurrent write safety matter.

**Failure modes:**
- Concurrent writes to the same file (unlikely at this scale): last write wins. No corruption risk on POSIX filesystems for atomic rename-based writes.
- Disk full: write fails with an OS error. Not handled — out of scope.

---

### FastAPI [MVP1 — read-only; MVP3 — POST /extract]

**MVP1:** Two routes: `GET /products` (reads all JSON files, returns summaries), `GET /products/{id}` (reads one file, returns Product). The API layer contains no business logic. Extraction lives in `backend/extract/`, the API is just HTTP plumbing.

**MVP3 addition:** `POST /extract` (runs pipeline, writes file, returns Product).

**Trade-offs:** Synchronous reads on the GET routes are fine at this scale. `POST /extract` (when added) is async because the LLM call is I/O-bound.

**Failure modes:**
- `GET /products/{id}` with unknown ID: 404.
- Corrupted JSON file: parse error surfaced as 500. No partial recovery — the file should be re-seeded.

---

### Frontend [MVP1 — core; MVP2 — variants/gallery upgrade; MVP3 — polish]

**MVP1:** Two pages. Catalog at `/` renders a `ProductCard` grid fetched from `GET /products`. Detail at `/products/:id` renders image gallery, price, description, and variants (if any) from `GET /products/{id}`. shadcn components for all UI primitives.

**MVP2 additions:** `VariantsPanel` with attribute pill selectors. `ImageGallery` with full-res zoom and better thumbnail handling.

**MVP3 additions:** Skeleton loading states. Responsive layout tuning. `AttributesTable` for `raw_attributes`. Error boundaries.

**Trade-offs:** The data is pre-seeded; the frontend is read-only. This is the right call — adding upload/extract UI to the frontend would complicate both the UI and the API contract without being part of what's being evaluated.

**Failure modes:**
- API is not running: fetch errors surfaced as empty state, not crash.
- Product has no images: `ImageGallery` renders a placeholder.
- Variants array is empty: `VariantsPanel` is not rendered. No empty state needed.

---

## What is deferred vs cut

| Item | Status | Reason |
|------|--------|--------|
| Pass 2: DOM extraction | **MVP2** | Quality improvement; not needed for happy path |
| Rich variant selectors | **MVP2** | Requires option group parsing from Pass 2 |
| `POST /extract` endpoint | **MVP3** | Seed script covers extraction; API stays read-only in MVP1 |
| Skeleton loading states | **MVP3** | Polish — not blocking |
| `AttributesTable` | **MVP3** | Display enhancement |
| BM25 taxonomy retrieval | **Cut** | Token overlap achieves the same result in 10 lines |
| Per-variant image/price linking | **Cut** | Requires per-variant script blob mining; diminishing return |
| Microdata parsing | **Cut** | JSON-LD covers the same pages better |
| Evidence/provenance tracking | **Cut** | No payoff at this scope |
| Debug drawer in UI | **Cut** | Not asked for |
