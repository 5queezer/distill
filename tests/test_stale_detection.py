"""Stale memory detection — identify memories past their useful life.

Covers issue #59: stale-memory identification based on age and access patterns.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
        return [0.5] * 768


class FakeStorage:
    def __init__(self) -> None:
        self._memories: list[Memory] = []

    async def check_duplicate(self, vec, threshold=0.95):
        return None

    async def save(self, memory, vec, **kw):
        self._memories.append(memory)
        return memory.id

    async def get(self, id):
        return next((m for m in self._memories if m.id == id), None)

    async def delete(self, id):
        pass

    async def search(self, *a, **kw):
        return []

    async def list_recent(self, *, repo=None, limit=20, **kw) -> list[Memory]:
        mems = self._memories
        if repo is not None:
            mems = [m for m in mems if repo in m.repos]
        return mems[:limit]

    async def record_access(self, id):
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


def _make_memory(
    id: str,
    type: str,
    age_days: int,
    access_count: int = 0,
    last_accessed_days_ago: int | None = None,
    repos: list[str] | None = None,
) -> Memory:
    created = datetime.now(UTC) - timedelta(days=age_days)
    last_accessed = None
    if last_accessed_days_ago is not None:
        last_accessed = datetime.now(UTC) - timedelta(days=last_accessed_days_ago)
    return Memory(
        id=id,
        content=f"Memory {id} content for testing stale detection",
        type=type,
        repos=repos or ["repo"],
        tags=[],
        author=None,
        created_at=created,
        access_count=access_count,
        last_accessed_at=last_accessed,
    )


def _service(memories: list[Memory]) -> MemoryService:
    storage = FakeStorage()
    storage._memories = memories
    return MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=False,
    )


class TestStaleDetection:
    """identify_stale should find old, unaccessed memories."""

    async def test_fresh_memory_not_stale(self) -> None:
        svc = _service([_make_memory("fresh", "decision", age_days=1)])
        stale = await svc.identify_stale()
        assert len(stale) == 0

    async def test_old_unaccessed_decision_is_stale(self) -> None:
        # decision scale=14, shape=1.5 → survival at 30 days ≈ 0.02
        svc = _service([_make_memory("old", "decision", age_days=30)])
        stale = await svc.identify_stale()
        assert len(stale) == 1
        assert stale[0]["id"] == "old"

    async def test_old_context_is_stale(self) -> None:
        # context scale=7, shape=2.0 → survival at 15 days ≈ 0.01
        svc = _service([_make_memory("ctx", "context", age_days=15)])
        stale = await svc.identify_stale()
        assert len(stale) == 1

    async def test_old_pattern_not_stale_yet(self) -> None:
        # pattern scale=90, shape=0.8 → survival at 30 days ≈ 0.72
        svc = _service([_make_memory("pat", "pattern", age_days=30)])
        stale = await svc.identify_stale()
        assert len(stale) == 0

    async def test_frequently_accessed_not_stale(self) -> None:
        # Old but accessed 5 times → not stale
        svc = _service(
            [_make_memory("popular", "decision", age_days=60, access_count=5)]
        )
        stale = await svc.identify_stale()
        assert len(stale) == 0

    async def test_stale_includes_metadata(self) -> None:
        svc = _service([_make_memory("meta", "decision", age_days=30)])
        stale = await svc.identify_stale()
        assert len(stale) == 1
        entry = stale[0]
        assert "id" in entry
        assert "type" in entry
        assert "snippet" in entry
        assert "age_days" in entry
        assert "access_count" in entry
        assert "survival_score" in entry
        assert entry["survival_score"] < 0.1

    async def test_stale_filtered_by_repo(self) -> None:
        svc = _service(
            [
                _make_memory("a", "decision", age_days=30, repos=["repo-a"]),
                _make_memory("b", "decision", age_days=30, repos=["repo-b"]),
            ]
        )
        stale = await svc.identify_stale(repo="repo-a")
        assert len(stale) == 1
        assert stale[0]["id"] == "a"

    async def test_stale_respects_limit(self) -> None:
        memories = [
            _make_memory(f"old-{i}", "decision", age_days=30) for i in range(10)
        ]
        svc = _service(memories)
        stale = await svc.identify_stale(limit=3)
        assert len(stale) == 3

    async def test_dependency_very_durable(self) -> None:
        # dependency scale=180, shape=0.7 → survival at 90 days ≈ 0.60
        svc = _service([_make_memory("dep", "dependency", age_days=90)])
        stale = await svc.identify_stale()
        assert len(stale) == 0
