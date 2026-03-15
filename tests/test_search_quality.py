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
    RECENCY_HALFLIFE_DAYS,
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

    async def test_recency_formula_correctness(self) -> None:
        """Verify the exact recency boost for a known age."""
        m = _memory(days_old=RECENCY_HALFLIFE_DAYS)
        sr = SearchResult(memory=m, score=0.6)
        results = await _service([sr]).search("query")
        # recency = 1/(1 + 30/30) = 0.5
        # final = 0.85 * 0.6 + 0.15 * 0.5 = 0.51 + 0.075 = 0.585
        expected = (1 - RECENCY_WEIGHT) * 0.6 + RECENCY_WEIGHT * 0.5
        assert abs(results[0].score - expected) < 0.001

    async def test_results_sorted_by_boosted_score(self) -> None:
        r1 = SearchResult(memory=_memory(days_old=1), score=0.5)
        r2 = SearchResult(memory=_memory(days_old=0), score=0.5)
        r3 = SearchResult(memory=_memory(days_old=100), score=0.5)
        results = await _service([r1, r2, r3]).search("query")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
