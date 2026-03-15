"""Preview flow — verify the two-step remember/confirm flow."""

from __future__ import annotations

import time
from typing import Any

import pytest

from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes (same pattern as test_remember_flow.py) --


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output

    async def distill(self, raw_text: str) -> str:
        self._last_input = raw_text
        return self._output


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self, *, dup_id: str | None = None) -> None:
        self._dup_id = dup_id
        self.saved: list[Any] = []

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return self._dup_id

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        return memory.id

    async def get(self, id: str) -> None:
        return None

    async def delete(self, id: str) -> None:
        pass

    async def search(self, *a: Any, **kw: Any) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


def _service(
    *,
    distill_preview: bool = True,
    distill_enabled: bool = True,
    distiller_output: str = "Distilled fact",
    dup_id: str | None = None,
) -> tuple[MemoryService, FakeStorage, FakeDistiller]:
    storage = FakeStorage(dup_id=dup_id)
    distiller = FakeDistiller(distiller_output)
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=distiller,
        distill_enabled=distill_enabled,
        distill_preview=distill_preview,
    )
    return svc, storage, distiller


# -- Tests --


async def test_remember_returns_pending_when_preview_enabled() -> None:
    svc, storage, _ = _service(distill_preview=True)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "pending"
    assert "pending_id" in result
    assert "distilled" in result
    assert "confirm_memory" in result["message"]
    assert len(storage.saved) == 0  # nothing stored yet


async def test_confirm_stores_memory() -> None:
    svc, storage, _ = _service(distill_preview=True)
    pending = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert pending["status"] == "pending"

    result = await svc.confirm_memory(pending["pending_id"])
    assert result["status"] == "saved"
    assert "id" in result
    assert len(storage.saved) == 1


async def test_confirm_with_override() -> None:
    svc, storage, distiller = _service(distill_preview=True)
    pending = await svc.remember(_VALID_INPUT, "decision", ["repo"])

    override_text = "We chose SQLite for simplicity in single-node setups"
    distiller._output = "Distilled override"
    result = await svc.confirm_memory(pending["pending_id"], override=override_text)

    assert result["status"] == "saved"
    assert result["distilled"] == "Distilled override"
    assert storage.saved[0].content == "Distilled override"


async def test_confirm_expired_returns_expired() -> None:
    svc, _, _ = _service(distill_preview=True)
    pending = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pid = pending["pending_id"]

    # Manually expire
    svc._pending[pid]["expires_at"] = time.time() - 1

    result = await svc.confirm_memory(pid)
    assert result["status"] == "expired"
    assert result["pending_id"] == pid
    assert pid not in svc._pending


async def test_confirm_not_found() -> None:
    svc, _, _ = _service(distill_preview=True)
    result = await svc.confirm_memory("nonexistent-id-xyz")
    assert result["status"] == "not_found"


async def test_remember_stores_directly_when_preview_disabled() -> None:
    svc, storage, _ = _service(distill_preview=False)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "saved"
    assert "id" in result
    assert len(storage.saved) == 1


async def test_cleanup_removes_expired() -> None:
    svc, _, _ = _service(distill_preview=True)
    await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert len(svc._pending) == 1

    # Expire it
    for entry in svc._pending.values():
        entry["expires_at"] = time.time() - 1

    removed = svc.cleanup_expired_pending()
    assert removed == 1
    assert len(svc._pending) == 0


async def test_duplicate_bypasses_pending() -> None:
    """Duplicate check happens before pending — should return duplicate, not pending."""
    svc, _, _ = _service(distill_preview=True, dup_id="existing-123")
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "duplicate"
    assert result["existing_id"] == "existing-123"
    assert len(svc._pending) == 0
