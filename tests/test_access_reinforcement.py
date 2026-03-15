"""Access reinforcement — spaced-repetition-inspired scoring.

Tests that frequently accessed memories get a boost in search ranking,
and that access tracking is recorded correctly.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import (
    ACCESS_BOOST_WEIGHT,
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
        self.access_log: list[str] = []

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
        self.access_log.append(id)


def _service(
    search_results: list[SearchResult] | None = None,
) -> tuple[MemoryService, FakeStorage]:
    storage = FakeStorage(search_results)
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
    )
    return svc, storage


_seq = count()


def _memory(*, days_old: int = 0, access_count: int = 0) -> Memory:
    return Memory(
        id=f"mem-{next(_seq)}",
        content="Some fact",
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=days_old),
        access_count=access_count,
    )


# -- Access boost tests --


class TestAccessBoost:
    async def test_frequently_accessed_ranks_higher(self) -> None:
        """A memory accessed 10 times should rank above one never accessed,
        given equal base scores and age."""
        popular = SearchResult(memory=_memory(access_count=10), score=0.5)
        unused = SearchResult(memory=_memory(access_count=0), score=0.5)
        svc, _ = _service([popular, unused])
        results = await svc.search("query")
        assert results[0].memory.access_count == 10
        assert results[0].score > results[1].score

    async def test_access_boost_formula(self) -> None:
        """Verify the exact boost for a known access count."""
        m = _memory(access_count=5)
        sr = SearchResult(memory=m, score=0.6)
        svc, _ = _service([sr])
        results = await svc.search("query")

        # recency for days_old=0: 1/(1+0/30) = 1.0
        after_recency = (1 - RECENCY_WEIGHT) * 0.6 + RECENCY_WEIGHT * 1.0
        # access boost: log(5+1) * 0.1
        expected = after_recency * (1.0 + math.log(6) * ACCESS_BOOST_WEIGHT)
        assert abs(results[0].score - expected) < 0.001

    async def test_zero_access_no_boost(self) -> None:
        """A memory with 0 accesses should get no boost (log(1) = 0)."""
        m = _memory(access_count=0)
        sr = SearchResult(memory=m, score=0.6)
        svc, _ = _service([sr])
        results = await svc.search("query")

        after_recency = (1 - RECENCY_WEIGHT) * 0.6 + RECENCY_WEIGHT * 1.0
        # log(0+1) = 0 → multiplier is 1.0 → no change
        assert abs(results[0].score - after_recency) < 0.001

    async def test_access_boost_doesnt_override_relevance(self) -> None:
        """A highly relevant but unaccessed memory should still beat
        a weakly relevant but frequently accessed one."""
        relevant = SearchResult(memory=_memory(access_count=0), score=0.9)
        popular = SearchResult(memory=_memory(access_count=50), score=0.4)
        svc, _ = _service([relevant, popular])
        results = await svc.search("query")
        assert results[0].memory.access_count == 0
        assert results[0].score > results[1].score


# -- Access recording tests --


class TestAccessRecording:
    async def test_search_records_access_for_returned_results(self) -> None:
        """Each returned result should trigger an access record."""
        r1 = SearchResult(memory=_memory(access_count=0), score=0.5)
        r2 = SearchResult(memory=_memory(access_count=3), score=0.6)
        svc, storage = _service([r1, r2])
        results = await svc.search("query")
        await asyncio.sleep(0.01)
        assert len(storage.access_log) == len(results)

    async def test_filtered_results_not_recorded(self) -> None:
        """Results dropped by min-score filter should not get access recorded."""
        above = SearchResult(memory=_memory(access_count=0), score=0.6)
        below = SearchResult(memory=_memory(access_count=0), score=0.01)
        svc, storage = _service([above, below])
        await svc.search("query")
        await asyncio.sleep(0.01)
        assert len(storage.access_log) == 1
