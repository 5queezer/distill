"""Search quality — noise filter, min score, recency boost.

Tests the three quick wins that prevent low-quality storage and retrieval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import (
    MIN_CONTENT_LENGTH,
    MIN_SEARCH_SCORE,
    RECENCY_WEIGHT,
    MemoryService,
)

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return f"Distilled: {raw_text}"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self, search_results: list[SearchResult] | None = None) -> None:
        self._search_results = search_results or []

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        return memory.id

    async def get(self, id: str) -> None:
        return None

    async def delete(self, id: str) -> None:
        pass

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
    ) -> list[SearchResult]:
        return list(self._search_results)

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass


def _service(search_results: list[SearchResult] | None = None) -> MemoryService:
    return MemoryService(
        storage=FakeStorage(search_results),
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=False,
    )


def _memory(*, days_old: int = 0) -> Memory:
    return Memory(
        id="test-id",
        content="Some fact",
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=days_old),
    )


# -- Noise filter tests --


class TestNoiseFilter:
    async def test_rejects_greeting(self) -> None:
        result = await _service().remember("hello", "context", ["r"])
        assert result["status"] == "rejected"
        assert "trivial" in result["reason"]

    async def test_rejects_emoji_reaction(self) -> None:
        result = await _service().remember("\U0001f44d", "context", ["r"])
        assert result["status"] == "rejected"

    async def test_rejects_short_input(self) -> None:
        result = await _service().remember("too short", "context", ["r"])
        assert result["status"] == "rejected"
        assert str(MIN_CONTENT_LENGTH) in result["reason"]

    async def test_accepts_substantive_input(self) -> None:
        result = await _service().remember(
            "We decided to use PostgreSQL for the main database because of pgvector support.",
            "decision",
            ["repo"],
        )
        assert result["status"] == "saved"

    async def test_noise_check_is_case_insensitive(self) -> None:
        result = await _service().remember("THANKS", "context", ["r"])
        assert result["status"] == "rejected"

    async def test_noise_check_strips_whitespace(self) -> None:
        result = await _service().remember("  ok  ", "context", ["r"])
        assert result["status"] == "rejected"


# -- Hard min score tests --


class TestMinScore:
    async def test_drops_low_score_results(self) -> None:
        results_from_db = [
            SearchResult(memory=_memory(), score=0.016),
            SearchResult(memory=_memory(), score=0.02),
        ]
        results = await _service(results_from_db).search("fastmcp")
        assert len(results) == 0

    async def test_keeps_high_score_results(self) -> None:
        results_from_db = [
            SearchResult(memory=_memory(), score=0.8),
            SearchResult(memory=_memory(), score=0.5),
        ]
        results = await _service(results_from_db).search("fastmcp")
        assert len(results) == 2

    async def test_mixed_scores_filters_correctly(self) -> None:
        results_from_db = [
            SearchResult(memory=_memory(), score=0.7),
            SearchResult(memory=_memory(), score=0.1),
            SearchResult(memory=_memory(), score=0.5),
        ]
        results = await _service(results_from_db).search("query")
        assert len(results) == 2
        assert all(r.score >= MIN_SEARCH_SCORE for r in results)


# -- Recency boost tests --


class TestRecencyBoost:
    async def test_recent_memory_gets_boosted(self) -> None:
        fresh = SearchResult(memory=_memory(days_old=0), score=0.5)
        old = SearchResult(memory=_memory(days_old=90), score=0.5)
        results = await _service([fresh, old]).search("query")
        assert results[0].score > results[1].score

    async def test_recency_doesnt_dominate(self) -> None:
        """A much higher base score should still win over recency."""
        old_but_relevant = SearchResult(memory=_memory(days_old=60), score=0.9)
        fresh_but_weak = SearchResult(memory=_memory(days_old=0), score=0.4)
        results = await _service([old_but_relevant, fresh_but_weak]).search("query")
        assert results[0].score > results[1].score

    async def test_weibull_recency_formula_correctness(self) -> None:
        """Verify Weibull decay for a known type and age."""
        import math

        from distill_mcp.domain.services import WEIBULL_PARAMS

        days_old = 14
        m = _memory(days_old=days_old)  # type="decision"
        sr = SearchResult(memory=m, score=0.6)
        results = await _service([sr]).search("query")
        # decision: λ=14, k=1.5
        scale, shape = WEIBULL_PARAMS["decision"]
        recency = math.exp(-((days_old / scale) ** shape))
        expected = (1 - RECENCY_WEIGHT) * 0.6 + RECENCY_WEIGHT * recency
        assert abs(results[0].score - expected) < 0.001

    async def test_results_sorted_by_boosted_score(self) -> None:
        r1 = SearchResult(memory=_memory(days_old=1), score=0.5)
        r2 = SearchResult(memory=_memory(days_old=0), score=0.5)
        r3 = SearchResult(memory=_memory(days_old=100), score=0.5)
        results = await _service([r1, r2, r3]).search("query")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# -- Weibull type-aware decay tests --


def _typed_memory(*, days_old: int = 0, type: str = "decision") -> Memory:
    return Memory(
        id=f"test-{type}-{days_old}",
        content="Some fact about things",
        type=type,
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=days_old),
    )


class TestWeibullDecay:
    async def test_fresh_memory_gets_full_recency(self) -> None:
        """Age 0 should give recency=1.0 regardless of type."""
        from distill_mcp.domain.services import MemoryService

        for mtype in ["decision", "pattern", "failure", "dependency", "context"]:
            assert MemoryService._weibull_recency(0, mtype) == 1.0

    async def test_decision_decays_faster_than_pattern(self) -> None:
        """At 30 days, a decision should have decayed more than a pattern."""
        from distill_mcp.domain.services import MemoryService

        decision_recency = MemoryService._weibull_recency(30, "decision")
        pattern_recency = MemoryService._weibull_recency(30, "pattern")
        assert decision_recency < pattern_recency

    async def test_context_decays_fastest(self) -> None:
        """Context (λ=7, k=2) should decay fastest at 14 days."""
        from distill_mcp.domain.services import MemoryService

        context = MemoryService._weibull_recency(14, "context")
        decision = MemoryService._weibull_recency(14, "decision")
        failure = MemoryService._weibull_recency(14, "failure")
        assert context < decision < failure

    async def test_dependency_decays_slowest(self) -> None:
        """Dependency (λ=180, k=0.7) should retain most value at 90 days."""
        from distill_mcp.domain.services import MemoryService

        dependency = MemoryService._weibull_recency(90, "dependency")
        pattern = MemoryService._weibull_recency(90, "pattern")
        decision = MemoryService._weibull_recency(90, "decision")
        assert dependency > pattern > decision

    async def test_unknown_type_uses_default(self) -> None:
        """Unknown types should use the default exponential decay."""
        import math

        from distill_mcp.domain.services import WEIBULL_DEFAULT, MemoryService

        recency = MemoryService._weibull_recency(30, "unknown_type")
        scale, shape = WEIBULL_DEFAULT
        expected = math.exp(-((30 / scale) ** shape))
        assert abs(recency - expected) < 0.001

    async def test_type_aware_search_scoring(self) -> None:
        """Same age and base score, but different types should get different final scores."""
        days_old = 30
        decision_mem = _typed_memory(days_old=days_old, type="decision")
        pattern_mem = _typed_memory(days_old=days_old, type="pattern")

        results_from_db = [
            SearchResult(memory=decision_mem, score=0.6),
            SearchResult(memory=pattern_mem, score=0.6),
        ]
        results = await _service(results_from_db).search("query")

        # Pattern should score higher (slower decay)
        pattern_result = next(r for r in results if r.id.startswith("test-pattern"))
        decision_result = next(r for r in results if r.id.startswith("test-decision"))
        assert pattern_result.score > decision_result.score
