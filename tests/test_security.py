"""Security — search bounds checking.

Oversized input, noise filtering, and distillation error propagation
moved to the worker pipeline (ObservationWorker). The search top_k bounds
are tested here as they belong to MemoryService.search().
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        self._memories[memory.id] = memory
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        self._memories.pop(id, None)

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
    ) -> list[SearchResult]:
        results = []
        for mem in self._memories.values():
            if agent_id is not None and mem.agent_id != agent_id:
                continue
            results.append(SearchResult(memory=mem, score=0.9))
        return results[:top_k]

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return "Distilled fact"


def _service(
    storage: FakeStorage | None = None,
) -> tuple[MemoryService, FakeStorage]:
    if storage is None:
        storage = FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
    )
    return svc, storage


def _mem(id: str = "test") -> Memory:
    return Memory(
        id=id,
        content="PostgreSQL chosen for pgvector support in the project",
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )


# -- Search top_k bounds --


async def test_search_large_top_k_does_not_crash() -> None:
    """Verify search handles large top_k values without crashing."""
    storage = FakeStorage()
    storage._memories["m1"] = _mem("m1")
    svc, _ = _service(storage)
    results = await svc.search("PostgreSQL", top_k=999_999)
    assert isinstance(results, list)


async def test_search_top_k_zero_returns_empty() -> None:
    """top_k=0 should return empty results, not crash."""
    storage = FakeStorage()
    storage._memories["m1"] = _mem("m1")
    svc, _ = _service(storage)
    results = await svc.search("PostgreSQL", top_k=0)
    assert isinstance(results, list)
    assert len(results) == 0
