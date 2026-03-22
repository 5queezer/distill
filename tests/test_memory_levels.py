"""Memory levels — derive level from type/repos, boost search scoring.

Covers issue #57: multi-level memory with search ranking impact.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from distill_mcp.domain.models import Memory, SearchResult, derive_level
from distill_mcp.domain.services import LEVEL_BOOST, MemoryService


class TestDeriveLevel:
    """Level derivation from type and repo scope."""

    def test_context_is_short_term(self) -> None:
        assert derive_level("context", ["repo"]) == "short-term"

    def test_decision_is_long_term(self) -> None:
        assert derive_level("decision", ["repo"]) == "long-term"

    def test_pattern_is_long_term(self) -> None:
        assert derive_level("pattern", ["repo"]) == "long-term"

    def test_failure_is_long_term(self) -> None:
        assert derive_level("failure", ["repo"]) == "long-term"

    def test_dependency_is_long_term(self) -> None:
        assert derive_level("dependency", ["repo"]) == "long-term"

    def test_multi_repo_is_shared(self) -> None:
        assert derive_level("decision", ["repo-a", "repo-b"]) == "shared"

    def test_multi_repo_context_is_shared(self) -> None:
        # Multi-repo takes precedence over type
        assert derive_level("context", ["repo-a", "repo-b"]) == "shared"

    def test_empty_repos_is_not_shared(self) -> None:
        assert derive_level("decision", []) == "long-term"

    def test_single_repo_is_not_shared(self) -> None:
        assert derive_level("decision", ["repo"]) == "long-term"

    def test_unknown_type_is_long_term(self) -> None:
        assert derive_level("unknown", ["repo"]) == "long-term"


pytestmark = pytest.mark.asyncio


# -- Level in search results --


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return "Distilled fact"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.5] * 768


class FakeStorage:
    def __init__(self) -> None:
        self._memories: dict[str, tuple[Memory, float]] = {}

    async def check_duplicate(self, vec, threshold=0.95):
        return None

    async def save(self, memory, vec, **kw):
        self._memories[memory.id] = (memory, 0.9)
        return memory.id

    async def get(self, id):
        pair = self._memories.get(id)
        return pair[0] if pair else None

    async def delete(self, id):
        self._memories.pop(id, None)

    async def search(self, query_text, query_vec, top_k, *, repo=None, agent_id=None):
        results = []
        for mem, score in self._memories.values():
            if repo is not None and repo not in mem.repos:
                continue
            if agent_id is not None and mem.agent_id != agent_id:
                continue
            results.append(SearchResult(memory=mem, score=score))
        return results[:top_k]

    async def list_recent(self, **kw):
        return [m for m, _ in self._memories.values()]

    async def record_access(self, id):
        pass

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


def _make_memory(type: str, repos: list[str], content: str = "fact") -> Memory:
    return Memory(
        id=f"{type}-{'-'.join(repos)}",
        content=content,
        type=type,
        repos=repos,
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )


class TestLevelInResults:
    """Level should appear in MemoryIndex from search and list_recent."""

    async def test_search_returns_level(self) -> None:
        storage = FakeStorage()
        svc = MemoryService(
            storage=storage,
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
        )
        mem = _make_memory(
            "decision", ["repo"], "We chose PostgreSQL for pgvector support"
        )
        vec = await FakeEmbedder().embed(mem.content)
        await storage.save(mem, vec)
        results = await svc.search("PostgreSQL", top_k=5)
        assert len(results) >= 1
        assert results[0].level == "long-term"

    async def test_list_recent_returns_level(self) -> None:
        storage = FakeStorage()
        svc = MemoryService(
            storage=storage,
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
        )
        mem = _make_memory(
            "context", ["repo"], "Temporary context about debugging the OOM issue"
        )
        vec = await FakeEmbedder().embed(mem.content)
        await storage.save(mem, vec)
        results = await svc.list_recent()
        assert len(results) >= 1
        assert results[0].level == "short-term"


class TestLevelBoost:
    """Search scoring should be multiplied by level coefficient."""

    def test_shared_boost_is_higher(self) -> None:
        assert LEVEL_BOOST["shared"] > LEVEL_BOOST["long-term"]

    def test_short_term_boost_is_lower(self) -> None:
        assert LEVEL_BOOST["short-term"] < LEVEL_BOOST["long-term"]

    async def test_shared_memory_scores_higher_than_single_repo(self) -> None:
        """A shared memory with same base score should rank higher."""
        storage = FakeStorage()
        svc = MemoryService(
            storage=storage,
            embedder=FakeEmbedder(),
            distiller=FakeDistiller(),
        )

        # Create a single-repo decision
        mem_single = _make_memory("decision", ["repo-a"], "Use PostgreSQL for storage")
        storage._memories[mem_single.id] = (mem_single, 0.9)

        # Create a shared decision (same base score)
        mem_shared = _make_memory(
            "decision", ["repo-a", "repo-b"], "Use PostgreSQL everywhere"
        )
        storage._memories[mem_shared.id] = (mem_shared, 0.9)

        results = await svc.search("PostgreSQL", top_k=10)
        scores = {r.id: r.score for r in results}

        # Shared memory should have a higher final score
        assert scores[mem_shared.id] > scores[mem_single.id]
