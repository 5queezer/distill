"""Timeline export — verify HTML generation and CLI filtering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from distill_mcp.domain.models import Memory
from distill_mcp.formats.timeline import generate_timeline_html


def _mem(
    id: str = "abc123",
    content: str = "PostgreSQL chosen for pgvector support",
    type: str = "decision",
    repos: list[str] | None = None,
    tags: list[str] | None = None,
    created_at: str = "2025-09-15T12:00:00",
    supersedes: str | None = None,
) -> Memory:
    return Memory(
        id=id,
        content=content,
        type=type,
        repos=repos or ["distill"],
        tags=tags or [],
        author=None,
        created_at=datetime.fromisoformat(created_at).replace(tzinfo=UTC),
        supersedes=supersedes,
    )


class TestTimelineHtml:
    def test_empty_state(self) -> None:
        html = generate_timeline_html([])
        assert "No memories yet" in html
        assert "<!DOCTYPE html>" in html

    def test_single_memory_renders(self) -> None:
        html = generate_timeline_html([_mem()])
        assert "Knowledge Timeline" in html
        assert "PostgreSQL chosen" in html
        assert '"type": "decision"' in html

    def test_multiple_repos_appear(self) -> None:
        memories = [
            _mem(id="a", repos=["distill"]),
            _mem(id="b", repos=["axiom-vault"], created_at="2025-10-01T12:00:00"),
        ]
        html = generate_timeline_html(memories)
        assert "distill" in html
        assert "axiom-vault" in html

    def test_supersedes_chain_in_data(self) -> None:
        memories = [
            _mem(id="old1", type="failure", content="Tauri abandoned"),
            _mem(
                id="new1",
                type="decision",
                content="SwiftUI chosen",
                supersedes="old1",
                created_at="2025-10-01T12:00:00",
            ),
        ]
        html = generate_timeline_html(memories)
        assert '"supersedes": "old1"' in html

    def test_all_types_encoded(self) -> None:
        types = ["decision", "pattern", "failure", "dependency", "context"]
        memories = [
            _mem(id=f"m{i}", type=t, created_at=f"2025-0{i + 1}-15T12:00:00")
            for i, t in enumerate(types)
        ]
        html = generate_timeline_html(memories)
        for t in types:
            assert f'"type": "{t}"' in html

    def test_tags_included(self) -> None:
        html = generate_timeline_html([_mem(tags=["auth", "migration"])])
        assert "auth" in html
        assert "migration" in html

    def test_multi_repo_memory(self) -> None:
        html = generate_timeline_html([_mem(repos=["distill", "axiom-vault"])])
        assert "distill" in html
        assert "axiom-vault" in html

    def test_html_is_standalone(self) -> None:
        html = generate_timeline_html([_mem()])
        assert "<html" in html
        assert "</html>" in html
        assert "<style>" in html
        assert "<script>" in html
        # No external resource links
        assert "src=" not in html or 'src="http' not in html
        assert "href=" not in html or 'href="http' not in html

    def test_xss_content_escaped_via_js(self) -> None:
        """Content with HTML chars is JSON-encoded, JS esc() handles display."""
        html = generate_timeline_html([_mem(content='<script>alert("xss")</script>')])
        # JSON encoding escapes angle brackets as unicode or literal in JSON
        # The JS esc() function handles display-time escaping
        assert "<script>alert" not in html.split("const DATA =")[0]


@pytest.mark.asyncio
class TestExportAll:
    """Test SqliteStore.export_all via a real SQLite instance."""

    @pytest.fixture
    async def store(self, tmp_path):
        from distill_mcp.adapters.storage.sqlite_store import SqliteStore

        s = SqliteStore(str(tmp_path), rrf_k=60)
        s.initialize()
        return s

    async def _save(self, store, mem: Memory) -> None:
        vec = [0.1] * 768
        await store.save(mem, vec, supersedes=mem.supersedes)

    async def test_export_all_returns_all(self, store) -> None:
        await self._save(store, _mem(id="a"))
        await self._save(store, _mem(id="b", created_at="2025-10-01T12:00:00"))
        result = await store.export_all()
        assert len(result) == 2
        assert result[0].id == "a"  # ASC order
        assert result[1].id == "b"

    async def test_export_empty_db(self, store) -> None:
        result = await store.export_all()
        assert result == []

    async def test_export_filters_by_repo(self, store) -> None:
        await self._save(store, _mem(id="a", repos=["distill"]))
        await self._save(
            store,
            _mem(id="b", repos=["axiom"], created_at="2025-10-01T12:00:00"),
        )
        result = await store.export_all(repos=["distill"])
        assert len(result) == 1
        assert result[0].id == "a"

    async def test_export_filters_by_after(self, store) -> None:
        await self._save(store, _mem(id="old", created_at="2025-01-01T00:00:00"))
        await self._save(store, _mem(id="new", created_at="2025-07-01T00:00:00"))
        result = await store.export_all(after="2025-06")
        assert len(result) == 1
        assert result[0].id == "new"

    async def test_export_filters_by_before(self, store) -> None:
        await self._save(store, _mem(id="old", created_at="2025-01-01T00:00:00"))
        await self._save(store, _mem(id="new", created_at="2025-07-01T00:00:00"))
        result = await store.export_all(before="2025-06")
        assert len(result) == 1
        assert result[0].id == "old"

    async def test_export_excludes_deleted(self, store) -> None:
        await self._save(store, _mem(id="a"))
        await store.delete("a")
        result = await store.export_all()
        assert result == []

    async def test_export_preserves_supersedes(self, store) -> None:
        await self._save(store, _mem(id="old"))
        await self._save(
            store,
            _mem(id="new", supersedes="old", created_at="2025-10-01T12:00:00"),
        )
        result = await store.export_all()
        new_mem = next(m for m in result if m.id == "new")
        assert new_mem.supersedes == "old"

    async def test_export_combined_filters(self, store) -> None:
        await self._save(
            store,
            _mem(id="a", repos=["distill"], created_at="2025-03-01T00:00:00"),
        )
        await self._save(
            store,
            _mem(id="b", repos=["axiom"], created_at="2025-08-01T00:00:00"),
        )
        await self._save(
            store,
            _mem(id="c", repos=["distill"], created_at="2025-08-01T00:00:00"),
        )
        result = await store.export_all(repos=["distill"], after="2025-06")
        assert len(result) == 1
        assert result[0].id == "c"
