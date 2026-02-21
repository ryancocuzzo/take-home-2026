"""
Cross-merchant product deduplication.

  1. Compare every product pair. Match if: shared GTIN/UPC, or title+brand similarity ≥ threshold.
  2. Cluster matches via networkx.connected_components (A↔B and B↔C ⇒ A,B,C in one group).
  3. Assign each cluster a stable canonical ID (hash of sorted product IDs).
  4. Attach match_decision (evidence + confidence) to each product.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import networkx as nx

from models import MatchDecision, MatchEvidence, Product


_GTIN_PATTERN = re.compile(r"\b\d{8,14}\b")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _read_env_float(name: str, default: float) -> float:
    """Read env var as float; return default if unset or invalid."""
    raw = os.getenv(name)
    if raw is None: 
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _normalize_text(value: str) -> str:
    """Lowercase and replace non-alphanumeric runs with spaces."""
    lowered = value.lower().strip()
    return _NON_ALNUM.sub(" ", lowered).strip()


@dataclass(frozen=True)
class IdentityResolverConfig:
    """Thresholds and weights for matching. Overridable via IDENTITY_* env vars."""

    match_threshold: float = 0.72
    title_brand_min_similarity: float = 0.62
    upc_weight: float = 0.75
    title_brand_weight: float = 0.25

    @classmethod
    def from_env(cls) -> "IdentityResolverConfig":
        """Build config from IDENTITY_* env vars, falling back to defaults."""
        return cls(
            match_threshold=_read_env_float("IDENTITY_MATCH_THRESHOLD", 0.72),
            title_brand_min_similarity=_read_env_float(
                "IDENTITY_TITLE_BRAND_MIN_SIMILARITY", 0.62
            ),
            upc_weight=_read_env_float("IDENTITY_UPC_WEIGHT", 0.75),
            title_brand_weight=_read_env_float("IDENTITY_TITLE_BRAND_WEIGHT", 0.25),
        )


@dataclass(frozen=True)
class _PairwiseMatchResult:
    matched: bool
    confidence: float
    evidence: list[MatchEvidence]


class IdentityResolver:
    """Deduplicates products by GTIN and title+brand similarity, assigns canonical IDs."""

    def __init__(self, config: IdentityResolverConfig | None = None) -> None:
        self.config = config or IdentityResolverConfig.from_env()

    def assign_canonical_products(self, products_by_id: dict[str, Product]) -> dict[str, Product]:
        """Run dedupe: set canonical_product_id and match_decision on each product. Mutates copies, returns updated dict."""
        if not products_by_id:
            return {}

        products: dict[str, Product] = {
            pid: product.model_copy(deep=True) for pid, product in products_by_id.items()
        }
        ids = sorted(products.keys())
        pairwise: dict[tuple[str, str], _PairwiseMatchResult] = {}

        for i, left_id in enumerate(ids):
            for right_id in ids[i + 1 :]:
                result = self._evaluate_pair(products[left_id], products[right_id])
                pairwise[(left_id, right_id)] = result
                pairwise[(right_id, left_id)] = result

        components = self._connected_components(pairwise)
        for component in components:
            canonical_id = self._canonical_id_for_component(component)
            for pid in component:
                products[pid].canonical_product_id = canonical_id

        for pid in ids:
            best_id, best_result = self._best_candidate(pid, ids, pairwise)
            products[pid].match_decision = MatchDecision(
                candidate_product_id=best_id,
                matched=best_result.matched,
                confidence=best_result.confidence,
                threshold=self.config.match_threshold,
                evidence=best_result.evidence,
            )

        return products

    def _best_candidate(
        self,
        pid: str,
        ids: list[str],
        pairwise: dict[tuple[str, str], _PairwiseMatchResult],
    ) -> tuple[str | None, _PairwiseMatchResult]:
        """Return the other product with highest match confidence for pid; ties broken by id sort order."""
        best_id: str | None = None
        best_result: _PairwiseMatchResult | None = None
        for other_id in ids:
            if other_id == pid:
                continue
            result = pairwise[(pid, other_id)]
            if best_result is None:
                best_id = other_id
                best_result = result
                continue
            if result.confidence > best_result.confidence:
                best_id = other_id
                best_result = result
                continue
            if result.confidence == best_result.confidence and best_id is not None:
                if other_id < best_id:
                    best_id = other_id
                    best_result = result

        if best_result is None:
            return None, self._singleton_decision()
        return best_id, best_result

    def _connected_components(
        self,
        pairwise: dict[tuple[str, str], _PairwiseMatchResult],
    ) -> list[list[str]]:
        """Group product IDs into clusters where matched pairs form edges. Uses networkx."""
        graph = nx.Graph()
        for (left_id, right_id), result in pairwise.items():
            graph.add_node(left_id)
            graph.add_node(right_id)
            if result.matched:
                graph.add_edge(left_id, right_id)
        return [sorted(component) for component in nx.connected_components(graph)]

    def _canonical_id_for_component(self, component: list[str]) -> str:
        """Hash of sorted product IDs → cp_<hex>. Stable across reruns (IDs are deterministic)."""
        canonical_key = "||".join(sorted(component))
        digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:16]
        return f"cp_{digest}"

    def _evaluate_pair(self, left: Product, right: Product) -> _PairwiseMatchResult:
        """Score two products: GTIN overlap + title/brand similarity → matched, confidence, evidence."""
        left_gtins = self._extract_gtin_codes(left)
        right_gtins = self._extract_gtin_codes(right)
        shared_gtins = sorted(left_gtins & right_gtins)
        upc_score = 1.0 if shared_gtins else 0.0

        title_brand_score = self._title_brand_similarity(left, right)

        evidence = [
            MatchEvidence(
                signal="upc_gtin_exact_match",
                score=upc_score,
                matched=bool(shared_gtins),
                details={"shared_codes": shared_gtins},
            ),
            MatchEvidence(
                signal="title_brand_similarity",
                score=title_brand_score,
                matched=title_brand_score >= self.config.title_brand_min_similarity,
                details={"left_brand": left.brand, "right_brand": right.brand},
            ),
        ]

        weighted = (
            self.config.upc_weight * upc_score
            + self.config.title_brand_weight * title_brand_score
        )
        total_weight = (
            self.config.upc_weight
            + self.config.title_brand_weight
        )
        confidence = weighted / total_weight if total_weight > 0 else 0.0
        if shared_gtins:
            confidence = max(confidence, 0.95)

        matched = bool(shared_gtins) or confidence >= self.config.match_threshold
        return _PairwiseMatchResult(matched=matched, confidence=confidence, evidence=evidence)

    def _singleton_decision(self) -> _PairwiseMatchResult:
        """Placeholder when there are no other products to compare against."""
        return _PairwiseMatchResult(
            matched=False,
            confidence=0.0,
            evidence=[
                MatchEvidence(
                    signal="upc_gtin_exact_match",
                    score=0.0,
                    matched=False,
                    details={"reason": "no_other_products"},
                ),
                MatchEvidence(
                    signal="title_brand_similarity",
                    score=0.0,
                    matched=False,
                    details={"reason": "no_other_products"},
                ),
            ],
        )

    def _extract_gtin_codes(self, product: Product) -> set[str]:
        """Find 8–14 digit barcode-like numbers in name, description, features, source URLs."""
        fields: list[str] = [product.name, product.description, product.brand]
        fields.extend(product.key_features)
        for offer in product.offers:
            if offer.source_url:
                fields.append(offer.source_url)

        found: set[str] = set()
        for field in fields:
            for candidate in _GTIN_PATTERN.findall(field):
                found.add(candidate)
        return found

    def _title_brand_similarity(self, left: Product, right: Product) -> float:
        """SequenceMatcher ratio on title (75%) and brand (25%), 0–1."""
        left_title = _normalize_text(left.name)
        right_title = _normalize_text(right.name)
        left_brand = _normalize_text(left.brand)
        right_brand = _normalize_text(right.brand)

        title_ratio = SequenceMatcher(None, left_title, right_title).ratio()
        brand_ratio = SequenceMatcher(None, left_brand, right_brand).ratio()
        return (0.75 * title_ratio) + (0.25 * brand_ratio)
