"""Integration tests for SqliteStore.get_lineage() — real SQLite + LanceDB.

Tests the actual SQL queries, cycle protection, and snippet formatting
against a real database, not fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from distill_mcp.adapters.storage.sqlite_store import SqliteStore
from distill_mcp.domain.models import Memory

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path) -> SqliteStore:
    s = SqliteStore(str(tmp_path))
    s.initialize()
    return s


def _mem(id: str, content: str, age_days: int = 0) -> Memory:
    return Memory(
        id=id,
        content=content,
        type="decision",
        repos=["repo"],
        tags=["test"],
        author=None,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


VEC = [0.1] * 768


class TestGetLineage:
    async def test_single_memory_returns_self(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "Use PostgreSQL"), VEC)
        lineage = await store.get_lineage("m1")
        assert len(lineage) == 1
        assert lineage[0]["id"] == "m1"
        assert lineage[0]["direction"] == "self"

    async def test_two_step_chain(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "Use Redis", age_days=30), VEC)
        await store.save(_mem("m2", "Use Memcached"), VEC, supersedes="m1")

        lineage = await store.get_lineage("m2")
        assert len(lineage) == 2
        assert lineage[0]["id"] == "m1"
        assert lineage[0]["direction"] == "predecessor"
        assert lineage[1]["id"] == "m2"
        assert lineage[1]["direction"] == "self"

    async def test_query_from_predecessor_shows_successor(
        self, store: SqliteStore
    ) -> None:
        await store.save(_mem("m1", "Use Redis", age_days=30), VEC)
        await store.save(_mem("m2", "Use Memcached"), VEC, supersedes="m1")

        lineage = await store.get_lineage("m1")
        assert len(lineage) == 2
        assert lineage[0]["direction"] == "self"
        assert lineage[1]["direction"] == "successor"
        assert lineage[1]["id"] == "m2"

    async def test_three_step_chain_from_middle(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "v1", age_days=60), VEC)
        await store.save(_mem("m2", "v2", age_days=30), VEC, supersedes="m1")
        await store.save(_mem("m3", "v3"), VEC, supersedes="m2")

        lineage = await store.get_lineage("m2")
        assert len(lineage) == 3
        assert [e["id"] for e in lineage] == ["m1", "m2", "m3"]
        assert [e["direction"] for e in lineage] == [
            "predecessor",
            "self",
            "successor",
        ]

    async def test_nonexistent_memory_returns_empty(self, store: SqliteStore) -> None:
        lineage = await store.get_lineage("nonexistent")
        assert lineage == []

    async def test_snippet_truncated_with_ellipsis(self, store: SqliteStore) -> None:
        long_content = "A" * 100
        await store.save(_mem("m1", long_content), VEC)

        lineage = await store.get_lineage("m1")
        assert lineage[0]["snippet"] == "A" * 80 + "..."

    async def test_snippet_not_truncated_for_short_content(
        self, store: SqliteStore
    ) -> None:
        await store.save(_mem("m1", "Short content"), VEC)

        lineage = await store.get_lineage("m1")
        assert lineage[0]["snippet"] == "Short content"

    async def test_includes_soft_deleted_memories(self, store: SqliteStore) -> None:
        """Lineage should show soft-deleted predecessors (they're history)."""
        await store.save(_mem("m1", "Old decision", age_days=30), VEC)
        await store.save(_mem("m2", "New decision"), VEC, supersedes="m1")
        await store.delete("m1")  # soft-delete the predecessor

        lineage = await store.get_lineage("m2")
        assert len(lineage) == 2
        assert lineage[0]["id"] == "m1"
        assert lineage[0]["deleted_at"] is not None

    async def test_independent_memories_no_lineage(self, store: SqliteStore) -> None:
        """Unrelated memories should not appear in each other's lineage."""
        await store.save(_mem("m1", "Decision A"), VEC)
        await store.save(_mem("m2", "Decision B"), VEC)

        lineage = await store.get_lineage("m1")
        assert len(lineage) == 1
        assert lineage[0]["id"] == "m1"


class TestPurgeExpired:
    async def test_purges_old_soft_deleted(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "To be purged"), VEC)
        # Manually backdate the soft-delete timestamp
        store._conn.execute(
            "UPDATE memories SET deleted_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(days=100)).isoformat(),
                "m1",
            ),
        )
        store._conn.commit()

        count = await store.purge_expired(retention_days=90)
        assert count == 1
        # Should be physically gone from memories table
        row = store._conn.execute(
            "SELECT id FROM memories WHERE id = ?", ("m1",)
        ).fetchone()
        assert row is None

    async def test_purge_removes_from_fts(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "PostgreSQL chosen for pgvector"), VEC)
        store._conn.execute(
            "UPDATE memories SET deleted_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=100)).isoformat(), "m1"),
        )
        store._conn.commit()

        await store.purge_expired(retention_days=90)
        fts_row = store._conn.execute(
            "SELECT id FROM memories_fts WHERE id = ?", ("m1",)
        ).fetchone()
        assert fts_row is None

    async def test_purge_removes_from_lancedb(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "To be purged"), VEC)
        store._conn.execute(
            "UPDATE memories SET deleted_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=100)).isoformat(), "m1"),
        )
        store._conn.commit()

        await store.purge_expired(retention_days=90)
        # LanceDB should no longer have this vector
        table = store._lance.open_table("vectors")
        results = table.search(VEC).metric("cosine").limit(10).to_list()
        ids = [r["id"] for r in results]
        assert "m1" not in ids

    async def test_keeps_recently_deleted(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "Recently deleted"), VEC)
        await store.delete("m1")  # soft-delete now

        count = await store.purge_expired(retention_days=90)
        assert count == 0
        # Should still exist in DB
        row = store._conn.execute(
            "SELECT id FROM memories WHERE id = ?", ("m1",)
        ).fetchone()
        assert row is not None

    async def test_keeps_active_memories(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "Active memory"), VEC)

        count = await store.purge_expired(retention_days=90)
        assert count == 0
        mem = await store.get("m1")
        assert mem is not None

    async def test_purge_multiple(self, store: SqliteStore) -> None:
        for i in range(5):
            await store.save(_mem(f"exp-{i}", f"Expired memory {i}"), VEC)
            store._conn.execute(
                "UPDATE memories SET deleted_at = ? WHERE id = ?",
                (
                    (datetime.now(UTC) - timedelta(days=100 + i)).isoformat(),
                    f"exp-{i}",
                ),
            )
        # Keep one active
        await store.save(_mem("active", "Still good"), VEC)
        store._conn.commit()

        count = await store.purge_expired(retention_days=90)
        assert count == 5
        assert await store.get("active") is not None

    async def test_purge_returns_zero_when_nothing_to_purge(
        self, store: SqliteStore
    ) -> None:
        count = await store.purge_expired(retention_days=90)
        assert count == 0


class TestTemporalFilterSqlite:
    """Test after/before filtering against the real SQLite store."""

    async def test_after_filters_old_memories(self, store: SqliteStore) -> None:
        await store.save(_mem("old", "Old decision", age_days=60), VEC)
        await store.save(_mem("new", "New decision", age_days=5), VEC)

        cutoff = datetime.now(UTC) - timedelta(days=30)
        results = await store.search("decision", VEC, 10, after=cutoff)
        ids = {r.memory.id for r in results}
        assert "new" in ids
        assert "old" not in ids

    async def test_before_filters_new_memories(self, store: SqliteStore) -> None:
        await store.save(_mem("old", "Old decision", age_days=60), VEC)
        await store.save(_mem("new", "New decision", age_days=5), VEC)

        cutoff = datetime.now(UTC) - timedelta(days=30)
        results = await store.search("decision", VEC, 10, before=cutoff)
        ids = {r.memory.id for r in results}
        assert "old" in ids
        assert "new" not in ids

    async def test_combined_date_range(self, store: SqliteStore) -> None:
        await store.save(_mem("ancient", "Ancient", age_days=90), VEC)
        await store.save(_mem("middle", "Middle", age_days=45), VEC)
        await store.save(_mem("recent", "Recent", age_days=5), VEC)

        after = datetime.now(UTC) - timedelta(days=60)
        before = datetime.now(UTC) - timedelta(days=10)
        results = await store.search("decision", VEC, 10, after=after, before=before)
        ids = {r.memory.id for r in results}
        assert ids == {"middle"}

    async def test_no_filter_returns_all(self, store: SqliteStore) -> None:
        await store.save(_mem("m1", "Decision one"), VEC)
        await store.save(_mem("m2", "Decision two"), VEC)

        results = await store.search("decision", VEC, 10)
        assert len(results) == 2
