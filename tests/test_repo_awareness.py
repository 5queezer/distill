"""Repo awareness — auto-detection and search filtering by repo."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

# -- search with repo filter --


def _mem(id: str, repos: list[str]) -> Memory:
    return Memory(
        id=id,
        content=f"fact from {id}",
        type="decision",
        repos=repos,
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )


class FakeStorage:
    """Returns pre-built search results, respects repo filter."""

    def __init__(self, memories: list[Memory]) -> None:
        self._mems = {m.id: m for m in memories}

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
    ) -> list[SearchResult]:
        out = []
        for m in self._mems.values():
            if repo is None or repo in m.repos:
                out.append(SearchResult(memory=m, score=1.0))
            if len(out) >= top_k:
                break
        return out

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._mems.get(id)

    async def delete(self, id: str) -> None:
        pass

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return raw_text


@pytest.mark.asyncio
async def test_search_without_repo_returns_all() -> None:
    mems = [_mem("a", ["auth-service"]), _mem("b", ["payment-api"])]
    svc = MemoryService(FakeStorage(mems), FakeEmbedder(), FakeDistiller())
    results = await svc.search("fact", top_k=10)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_with_repo_filters() -> None:
    mems = [_mem("a", ["auth-service"]), _mem("b", ["payment-api"])]
    svc = MemoryService(FakeStorage(mems), FakeEmbedder(), FakeDistiller())
    results = await svc.search("fact", top_k=10, repo="auth-service")
    assert len(results) == 1
    assert results[0].id == "a"


@pytest.mark.asyncio
async def test_search_with_nonexistent_repo_returns_empty() -> None:
    mems = [_mem("a", ["auth-service"])]
    svc = MemoryService(FakeStorage(mems), FakeEmbedder(), FakeDistiller())
    results = await svc.search("fact", top_k=10, repo="no-such-repo")
    assert results == []
