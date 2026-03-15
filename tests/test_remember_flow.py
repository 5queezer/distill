"""Remember flow — verify the chain: distill → embed → dedup → save.

All ports are mocked. We only test that the service calls them in the right
order and stops early when it should.
"""

from __future__ import annotations

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


def _service(
    distiller_output: str = "Distilled fact", dup_id: str | None = None
) -> MemoryService:
    return MemoryService(
        storage=FakeStorage(dup_id=dup_id),
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(distiller_output),
        preview_enabled=False,
    )


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


async def test_happy_path_calls_distill_embed_dedup_save() -> None:
    result = await _service().remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "saved"
    assert call_log == ["distill", "embed", "dedup", "save"]


async def test_no_factual_content_stops_after_distill() -> None:
    result = await _service("NO_FACTUAL_CONTENT").remember(
        _VALID_INPUT, "context", ["r"]
    )
    assert result["status"] == "rejected"
    assert call_log == ["distill"]


async def test_duplicate_stops_before_save() -> None:
    result = await _service(dup_id="existing-123").remember(
        _VALID_INPUT, "decision", ["r"]
    )
    assert result["status"] == "duplicate"
    assert call_log == ["distill", "embed", "dedup"]
    assert "save" not in call_log
