"""Agent ID — verify multi-agent memory support."""

from __future__ import annotations

import asyncio
from typing import Any
from datetime import UTC, datetime

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
    def __init__(self) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}

    async def check_duplicate(self, vec: list[float], threshold: float = 0.95) -> str | None:
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


_VALID_INPUT = "We chose asyncpg for async PostgreSQL support"


def _service(distill_preview: bool = False) -> tuple[MemoryService, FakeStorage, FakeDistiller]:
    storage = FakeStorage()
    distiller = FakeDistiller()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=distiller,
        distill_enabled=True,
        distill_preview=distill_preview,
    )
    return svc, storage, distiller


# -- Tests --


async def test_remember_stores_agent_id() -> None:
    svc, storage, _ = _service()
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"], agent_id="zeroclaw")
    assert result["status"] == "saved"
    assert storage.saved[0].agent_id == "zeroclaw"


async def test_agent_id_none_works_as_before() -> None:
    svc, storage, _ = _service()
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "saved"
    assert storage.saved[0].agent_id is None


async def test_distillation_includes_agent_prefix() -> None:
    svc, _, distiller = _service()
    await svc.remember(_VALID_INPUT, "decision", ["repo"], agent_id="zeroclaw")
    assert distiller.last_input.startswith("[Agent: zeroclaw]")
    assert _VALID_INPUT in distiller.last_input


async def test_distillation_no_prefix_when_no_agent_id() -> None:
    svc, _, distiller = _service()
    await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert not distiller.last_input.startswith("[Agent:")


async def test_search_filters_by_agent_id() -> None:
    svc, storage, _ = _service()
    await svc.remember(_VALID_INPUT, "decision", ["repo"], agent_id="agent-a")
    await svc.remember("FastAPI chosen for REST layer", "decision", ["repo"], agent_id="agent-b")

    results = await svc.search("postgres", agent_id="agent-a")
    assert all(r.memory.agent_id == "agent-a" for r in results)


async def test_search_without_filter_returns_all() -> None:
    svc, storage, _ = _service()
    await svc.remember(_VALID_INPUT, "decision", ["repo"], agent_id="agent-a")
    await svc.remember("FastAPI chosen for REST layer", "decision", ["repo"], agent_id="agent-b")

    results = await svc.search("chosen")
    agent_ids = {r.memory.agent_id for r in results}
    assert "agent-a" in agent_ids
    assert "agent-b" in agent_ids


async def test_list_recent_filters_by_agent_id() -> None:
    svc, _, _ = _service()
    await svc.remember(_VALID_INPUT, "decision", ["repo"], agent_id="agent-a")
    await svc.remember("FastAPI chosen for REST layer", "decision", ["repo"], agent_id="agent-b")

    results = await svc.list_recent(agent_id="agent-b")
    assert all(m.agent_id == "agent-b" for m in results)
    assert len(results) == 1


async def test_concurrent_writes_from_two_agents() -> None:
    """Two agents writing simultaneously — both memories stored correctly."""
    svc, storage, _ = _service()
    results = await asyncio.gather(
        svc.remember("asyncpg chosen for async PostgreSQL support", "decision", ["repo"], agent_id="agent-a"),
        svc.remember("FastAPI chosen for REST layer in the service", "decision", ["repo"], agent_id="agent-b"),
    )
    assert all(r["status"] == "saved" for r in results)
    assert len(storage.saved) == 2
    agent_ids = {m.agent_id for m in storage.saved}
    assert agent_ids == {"agent-a", "agent-b"}
