"""Lineage tracking — queryable supersedes chain.

Covers issue #69: get_lineage(id) returns the full supersedes chain
in both directions (predecessors and successors).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return f"Distilled: {raw_text}"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}
        self._supersedes: dict[str, str | None] = {}  # id -> supersedes

    async def save(
        self, memory: Memory, vec: list[float], *, supersedes: str | None = None
    ) -> str:
        self._memories[memory.id] = memory
        self._supersedes[memory.id] = supersedes
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        pass

    async def search(self, *a: Any, **kw: Any) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec: Any, **kw: Any) -> list:
        return []

    async def check_duplicate(self, vec: Any, **kw: Any) -> str | None:
        return None

    async def purge_expired(self, retention_days: int) -> int:
        return 0

    async def get_lineage(self, memory_id: str) -> list[dict]:
        """Fake implementation that mirrors the real logic."""
        seen: set[str] = {memory_id}

        def _entry(mem: Memory, direction: str) -> dict:
            content = mem.content
            snippet = content[:80] + ("..." if len(content) > 80 else "")
            return {
                "id": mem.id,
                "snippet": snippet,
                "created_at": mem.created_at.isoformat(),
                "deleted_at": None,
                "direction": direction,
            }

        # Walk backwards
        predecessors: list[dict] = []
        current = memory_id
        while True:
            sup = self._supersedes.get(current)
            if not sup or sup in seen:
                break
            seen.add(sup)
            mem = self._memories.get(sup)
            if not mem:
                break
            predecessors.append(_entry(mem, "predecessor"))
            current = sup
        predecessors.reverse()

        # Self
        chain = predecessors
        target = self._memories.get(memory_id)
        if target:
            chain.append(_entry(target, "self"))

        # Walk forward
        current = memory_id
        while True:
            successor = None
            for mid, sup in self._supersedes.items():
                if sup == current:
                    successor = mid
                    break
            if not successor or successor in seen:
                break
            seen.add(successor)
            mem = self._memories[successor]
            chain.append(_entry(mem, "successor"))
            current = successor

        return chain


def _make_memory(id: str, content: str, age_days: int = 0) -> Memory:
    return Memory(
        id=id,
        content=content,
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


def _service() -> tuple[MemoryService, FakeStorage]:
    storage = FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
    )
    return svc, storage


class TestGetLineage:
    async def test_single_memory_returns_self(self) -> None:
        svc, storage = _service()
        mem = _make_memory("m1", "PostgreSQL chosen for pgvector")
        await storage.save(mem, [0.1] * 768)

        lineage = await svc.get_lineage("m1")
        assert len(lineage) == 1
        assert lineage[0]["id"] == "m1"
        assert lineage[0]["direction"] == "self"

    async def test_two_step_chain(self) -> None:
        """m1 → m2 (m2 supersedes m1)."""
        svc, storage = _service()
        m1 = _make_memory("m1", "Use Redis for caching", age_days=30)
        m2 = _make_memory("m2", "Use Memcached for caching", age_days=0)
        await storage.save(m1, [0.1] * 768)
        await storage.save(m2, [0.1] * 768, supersedes="m1")

        # Query from m2 (current) — should see m1 as predecessor
        lineage = await svc.get_lineage("m2")
        assert len(lineage) == 2
        assert lineage[0]["direction"] == "predecessor"
        assert lineage[0]["id"] == "m1"
        assert lineage[1]["direction"] == "self"
        assert lineage[1]["id"] == "m2"

    async def test_query_from_predecessor(self) -> None:
        """Query from m1 — should see m2 as successor."""
        svc, storage = _service()
        m1 = _make_memory("m1", "Use Redis", age_days=30)
        m2 = _make_memory("m2", "Use Memcached", age_days=0)
        await storage.save(m1, [0.1] * 768)
        await storage.save(m2, [0.1] * 768, supersedes="m1")

        lineage = await svc.get_lineage("m1")
        assert len(lineage) == 2
        assert lineage[0]["direction"] == "self"
        assert lineage[0]["id"] == "m1"
        assert lineage[1]["direction"] == "successor"
        assert lineage[1]["id"] == "m2"

    async def test_three_step_chain(self) -> None:
        """m1 → m2 → m3."""
        svc, storage = _service()
        m1 = _make_memory("m1", "v1 of decision", age_days=60)
        m2 = _make_memory("m2", "v2 of decision", age_days=30)
        m3 = _make_memory("m3", "v3 of decision", age_days=0)
        await storage.save(m1, [0.1] * 768)
        await storage.save(m2, [0.1] * 768, supersedes="m1")
        await storage.save(m3, [0.1] * 768, supersedes="m2")

        # Query from middle
        lineage = await svc.get_lineage("m2")
        assert len(lineage) == 3
        assert lineage[0]["id"] == "m1"
        assert lineage[0]["direction"] == "predecessor"
        assert lineage[1]["id"] == "m2"
        assert lineage[1]["direction"] == "self"
        assert lineage[2]["id"] == "m3"
        assert lineage[2]["direction"] == "successor"

    async def test_nonexistent_memory_returns_empty(self) -> None:
        svc, _storage = _service()
        lineage = await svc.get_lineage("nonexistent")
        assert lineage == []

    async def test_lineage_includes_snippet(self) -> None:
        svc, storage = _service()
        content = "PostgreSQL chosen for pgvector support in the main application"
        mem = _make_memory("m1", content)
        await storage.save(mem, [0.1] * 768)

        lineage = await svc.get_lineage("m1")
        assert lineage[0]["snippet"] == content[:80]
