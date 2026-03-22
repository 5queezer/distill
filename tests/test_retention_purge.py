"""Retention purge — hard-delete soft-deleted memories past retention period.

Covers issue #68: auto-forget after retention period + vector cleanup.
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
        return "Distilled fact"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self._memories: dict[
            str, tuple[Memory, str | None]
        ] = {}  # id -> (mem, deleted_at)
        self._purged_ids: list[str] = []

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self._memories[memory.id] = (memory, None)
        return memory.id

    async def get(self, id: str) -> Memory | None:
        entry = self._memories.get(id)
        if entry and entry[1] is None:
            return entry[0]
        return None

    async def delete(self, id: str) -> None:
        if id in self._memories:
            mem, _ = self._memories[id]
            self._memories[id] = (mem, datetime.now(UTC).isoformat())

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

    async def get_lineage(self, memory_id: str) -> list[dict]:
        return []

    async def purge_expired(self, retention_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        to_purge = []
        for mid, (_mem, deleted_at) in self._memories.items():
            if deleted_at and datetime.fromisoformat(deleted_at) < cutoff:
                to_purge.append(mid)
        for mid in to_purge:
            del self._memories[mid]
            self._purged_ids.append(mid)
        return len(to_purge)


def _make_memory(id: str, age_days: int = 0) -> Memory:
    return Memory(
        id=id,
        content=f"Memory {id} content",
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


class TestRetentionPurge:
    async def test_purges_old_soft_deleted_memories(self) -> None:
        svc, storage = _service()
        mem = _make_memory("old-deleted")
        await storage.save(mem, [0.1] * 768)
        # Simulate soft-delete 100 days ago
        storage._memories["old-deleted"] = (
            mem,
            (datetime.now(UTC) - timedelta(days=100)).isoformat(),
        )

        count = await svc.purge_expired(retention_days=90)
        assert count == 1
        assert "old-deleted" in storage._purged_ids

    async def test_keeps_recently_soft_deleted(self) -> None:
        svc, storage = _service()
        mem = _make_memory("recent-deleted")
        await storage.save(mem, [0.1] * 768)
        # Soft-deleted 10 days ago — within retention
        storage._memories["recent-deleted"] = (
            mem,
            (datetime.now(UTC) - timedelta(days=10)).isoformat(),
        )

        count = await svc.purge_expired(retention_days=90)
        assert count == 0
        assert "recent-deleted" not in storage._purged_ids

    async def test_keeps_active_memories(self) -> None:
        svc, storage = _service()
        mem = _make_memory("active")
        await storage.save(mem, [0.1] * 768)

        count = await svc.purge_expired(retention_days=90)
        assert count == 0

    async def test_purges_multiple_expired(self) -> None:
        svc, storage = _service()
        for i in range(5):
            mem = _make_memory(f"expired-{i}")
            await storage.save(mem, [0.1] * 768)
            storage._memories[f"expired-{i}"] = (
                mem,
                (datetime.now(UTC) - timedelta(days=100 + i)).isoformat(),
            )

        count = await svc.purge_expired(retention_days=90)
        assert count == 5

    async def test_zero_retention_disables_purge(self) -> None:
        """retention_days=0 means purge everything that's soft-deleted."""
        svc, storage = _service()
        mem = _make_memory("just-deleted")
        await storage.save(mem, [0.1] * 768)
        storage._memories["just-deleted"] = (
            mem,
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )

        count = await svc.purge_expired(retention_days=0)
        assert count == 1
