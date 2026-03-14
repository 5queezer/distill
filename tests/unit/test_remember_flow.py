"""Tests for MemoryService — mocked distiller + embedder, real SqliteStore."""

from __future__ import annotations

import pytest

from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.services import MemoryService


def _vec(seed: float = 0.1) -> list[float]:
    import math

    return [math.sin(seed * 100.0 + i) for i in range(768)]


class FakeDistiller:
    """Returns input prefixed with 'Distilled: '."""

    async def distill(self, raw_text: str) -> str:
        if "no content" in raw_text.lower():
            return "NO_FACTUAL_CONTENT"
        return f"Distilled: {raw_text}"


class FakeEmbedder:
    """Returns a deterministic 768-dim vector derived from text bytes."""

    async def embed(self, text: str) -> list[float]:
        encoded = text.encode()
        n = len(encoded)
        return [encoded[i % n] / 255.0 for i in range(768)]


@pytest.fixture
def service(tmp_path: str) -> MemoryService:
    store = SqliteStore(str(tmp_path), rrf_k=60)
    store.initialize()
    return MemoryService(
        storage=store,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        distill_enabled=True,
    )


pytestmark = pytest.mark.asyncio


async def test_remember_happy_path(service: MemoryService) -> None:
    result = await service.remember(
        "Switched from Kong to Envoy", "decision", ["api-gateway"], ["infra"]
    )
    assert result["status"] == "saved"
    assert "id" in result
    assert "Distilled:" in result["distilled"]


async def test_remember_no_factual_content(service: MemoryService) -> None:
    result = await service.remember("I have no content to share", "context", ["repo"])
    assert result["status"] == "rejected"
    assert result["reason"] == "no factual content"


async def test_remember_duplicate_rejected(service: MemoryService) -> None:
    # Same text → same embedding → duplicate
    await service.remember("Same fact A", "decision", ["repo"])
    result = await service.remember("Same fact A", "decision", ["repo"])
    assert result["status"] == "duplicate"
    assert "existing_id" in result


async def test_search_returns_results(service: MemoryService) -> None:
    await service.remember("Envoy proxy deployed", "decision", ["api"])
    results = await service.search("Envoy")
    assert len(results) >= 1
    assert "Envoy" in results[0].memory.content


async def test_get_memory(service: MemoryService) -> None:
    result = await service.remember("Some fact", "pattern", ["repo"])
    mem = await service.get(result["id"])
    assert mem is not None
    assert mem.id == result["id"]


async def test_forget_memory(service: MemoryService) -> None:
    result = await service.remember("To be forgotten", "decision", ["repo"])
    mid = result["id"]
    forget_result = await service.forget(mid)
    assert forget_result["status"] == "forgotten"
    assert await service.get(mid) is None


async def test_forget_nonexistent(service: MemoryService) -> None:
    result = await service.forget("nonexistent")
    assert result["status"] == "not_found"


async def test_update_memory(service: MemoryService) -> None:
    r1 = await service.remember("Old fact", "decision", ["repo"])
    old_id = r1["id"]
    r2 = await service.update(old_id, "Updated fact")
    assert r2["status"] == "updated"
    assert r2["old_id"] == old_id
    assert r2["new_id"] != old_id
    # Old memory should be soft-deleted
    assert await service.get(old_id) is None
    # New memory should exist
    new_mem = await service.get(r2["new_id"])
    assert new_mem is not None
    assert "Updated" in new_mem.content


async def test_update_nonexistent(service: MemoryService) -> None:
    result = await service.update("nonexistent", "New content")
    assert result["status"] == "not_found"


async def test_list_recent(service: MemoryService) -> None:
    await service.remember("Fact alpha", "decision", ["repo-a"], ["tag-a"])
    await service.remember(
        "Fact bravo with more words", "pattern", ["repo-b"], ["tag-b"]
    )
    recent = await service.list_recent(limit=10)
    assert len(recent) == 2


async def test_distill_disabled(tmp_path: str) -> None:
    store = SqliteStore(str(tmp_path), rrf_k=60)
    store.initialize()
    svc = MemoryService(
        storage=store,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        distill_enabled=False,
    )
    result = await svc.remember("Raw text here", "decision", ["repo"])
    assert result["status"] == "saved"
    assert result["distilled"] == "Raw text here"
