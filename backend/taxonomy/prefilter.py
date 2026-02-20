"""
Taxonomy prefilter: fast keyword-based candidate selection.

THE PROBLEM
-----------
We have ~5,000 job categories ("Software Development > Backend", "Marketing > SEO", etc.)
and an incoming job posting. We can't send all 5,000 categories to the LLM — it's too slow
and expensive. We need to narrow it down to ~20 plausible candidates first.

THE APPROACH: BM25
------------------
We use BM25 (Best Match 25), a proven ranking algorithm used in search engines.
Like TF-IDF, BM25 scores documents by how well they match a query's keywords.
It improves on raw TF-IDF in two ways:

  Term saturation: repeating a word in a document has diminishing returns.
    A category with "shoes shoes shoes" doesn't score 3x a category with "shoes" once.

  Document length normalisation: shorter documents aren't penalised just for being short.
    A short category label "Shoes" can still score well against a long one.

Each category label is treated as a small document. The job posting signals
(title, brand, category hints) form the query. BM25 scores how well each
category matches that query. We return the top_k highest-scoring categories.

FALLBACK
--------
If no category scores above 0 (zero vocabulary overlap), we return a broad
spread of top-level taxonomy segments so the LLM still has something to work with.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from models import ExtractionContext, VALID_CATEGORIES

# Matches runs of lowercase letters and digits (after lowercasing input).
# Punctuation, slashes, and other separators are treated as word boundaries.
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Common English words that carry no signal for category matching.
# Removing them reduces noise in the BM25 scoring.
_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass
class _TaxonomyIndex:
    """
    The pre-built BM25 index over all category labels.

    Built once per unique set of categories (cached), then reused for every query.
    The `categories` tuple preserves insertion order so BM25 score positions
    map directly back to category names.
    """

    categories: tuple[str, ...]
    bm25: BM25Okapi


def select_category_candidates(
    context: ExtractionContext,
    categories: list[str] | None = None,
    top_k: int = 20,
) -> list[str]:
    """
    Return up to `top_k` category labels most relevant to the given extraction context.

    This is the main entry point. It orchestrates all steps:
      1. Resolve the category list to search against.
      2. Build (or reuse a cached) BM25 index over those categories.
      3. Convert the job posting context into a query token list.
      4. Score every category via BM25.
      5. Return the top-k unique results, or fall back if nothing matched.

    Args:
        context:    Signals extracted from the job posting (title, brand, category hints).
        categories: Explicit list of categories to rank. Defaults to all VALID_CATEGORIES.
        top_k:      Maximum number of candidates to return.
    """
    if top_k <= 0:
        return []

    category_tuple = _materialize_categories(categories)
    if not category_tuple:
        return []

    index = _build_index(category_tuple)
    query_terms = _build_query_terms(context)
    if not query_terms:
        # No usable text from the posting — fall back to broad coverage
        return _fallback_categories(index.categories, top_k)

    scored = _score_categories(index, query_terms)
    if not scored or scored[0][0] <= 0:
        # Best match scored 0, meaning zero vocabulary overlap with every category — fall back
        return _fallback_categories(index.categories, top_k)

    limit = min(top_k, len(index.categories))
    return _collect_unique_categories(scored, limit)


def _materialize_categories(categories: list[str] | None) -> tuple[str, ...]:
    """
    Resolve the caller-supplied category list into a clean, sorted, deduplicated tuple.

    A tuple (rather than a list) is required because it is hashable, which allows
    _build_index to cache its result keyed on this value.

    If `categories` is None, the full VALID_CATEGORIES set is used.
    """
    if categories is None:
        return tuple(sorted(VALID_CATEGORIES))

    cleaned = sorted({value.strip() for value in categories if value and value.strip()})
    return tuple(cleaned)


@lru_cache(maxsize=4)
def _build_index(categories: tuple[str, ...]) -> _TaxonomyIndex:
    """
    Build a BM25 index over all category labels.

    Tokenises every category label and fits a BM25Okapi model on the corpus.
    The result is cached so it's only built once per unique category set.

    BM25Okapi handles empty token lists gracefully (score = 0 for that document),
    so categories that produce no tokens after stopword removal are safe to include.
    """
    tokenized = [_tokenize(cat) for cat in categories]
    return _TaxonomyIndex(categories=categories, bm25=BM25Okapi(tokenized))


def _build_query_terms(context: ExtractionContext) -> list[str]:
    """
    Flatten the most informative fields from the extraction context into a list of tokens.

    We cap the number of candidates per field to prevent any single noisy signal
    from drowning out the others (e.g. 10 title candidates vs 2 brand candidates).
    """
    values: list[str] = []
    values.extend(context.title_candidates[:3])
    values.extend(context.brand_candidates[:2])
    values.extend(context.category_hint_candidates[:3])

    terms: list[str] = []
    for value in values:
        terms.extend(_tokenize(value))
    return terms


def _tokenize(value: str) -> list[str]:
    """
    Convert a raw string into a list of meaningful tokens.

    Steps:
      1. Lowercase everything.
      2. Extract runs of alphanumeric characters (strips punctuation/symbols).
      3. Drop stopwords and single-character tokens.

    Example:
        "Software Development > Back-End" → ["software", "development", "back", "end"]
    """
    text = value.lower()
    tokens = _TOKEN_PATTERN.findall(text)
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _score_categories(
    index: _TaxonomyIndex,
    query_terms: list[str],
) -> list[tuple[float, str]]:
    """
    Score every category against the query using BM25, sorted best-first.

    BM25Okapi.get_scores() returns one score per document in corpus order.
    We zip those scores back with the original category strings, then sort
    descending by score (ties broken alphabetically for determinism).
    """
    raw_scores = index.bm25.get_scores(query_terms)
    scored = [
        (float(score), category)
        for score, category in zip(raw_scores, index.categories)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def _collect_unique_categories(scored: list[tuple[float, str]], limit: int) -> list[str]:
    """
    Return up to `limit` unique category strings from a scored list.

    The same category string could in theory appear multiple times (e.g. if the caller
    passed a list with duplicates). This guards against that.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for _, category in scored:
        if category in seen:
            continue
        unique.append(category)
        seen.add(category)
        if len(unique) >= limit:
            break
    return unique


def _fallback_categories(categories: tuple[str, ...], top_k: int) -> list[str]:
    """
    Return a broad spread of categories when BM25 scoring finds no match.

    This happens when the query has zero vocabulary overlap with every category label.
    Rather than returning nothing (which would give the LLM nothing to work with),
    we return a diverse sample by preferring top-level taxonomy segments first.

    Strategy:
      Pass 1 — collect the first segment of each category path (e.g. "Software Development"
               from "Software Development > Backend"). One per unique top-level segment,
               to maximise breadth. Stop once we reach top_k.
      Pass 2 — if we still need more, fill remaining slots with full category paths
               that weren't already included.

    Example (top_k=3, categories include many "Software Development > *" entries):
        Pass 1 yields: ["Software Development", "Marketing", "Design"]
        (three different top-level segments, not three sub-paths of the same one)
    """
    if top_k <= 0:
        return []

    ordered: list[str] = []
    seen: set[str] = set()

    # Pass 1: one representative per top-level taxonomy segment
    for category in categories:
        segment = category.split(" > ", 1)[0]
        if segment in seen:
            continue
        ordered.append(segment)
        seen.add(segment)
        if len(ordered) >= top_k:
            return ordered

    # Pass 2: fill remaining slots with full category paths not yet covered
    for category in categories:
        if category in seen:
            continue
        ordered.append(category)
        seen.add(category)
        if len(ordered) >= top_k:
            break

    return ordered
