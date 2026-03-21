"""Reranker — JinaReranker adapter and MemoryService integration.

Tests the cross-encoder reranking step: Jina API adapter, error handling,
and correct placement in the search pipeline (after RRF, before recency boost).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from distill_mcp.adapters.reranker.jina_rerank import JinaReranker
from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes for MemoryService --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return f"Distilled: {raw_text}"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self, search_results: list[SearchResult] | None = None) -> None:
        self._search_results = search_results or []

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Any, vec: list[float], **kw: Any) -> str:
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
        agent_id: str | None = None,
    ) -> list[SearchResult]:
        return list(self._search_results)

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


class FakeReranker:
    """Fake RerankerPort that reverses document order and assigns descending scores."""

    def __init__(self) -> None:
        self.called = False
        self.last_query: str | None = None
        self.last_docs: list[str] | None = None
        self.last_top_n: int | None = None

    async def rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        self.called = True
        self.last_query = query
        self.last_docs = documents
        self.last_top_n = top_n
        # Reverse the order: last doc gets highest score
        n = len(documents)
        return [(n - 1 - i, 0.9 - i * 0.1) for i in range(min(top_n, n))]


def _memory(content: str = "Some fact", *, id: str = "test-id") -> Memory:
    return Memory(
        id=id,
        content=content,
        type="decision",
        repos=["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )


# -- JinaReranker adapter tests --


class TestJinaRerankerInit:
    def test_default_model(self) -> None:
        r = JinaReranker(api_key="test-key")
        assert r._model == "jina-reranker-v2-base-multilingual"

    def test_custom_model(self) -> None:
        r = JinaReranker(api_key="test-key", model="custom-model")
        assert r._model == "custom-model"


class TestJinaRerankerRerank:
    async def test_successful_rerank(self) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.72},
                ]
            },
            request=httpx.Request("POST", "https://api.jina.ai/v1/rerank"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            reranker = JinaReranker(api_key="test-key")
            result = await reranker.rerank("query", ["doc A", "doc B"], top_n=2)

        assert result == [(1, 0.95), (0, 0.72)]
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["query"] == "query"
        assert call_kwargs.kwargs["json"]["documents"] == ["doc A", "doc B"]

    async def test_http_error_raises_runtime_error(self) -> None:
        mock_response = httpx.Response(
            401,
            json={"error": "unauthorized"},
            request=httpx.Request("POST", "https://api.jina.ai/v1/rerank"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            reranker = JinaReranker(api_key="bad-key")
            with pytest.raises(RuntimeError, match="HTTP 401"):
                await reranker.rerank("query", ["doc"], top_n=1)

    async def test_connect_error_raises_runtime_error(self) -> None:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")
            reranker = JinaReranker(api_key="key")
            with pytest.raises(RuntimeError, match="not reachable"):
                await reranker.rerank("query", ["doc"], top_n=1)

    async def test_timeout_raises_runtime_error(self) -> None:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ReadTimeout("timed out")
            reranker = JinaReranker(api_key="key")
            with pytest.raises(RuntimeError, match="request failed"):
                await reranker.rerank("query", ["doc"], top_n=1)

    async def test_malformed_response_raises_runtime_error(self) -> None:
        mock_response = httpx.Response(
            200,
            json={"unexpected": "format"},
            request=httpx.Request("POST", "https://api.jina.ai/v1/rerank"),
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            reranker = JinaReranker(api_key="key")
            with pytest.raises(RuntimeError, match="response format"):
                await reranker.rerank("query", ["doc"], top_n=1)


# -- MemoryService integration tests --


class TestSearchWithReranker:
    async def test_reranker_called_and_results_reordered(self) -> None:
        """When reranker is set, results should be reordered by reranker scores."""
        results_from_db = [
            SearchResult(memory=_memory("first", id="a"), score=0.8),
            SearchResult(memory=_memory("second", id="b"), score=0.7),
            SearchResult(memory=_memory("third", id="c"), score=0.6),
        ]
        fake_reranker = FakeReranker()
        service = MemoryService(
            storage=FakeStorage(results_from_db),
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
            preview_enabled=False,
            reranker=fake_reranker,
        )
        results = await service.search("query")

        assert fake_reranker.called
        assert fake_reranker.last_query == "query"
        assert fake_reranker.last_docs == ["first", "second", "third"]
        # FakeReranker reverses: "third" (idx 2) → 0.9, "second" (idx 1) → 0.8, "first" (idx 0) → 0.7
        assert len(results) == 3
        assert results[0].id == "c"  # "third" was reranked highest
        assert results[1].id == "b"
        assert results[2].id == "a"

    async def test_reranker_not_called_when_none(self) -> None:
        """When reranker is None, search should work as before."""
        results_from_db = [
            SearchResult(memory=_memory("fact A", id="a"), score=0.8),
            SearchResult(memory=_memory("fact B", id="b"), score=0.6),
        ]
        service = MemoryService(
            storage=FakeStorage(results_from_db),
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
            preview_enabled=False,
            reranker=None,
        )
        results = await service.search("query")

        assert len(results) == 2
        assert results[0].id == "a"
        assert results[1].id == "b"

    async def test_reranker_not_called_on_empty_results(self) -> None:
        """When storage returns no results, reranker should not be called."""
        fake_reranker = FakeReranker()
        service = MemoryService(
            storage=FakeStorage([]),
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
            preview_enabled=False,
            reranker=fake_reranker,
        )
        results = await service.search("query")

        assert not fake_reranker.called
        assert results == []

    async def test_reranker_scores_feed_into_recency_boost(self) -> None:
        """Reranker scores should be the base for recency/access boost, not RRF scores."""
        results_from_db = [
            SearchResult(memory=_memory("only result", id="x"), score=0.3),
        ]
        fake_reranker = FakeReranker()  # will set score to 0.9
        service = MemoryService(
            storage=FakeStorage(results_from_db),
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
            preview_enabled=False,
            reranker=fake_reranker,
        )
        results = await service.search("query")

        # Reranker sets score to 0.9, then recency+access boost is applied on top
        assert len(results) == 1
        assert results[0].score > 0.85
