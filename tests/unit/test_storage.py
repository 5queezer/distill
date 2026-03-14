"""Tests for SqliteStore — in-memory SQLite + temp-dir LanceDB."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.models import Memory


def _vec(seed: float = 0.1) -> list[float]:
    import math

    return [math.sin(seed * 100.0 + i) for i in range(768)]


def _memory(
    id: str = "m1",
    content: str = "Test memory",
    type: str = "decision",
    repos: list[str] | None = None,
    tags: list[str] | None = None,
) -> Memory:
    return Memory(
        id=id,
        content=content,
        type=type,
        repos=repos or ["test-repo"],
        tags=tags or ["python"],
        author=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def store(tmp_path: str) -> SqliteStore:
    s = SqliteStore(str(tmp_path), rrf_k=60)
    s.initialize()
    return s


pytestmark = pytest.mark.asyncio


async def test_save_and_get(store: SqliteStore) -> None:
    mem = _memory()
    await store.save(mem, _vec())
    got = await store.get("m1")
    assert got is not None
    assert got.id == "m1"
    assert got.content == "Test memory"
    assert got.repos == ["test-repo"]
    assert got.tags == ["python"]


async def test_get_nonexistent(store: SqliteStore) -> None:
    assert await store.get("nope") is None


async def test_soft_delete(store: SqliteStore) -> None:
    await store.save(_memory(), _vec())
    await store.delete("m1")
    assert await store.get("m1") is None


async def test_fts_search(store: SqliteStore) -> None:
    await store.save(_memory(content="Flask migration to FastAPI"), _vec(0.1))
    await store.save(_memory(id="m2", content="PostgreSQL jsonb indexing"), _vec(0.2))
    results = await store.search("FastAPI", _vec(0.15), top_k=5)
    ids = [r.memory.id for r in results]
    assert "m1" in ids


async def test_vector_search(store: SqliteStore) -> None:
    v1 = _vec(0.1)
    v2 = _vec(0.9)
    await store.save(_memory(content="alpha"), v1)
    await store.save(_memory(id="m2", content="beta"), v2)
    # Search with a vector close to v1
    results = await store.search("", _vec(0.10001), top_k=5)
    assert results[0].memory.id == "m1"


async def test_hybrid_rrf(store: SqliteStore) -> None:
    v1 = _vec(0.1)
    await store.save(_memory(content="Deployed Envoy proxy"), v1)
    await store.save(
        _memory(id="m2", content="Configured nginx reverse proxy"), _vec(0.5)
    )
    # Query matches m1 by text ("Envoy") and vector (close to v1)
    results = await store.search("Envoy proxy", _vec(0.1001), top_k=5)
    assert results[0].memory.id == "m1"


async def test_check_duplicate_found(store: SqliteStore) -> None:
    v = _vec(0.5)
    await store.save(_memory(), v)
    # Nearly identical vector should be flagged
    similar = [x + 0.0001 for x in v]
    dup_id = await store.check_duplicate(similar, threshold=0.95)
    assert dup_id == "m1"


async def test_check_duplicate_not_found(store: SqliteStore) -> None:
    await store.save(_memory(), _vec(0.1))
    # Very different vector
    dup_id = await store.check_duplicate(_vec(0.9), threshold=0.95)
    assert dup_id is None


async def test_check_duplicate_ignores_deleted(store: SqliteStore) -> None:
    v = _vec(0.5)
    await store.save(_memory(), v)
    await store.delete("m1")
    similar = [x + 0.0001 for x in v]
    dup_id = await store.check_duplicate(similar, threshold=0.95)
    assert dup_id is None


async def test_list_recent_all(store: SqliteStore) -> None:
    await store.save(_memory(id="m1"), _vec(0.1))
    await store.save(_memory(id="m2"), _vec(0.2))
    recent = await store.list_recent(limit=10)
    assert len(recent) == 2


async def test_list_recent_filter_repo(store: SqliteStore) -> None:
    await store.save(_memory(id="m1", repos=["alpha"]), _vec(0.1))
    await store.save(_memory(id="m2", repos=["beta"]), _vec(0.2))
    recent = await store.list_recent(repo="alpha", limit=10)
    assert len(recent) == 1
    assert recent[0].id == "m1"


async def test_list_recent_filter_tag(store: SqliteStore) -> None:
    await store.save(_memory(id="m1", tags=["python"]), _vec(0.1))
    await store.save(_memory(id="m2", tags=["rust"]), _vec(0.2))
    recent = await store.list_recent(tag="rust", limit=10)
    assert len(recent) == 1
    assert recent[0].id == "m2"


async def test_list_recent_filter_type(store: SqliteStore) -> None:
    await store.save(_memory(id="m1", type="decision"), _vec(0.1))
    await store.save(_memory(id="m2", type="failure"), _vec(0.2))
    recent = await store.list_recent(type="failure", limit=10)
    assert len(recent) == 1
    assert recent[0].id == "m2"


async def test_list_recent_excludes_deleted(store: SqliteStore) -> None:
    await store.save(_memory(id="m1"), _vec(0.1))
    await store.save(_memory(id="m2"), _vec(0.2))
    await store.delete("m1")
    recent = await store.list_recent(limit=10)
    assert len(recent) == 1
    assert recent[0].id == "m2"


async def test_save_with_supersedes(store: SqliteStore) -> None:
    await store.save(_memory(id="m1"), _vec(0.1))
    await store.save(_memory(id="m2"), _vec(0.2), supersedes="m1")
    got = await store.get("m2")
    assert got is not None
