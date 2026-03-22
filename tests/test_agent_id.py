"""Agent ID — verify multi-agent memory support."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output
        self.last_input: str = ""

    async def distill(self, raw_text: str) -> str:
        self.last_input = raw_text
        return self._output


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self, *, fail_save: bool = False) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}
        self._fail_save = fail_save

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        if self._fail_save:
            raise RuntimeError("storage write failed")
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

    async def list_recent(
        self,
        *,
        repo: str | None = None,
        tag: str | None = None,
        type: str | None = None,
        limit: int = 20,
        agent_id: str | None = None,
    ) -> list[Memory]:
        results = list(self._memories.values())
        if agent_id is not None:
            results = [m for m in results if m.agent_id == agent_id]
        return results[:limit]

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


def _service(
    *,
    fail_save: bool = False,
) -> tuple[MemoryService, FakeStorage, FakeDistiller]:
    storage = FakeStorage(fail_save=fail_save)
    distiller = FakeDistiller()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=distiller,
        distill_enabled=True,
    )
    return svc, storage, distiller


async def _insert(
    storage: FakeStorage,
    content: str = "Distilled fact",
    *,
    type: str = "decision",
    repos: list[str] | None = None,
    agent_id: str | None = None,
) -> Memory:
    """Insert a Memory directly into FakeStorage, bypassing distillation."""
    from datetime import UTC, datetime
    from uuid import uuid4

    mem = Memory(
        id=uuid4().hex,
        content=content,
        type=type,
        repos=repos or ["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
        agent_id=agent_id,
    )
    await storage.save(mem, [0.1] * 768)
    return mem


# -- Tests --


async def test_agent_id_stored_in_memory() -> None:
    _, storage, _ = _service()
    mem = await _insert(storage, agent_id="zeroclaw")
    assert storage.saved[0].agent_id == "zeroclaw"
    assert mem.agent_id == "zeroclaw"


async def test_agent_id_none_stored_correctly() -> None:
    _, storage, _ = _service()
    mem = await _insert(storage, agent_id=None)
    assert storage.saved[0].agent_id is None
    assert mem.agent_id is None


async def test_search_filters_by_agent_id() -> None:
    svc, storage, _ = _service()
    await _insert(storage, "asyncpg for async PostgreSQL", agent_id="agent-a")
    await _insert(storage, "FastAPI chosen for REST layer", agent_id="agent-b")

    results = await svc.search("postgres", agent_id="agent-a")
    assert all(r.agent_id == "agent-a" for r in results)


async def test_search_without_filter_returns_all() -> None:
    svc, storage, _ = _service()
    await _insert(storage, "asyncpg for async PostgreSQL", agent_id="agent-a")
    await _insert(storage, "FastAPI chosen for REST layer", agent_id="agent-b")

    results = await svc.search("chosen")
    agent_ids = {r.agent_id for r in results}
    assert "agent-a" in agent_ids
    assert "agent-b" in agent_ids


async def test_list_recent_filters_by_agent_id() -> None:
    svc, storage, _ = _service()
    await _insert(storage, "asyncpg for async PostgreSQL", agent_id="agent-a")
    await _insert(storage, "FastAPI chosen for REST layer", agent_id="agent-b")

    results = await svc.list_recent(agent_id="agent-b")
    assert all(m.agent_id == "agent-b" for m in results)
    assert len(results) == 1


async def test_concurrent_inserts_from_two_agents() -> None:
    """Two agents inserting simultaneously — both memories stored correctly."""
    _, storage, _ = _service()
    await asyncio.gather(
        _insert(storage, "asyncpg for async PostgreSQL", agent_id="agent-a"),
        _insert(storage, "FastAPI for REST layer service", agent_id="agent-b"),
    )
    assert len(storage.saved) == 2
    agent_ids = {m.agent_id for m in storage.saved}
    assert agent_ids == {"agent-a", "agent-b"}


# -- forget() agent isolation --


async def test_forget_own_memory_succeeds() -> None:
    """An agent can delete its own memory."""
    svc, storage, _ = _service()
    mem = await _insert(storage, agent_id="agent-a")

    out = await svc.forget(mem.id, agent_id="agent-a")
    assert out["status"] == "forgotten"
    assert out["id"] == mem.id


async def test_forget_other_agents_memory_forbidden() -> None:
    """Agent B cannot delete Agent A's memory."""
    svc, storage, _ = _service()
    mem = await _insert(storage, agent_id="agent-a")

    out = await svc.forget(mem.id, agent_id="agent-b")
    assert out["status"] == "forbidden"
    assert "different agent" in out["reason"]
    # Memory should still exist
    assert await svc.get(mem.id) is not None


async def test_forget_without_agent_id_always_deletes() -> None:
    """When no agent_id is provided, any memory can be deleted (admin path)."""
    svc, storage, _ = _service()
    mem = await _insert(storage, agent_id="agent-a")

    out = await svc.forget(mem.id)
    assert out["status"] == "forgotten"


async def test_forget_nonexistent_returns_not_found() -> None:
    svc, _, _ = _service()
    out = await svc.forget("nonexistent-id")
    assert out["status"] == "not_found"
