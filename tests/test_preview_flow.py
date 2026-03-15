"""Preview flow — verify the two-step remember → confirm cycle.

All ports are mocked. We test that preview mode defers storage,
confirm completes it, and edge cases (expiry, unknown ID, override,
private file cleanup) behave correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio

# -- Shared call log used by all fakes --

call_log: list[str] = []


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output

    async def distill(self, raw_text: str) -> str:
        call_log.append("distill")
        return self._output


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        call_log.append("embed")
        return [0.1] * 768


class FakeStorage:
    def __init__(self, *, dup_id: str | None = None) -> None:
        self._dup_id = dup_id

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        call_log.append("dedup")
        return self._dup_id

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        call_log.append("save")
        return memory.id

    async def get(self, id: str) -> None:
        return None

    async def delete(self, id: str) -> None:
        pass

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
    ) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_log() -> None:
    call_log.clear()


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


def _service(
    *,
    preview_enabled: bool = True,
    preview_ttl_seconds: int = 300,
    private_dir: Any = None,
    dup_id: str | None = None,
) -> MemoryService:
    return MemoryService(
        storage=FakeStorage(dup_id=dup_id),
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=preview_enabled,
        preview_ttl_seconds=preview_ttl_seconds,
        private_dir=private_dir,
    )


async def test_preview_returns_pending_id_not_saved() -> None:
    svc = _service()
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])

    assert result["status"] == "preview"
    assert "pending_id" in result
    assert "distilled" in result
    assert "expires_in_seconds" in result
    assert "save" not in call_log
    assert "dedup" not in call_log
    assert call_log == ["distill", "embed"]


async def test_confirm_stores_distilled() -> None:
    svc = _service()
    preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pending_id = preview["pending_id"]

    call_log.clear()
    result = await svc.confirm_memory(pending_id)

    assert result["status"] == "saved"
    assert "id" in result
    assert "distilled" in result
    assert "dedup" in call_log
    assert "save" in call_log


async def test_confirm_with_override_re_embeds() -> None:
    svc = _service()
    preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pending_id = preview["pending_id"]

    # call_log so far: ["distill", "embed"]  (one embed from remember)
    result = await svc.confirm_memory(pending_id, override="custom text")

    assert result["status"] == "saved"
    assert result["distilled"] == "custom text"
    # embed called twice total: once in remember, once for override
    assert call_log.count("embed") == 2


async def test_confirm_unknown_id_returns_not_found() -> None:
    svc = _service()
    result = await svc.confirm_memory("nonexistent")

    assert result["status"] == "not_found"


async def test_confirm_expired_returns_expired() -> None:
    svc = _service(preview_ttl_seconds=0)
    preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pending_id = preview["pending_id"]

    # Directly manipulate expires_at to avoid sleep
    svc._pending[pending_id].expires_at = datetime(2000, 1, 1, tzinfo=UTC)

    result = await svc.confirm_memory(pending_id)
    assert result["status"] == "expired"
    # Entry should be cleaned up
    assert pending_id not in svc._pending


async def test_preview_disabled_stores_immediately() -> None:
    svc = _service(preview_enabled=False)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])

    assert result["status"] == "saved"
    assert call_log == ["distill", "embed", "dedup", "save"]


async def test_private_file_written_and_cleaned_up(tmp_path: Any) -> None:
    svc = _service(private_dir=tmp_path)
    preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pending_id = preview["pending_id"]

    # Verify private file was written
    private_file = tmp_path / f"{pending_id}.txt"
    assert private_file.exists()
    assert private_file.read_text(encoding="utf-8") == _VALID_INPUT

    # Confirm should clean up the file
    result = await svc.confirm_memory(pending_id)
    assert result["status"] == "saved"
    assert not private_file.exists()


async def test_prune_expired_cleans_dict() -> None:
    from distill_mcp.domain.services import _PendingEntry

    svc = _service()

    # Manually insert an expired entry
    expired_id = "expired-entry-123"
    svc._pending[expired_id] = _PendingEntry(
        id=expired_id,
        raw_text="old text",
        distilled="old distilled",
        type="decision",
        repos=["repo"],
        tags=[],
        vec=[0.1] * 768,
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),
        private_file=None,
    )
    assert expired_id in svc._pending

    # Calling remember triggers _prune_expired
    await svc.remember(_VALID_INPUT, "decision", ["repo"])

    # The manually inserted expired entry should be gone
    assert expired_id not in svc._pending


async def test_secret_in_input_is_redacted_and_stored() -> None:
    """Pre-scan redacts secrets; distillation and storage continue."""
    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner

    svc = MemoryService(
        storage=FakeStorage(),
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=False,
        scanner=SecretScanner(),
    )
    text = "Use token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx for CI access"
    result = await svc.remember(text, "decision", ["repo"])
    assert result["status"] == "saved"
    assert result["redacted_count"] >= 1


async def test_secret_in_distilled_output_is_blocked() -> None:
    """Post-scan hard-blocks if LLM leaks a secret in distilled output."""
    from distill_mcp.adapters.scanner.secret_scanner import SecretScanner

    class LeakyDistiller:
        async def distill(self, raw_text: str) -> str:
            return "The CI token is ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx for authentication"

    svc = MemoryService(
        storage=FakeStorage(),
        embedder=FakeEmbedder(),
        distiller=LeakyDistiller(),
        preview_enabled=False,
        scanner=SecretScanner(),
    )
    result = await svc.remember(
        "Some legit input about our CI setup pipeline", "decision", ["repo"]
    )
    assert result["status"] == "blocked"


async def test_concurrent_confirms_only_one_saves() -> None:
    """Optimistic-pop contract: concurrent confirms yield exactly one saved and one not_found."""
    import asyncio

    svc = _service()
    preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    pending_id = preview["pending_id"]

    call_log.clear()
    results = await asyncio.gather(
        svc.confirm_memory(pending_id),
        svc.confirm_memory(pending_id),
    )

    statuses = {r["status"] for r in results}
    # One must be "saved", the other "not_found" (entry was already popped)
    assert "saved" in statuses
    assert statuses == {"saved", "not_found"}
    # Only one save to storage
    assert call_log.count("save") == 1
