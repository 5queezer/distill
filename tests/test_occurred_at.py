"""occurred_at — timeline timestamp distinct from created_at."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MemoryService


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return raw_text


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Memory] = []

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return next((m for m in self.saved if m.id == id), None)

    async def delete(self, id: str) -> None:
        pass

    async def search(
        self, query_text: str, query_vec: list[float], top_k: int, **kw: Any
    ) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def svc(storage: FakeStorage) -> MemoryService:
    return MemoryService(
        storage, FakeEmbedder(), FakeDistiller(), distill_enabled=False
    )


async def test_remember_with_occurred_at(
    svc: MemoryService, storage: FakeStorage
) -> None:
    past = datetime(2025, 6, 15, tzinfo=UTC)
    result = await svc.remember(
        "migrated to asyncpg", "decision", ["distill"], occurred_at=past
    )
    assert result["status"] == "saved"
    mem = storage.saved[0]
    assert mem.occurred_at == past
    assert mem.created_at != past  # created_at is "now"


async def test_remember_without_occurred_at_defaults_to_created(
    svc: MemoryService, storage: FakeStorage
) -> None:
    result = await svc.remember("some fact", "pattern", ["repo"])
    assert result["status"] == "saved"
    mem = storage.saved[0]
    assert mem.occurred_at == mem.created_at


async def test_update_preserves_occurred_at(
    svc: MemoryService, storage: FakeStorage
) -> None:
    past = datetime(2025, 1, 10, tzinfo=UTC)
    await svc.remember("old fact", "decision", ["r"], occurred_at=past)
    old_id = storage.saved[0].id

    result = await svc.update(old_id, "corrected fact")
    assert result["status"] == "updated"
    new_mem = storage.saved[-1]
    assert new_mem.occurred_at == past


async def test_memory_occurred_at_defaults_to_none() -> None:
    mem = Memory(
        id="x",
        content="test",
        type="pattern",
        repos=[],
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )
    assert mem.occurred_at is None
