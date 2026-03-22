"""Temporal range filter — search with after/before date bounds.

Covers issue #70: temporal range filtering for search_memory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return "Distilled fact"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self._memories[memory.id] = memory
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

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
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[SearchResult]:
        results = []
        for mem in self._memories.values():
            if after is not None and mem.created_at < after:
                continue
            if before is not None and mem.created_at > before:
                continue
            results.append(SearchResult(memory=mem, score=0.8))
        return results[:top_k]

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec: Any, **kw: Any) -> list:
        return []

    async def check_duplicate(self, vec: Any, **kw: Any) -> str | None:
        return None

    async def get_lineage(self, memory_id: str) -> list[dict]:
        return []

    async def purge_expired(self, retention_days: int) -> int:
        return 0


def _make_memory(id: str, age_days: int) -> Memory:
    return Memory(
        id=id,
        content=f"Memory {id} about architecture decisions",
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


def _service(memories: list[Memory]) -> MemoryService:
    storage = FakeStorage()
    for mem in memories:
        storage._memories[mem.id] = mem
    return MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
    )


class TestTemporalFilter:
    async def test_after_filters_old_memories(self) -> None:
        """Only memories created after the cutoff should be returned."""
        memories = [
            _make_memory("old", age_days=60),
            _make_memory("recent", age_days=5),
        ]
        svc = _service(memories)
        cutoff = datetime.now(UTC) - timedelta(days=30)
        results = await svc.search("architecture", after=cutoff)
        ids = {r.id for r in results}
        assert "recent" in ids
        assert "old" not in ids

    async def test_before_filters_new_memories(self) -> None:
        """Only memories created before the cutoff should be returned."""
        memories = [
            _make_memory("old", age_days=60),
            _make_memory("recent", age_days=5),
        ]
        svc = _service(memories)
        cutoff = datetime.now(UTC) - timedelta(days=30)
        results = await svc.search("architecture", before=cutoff)
        ids = {r.id for r in results}
        assert "old" in ids
        assert "recent" not in ids

    async def test_after_and_before_combined(self) -> None:
        """Date range: only memories within the window should be returned."""
        memories = [
            _make_memory("ancient", age_days=90),
            _make_memory("middle", age_days=45),
            _make_memory("recent", age_days=5),
        ]
        svc = _service(memories)
        after = datetime.now(UTC) - timedelta(days=60)
        before = datetime.now(UTC) - timedelta(days=10)
        results = await svc.search("architecture", after=after, before=before)
        ids = {r.id for r in results}
        assert ids == {"middle"}

    async def test_no_temporal_filter_returns_all(self) -> None:
        memories = [
            _make_memory("old", age_days=60),
            _make_memory("recent", age_days=5),
        ]
        svc = _service(memories)
        results = await svc.search("architecture")
        assert len(results) == 2

    async def test_after_in_future_returns_nothing(self) -> None:
        memories = [_make_memory("m1", age_days=5)]
        svc = _service(memories)
        future = datetime.now(UTC) + timedelta(days=1)
        results = await svc.search("architecture", after=future)
        assert len(results) == 0

    async def test_before_in_past_returns_nothing(self) -> None:
        memories = [_make_memory("m1", age_days=5)]
        svc = _service(memories)
        past = datetime.now(UTC) - timedelta(days=365)
        results = await svc.search("architecture", before=past)
        assert len(results) == 0
