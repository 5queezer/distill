"""Embedding dimension mismatch detection.

Verifies that the SQLite store detects when the current embedding model
produces vectors with a different dimension than what's already stored.
"""

from __future__ import annotations

import pytest

from distill_mcp.adapters.storage.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(str(tmp_path))
    s.initialize()
    return s


def test_no_vectors_returns_none(store: SqliteStore) -> None:
    assert store.get_vector_dimension() is None


@pytest.mark.asyncio
async def test_dimension_tracked_after_first_save(store: SqliteStore) -> None:
    from datetime import UTC, datetime

    from distill_mcp.domain.models import Memory

    mem = Memory(
        id="test-1",
        content="test content",
        type="decision",
        repos=["repo"],
        tags=["tag"],
        author=None,
        created_at=datetime.now(UTC),
    )
    vec_768 = [0.1] * 768
    await store.save(mem, vec_768)
    assert store.get_vector_dimension() == 768


@pytest.mark.asyncio
async def test_dimension_read_from_schema_on_init(tmp_path) -> None:
    """Dimension is read from the LanceDB schema when store re-initializes."""
    from datetime import UTC, datetime

    from distill_mcp.domain.models import Memory

    store1 = SqliteStore(str(tmp_path))
    store1.initialize()
    mem = Memory(
        id="test-1",
        content="test content",
        type="decision",
        repos=["repo"],
        tags=["tag"],
        author=None,
        created_at=datetime.now(UTC),
    )
    await store1.save(mem, [0.1] * 768)

    # Re-open the store — should read dimension from existing LanceDB table
    store2 = SqliteStore(str(tmp_path))
    store2.initialize()
    assert store2.get_vector_dimension() == 768


def test_embedding_meta_roundtrip(store: SqliteStore) -> None:
    model, dim = store.get_embedding_meta()
    assert model is None
    assert dim is None

    store.save_embedding_meta("nomic-embed-text", 768)

    model, dim = store.get_embedding_meta()
    assert model == "nomic-embed-text"
    assert dim == 768


def test_embedding_meta_update(store: SqliteStore) -> None:
    store.save_embedding_meta("nomic-embed-text", 768)
    store.save_embedding_meta("gte-qwen2-1.5b", 3072)

    model, dim = store.get_embedding_meta()
    assert model == "gte-qwen2-1.5b"
    assert dim == 3072


def test_db_meta_table_created(store: SqliteStore) -> None:
    """The db_meta table exists after initialization."""
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='db_meta'"
    ).fetchone()
    assert row is not None
