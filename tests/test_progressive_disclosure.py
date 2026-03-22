"""Progressive disclosure — search returns compact index, get_memories returns full content."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, MemoryIndex, SearchResult
from distill_mcp.domain.services import MemoryService, _to_index

# -- Fakes --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return f"Distilled: {raw_text}"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(
        self,
        search_results: list[SearchResult] | None = None,
        memories: dict[str, Memory] | None = None,
        recent: list[Memory] | None = None,
    ) -> None:
        self._search_results = search_results or []
        self._memories = memories or {}
        self._recent = recent or []

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        pass

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
        **kw,
    ) -> list[SearchResult]:
        return list(self._search_results)

    async def list_recent(self, **kw: Any) -> list[Memory]:
        return list(self._recent)

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


def _memory(
    id: str = "test-id",
    content: str = "Redis was chosen as the caching layer for session data due to sub-ms latency requirements.",
) -> Memory:
    return Memory(
        id=id,
        content=content,
        type="decision",
        repos=["myrepo"],
        tags=["redis", "caching"],
        author=None,
        created_at=datetime.now(UTC),
    )


def _service(
    search_results: list[SearchResult] | None = None,
    memories: dict[str, Memory] | None = None,
    recent: list[Memory] | None = None,
) -> MemoryService:
    return MemoryService(
        storage=FakeStorage(search_results, memories, recent),
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
    )


# -- Layer 1: search returns compact index --


@pytest.mark.asyncio
class TestSearchReturnsIndex:
    async def test_search_returns_memory_index(self) -> None:
        mem = _memory()
        sr = SearchResult(memory=mem, score=0.8)
        results = await _service([sr]).search("Redis")
        assert len(results) == 1
        assert isinstance(results[0], MemoryIndex)

    async def test_index_has_snippet_not_content(self) -> None:
        mem = _memory()
        sr = SearchResult(memory=mem, score=0.8)
        results = await _service([sr]).search("Redis")
        assert hasattr(results[0], "snippet")
        assert not hasattr(results[0], "content")

    async def test_snippet_truncated_at_80_chars(self) -> None:
        long_content = "x" * 200
        mem = _memory(content=long_content)
        sr = SearchResult(memory=mem, score=0.8)
        results = await _service([sr]).search("query")
        assert len(results[0].snippet) == 83  # 80 + "..."
        assert results[0].snippet.endswith("...")

    async def test_short_content_no_ellipsis(self) -> None:
        mem = _memory(content="Short fact.")
        sr = SearchResult(memory=mem, score=0.8)
        results = await _service([sr]).search("query")
        assert results[0].snippet == "Short fact."
        assert not results[0].snippet.endswith("...")

    async def test_est_tokens_calculation(self) -> None:
        mem = _memory(content="x" * 400)
        sr = SearchResult(memory=mem, score=0.8)
        results = await _service([sr]).search("query")
        assert results[0].est_tokens == 100  # 400 // 4


# -- Layer 2: get_memories returns full content --


@pytest.mark.asyncio
class TestGetMemories:
    async def test_returns_full_content(self) -> None:
        mem = _memory(id="abc123")
        svc = _service(memories={"abc123": mem})
        details = await svc.get_batch(["abc123"])
        assert len(details) == 1
        assert details[0].content == mem.content
        assert details[0].est_tokens == len(mem.content) // 4

    async def test_empty_ids(self) -> None:
        details = await _service().get_batch([])
        assert details == []

    async def test_invalid_id_skipped(self) -> None:
        details = await _service().get_batch(["nonexistent"])
        assert details == []

    async def test_mixed_valid_invalid(self) -> None:
        mem = _memory(id="valid1")
        svc = _service(memories={"valid1": mem})
        details = await svc.get_batch(["valid1", "bogus", "also-bogus"])
        assert len(details) == 1
        assert details[0].id == "valid1"

    async def test_empty_string_id_skipped(self) -> None:
        details = await _service().get_batch([""])
        assert details == []

    async def test_batch_preserves_order(self) -> None:
        m1 = _memory(id="id1", content="First")
        m2 = _memory(id="id2", content="Second")
        svc = _service(memories={"id1": m1, "id2": m2})
        details = await svc.get_batch(["id1", "id2"])
        assert [d.id for d in details] == ["id1", "id2"]


# -- list_recent returns index --


@pytest.mark.asyncio
class TestListRecentReturnsIndex:
    async def test_returns_memory_index(self) -> None:
        mem = _memory()
        results = await _service(recent=[mem]).list_recent()
        assert len(results) == 1
        assert isinstance(results[0], MemoryIndex)
        assert hasattr(results[0], "snippet")
        assert not hasattr(results[0], "content")


# -- _to_index helper --


class TestToIndex:
    def test_exactly_80_chars_no_ellipsis(self) -> None:
        mem = _memory(content="x" * 80)
        idx = _to_index(mem, score=0.5)
        assert idx.snippet == "x" * 80
        assert not idx.snippet.endswith("...")

    def test_81_chars_gets_ellipsis(self) -> None:
        mem = _memory(content="x" * 81)
        idx = _to_index(mem, score=0.5)
        assert idx.snippet == "x" * 80 + "..."
        assert len(idx.snippet) == 83
