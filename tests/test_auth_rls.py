# tests/test_auth_rls.py
"""Auth enforcement — write blocking and author tagging."""

from __future__ import annotations

from typing import Any

import pytest

from distill_mcp.adapters.storage.postgres_store import (
    _rls_init_sql,
    _set_session_identity_sql,
)
from distill_mcp.domain.identity import ANONYMOUS, Identity
from distill_mcp.domain.models import Memory, SearchResult
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio

_VALID_INPUT = "We chose asyncpg for async PostgreSQL support"


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return "Distilled fact"


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        self._memories[memory.id] = memory
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        self._memories.pop(id, None)

    async def search(
        self, query_text: str, query_vec: list[float], top_k: int, **kw: Any
    ) -> list[SearchResult]:
        return [
            SearchResult(memory=m, score=0.9)
            for m in list(self._memories.values())[:top_k]
        ]

    async def list_recent(self, **kw: Any) -> list[Memory]:
        return list(self._memories.values())

    async def record_access(self, id: str) -> None:
        pass


def _service(identity: Identity | None = None) -> tuple[MemoryService, FakeStorage]:
    storage = FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=False,
        identity=identity,
    )
    return svc, storage


async def test_anonymous_remember_blocked():
    svc, _ = _service(identity=ANONYMOUS)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "rejected"
    assert "identity" in result["reason"].lower()


async def test_anonymous_search_allowed():
    svc, storage = _service(identity=ANONYMOUS)
    from datetime import UTC, datetime

    mem = Memory(
        id="m1",
        content="test fact",
        type="decision",
        repos=["repo"],
        tags=[],
        author="dev@example.com",
        created_at=datetime.now(UTC),
    )
    storage._memories["m1"] = mem
    results = await svc.search("test")
    assert isinstance(results, list)  # No error thrown — reads allowed for anonymous


async def test_authenticated_remember_sets_author():
    ident = Identity(email="dev@example.com", repos=["distill"])
    svc, storage = _service(identity=ident)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "saved"
    assert storage.saved[0].author == "dev@example.com"


async def test_no_identity_means_no_enforcement():
    """When identity is None (auth disabled), behaves as before."""
    svc, storage = _service(identity=None)
    result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
    assert result["status"] == "saved"
    assert storage.saved[0].author is None


async def test_anonymous_update_blocked():
    svc, _ = _service(identity=ANONYMOUS)
    result = await svc.update("some-id", "new content")
    assert result["status"] == "rejected"


async def test_anonymous_forget_blocked():
    svc, _ = _service(identity=ANONYMOUS)
    result = await svc.forget("some-id")
    assert result["status"] == "rejected"


async def test_anonymous_confirm_blocked_defense_in_depth():
    """confirm_memory itself should block for anonymous (defense-in-depth)."""
    svc, _ = _service(identity=ANONYMOUS)
    result = await svc.confirm_memory("fake-pending-id")
    assert result["status"] == "rejected"
    assert "identity" in result["reason"].lower()


def test_rls_init_sql_creates_policy():
    sql = _rls_init_sql()
    assert "CREATE POLICY" in sql or "DO $$" in sql
    assert "app.repos" in sql


def test_set_session_identity_sql():
    sql = _set_session_identity_sql("dev@example.com", ["distill", "other-repo"])
    assert "app.user_email" in sql
    assert "dev@example.com" in sql
    assert "distill" in sql
