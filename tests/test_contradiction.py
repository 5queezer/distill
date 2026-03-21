"""Contradiction detection — find related memories, surface them, supersede on confirm.

Covers issue #58: detect when new memories contradict existing ones.
"""

from __future__ import annotations

from typing import Any

import pytest

from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output

    async def distill(self, raw_text: str) -> str:
        return self._output


class FakeEmbedder:
    """Embedder that returns different vectors based on content keywords."""

    async def embed(self, text: str) -> list[float]:
        # Return different vectors for different content to test similarity
        if "postgresql" in text.lower() or "postgres" in text.lower():
            vec = [0.9] * 384 + [0.1] * 384
        elif "sqlite" in text.lower():
            vec = [0.85] * 384 + [0.15] * 384  # Similar to postgres (both DBs)
        elif "redis" in text.lower():
            vec = [0.1] * 384 + [0.9] * 384  # Very different
        else:
            vec = [0.5] * 768
        return vec


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}
        self._vectors: dict[str, list[float]] = {}
        self._deleted: set[str] = set()

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        self._memories[memory.id] = memory
        self._vectors[memory.id] = vec
        return memory.id

    async def get(self, id: str) -> Memory | None:
        if id in self._deleted:
            return None
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        self._deleted.add(id)

    async def search(self, *a: Any, **kw: Any) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass

    async def find_related(
        self,
        vec: list[float],
        *,
        threshold: float = 0.80,
        top_k: int = 3,
        repo: str | None = None,
    ) -> list[tuple[str, float]]:
        """Compute cosine similarity against stored vectors."""
        import math

        results: list[tuple[str, float]] = []
        for mid, stored_vec in self._vectors.items():
            if mid in self._deleted:
                continue
            mem = self._memories.get(mid)
            if mem is None:
                continue
            if repo is not None and repo not in mem.repos:
                continue

            # Cosine similarity
            dot = sum(a * b for a, b in zip(vec, stored_vec, strict=False))
            norm_a = math.sqrt(sum(a * a for a in vec))
            norm_b = math.sqrt(sum(b * b for b in stored_vec))
            if norm_a == 0 or norm_b == 0:
                continue
            sim = dot / (norm_a * norm_b)
            if sim >= threshold:
                results.append((mid, round(sim, 4)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


def _service(
    *,
    preview_enabled: bool = True,
    storage: FakeStorage | None = None,
    embedder: FakeEmbedder | None = None,
) -> tuple[MemoryService, FakeStorage]:
    storage = storage or FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=embedder or FakeEmbedder(),
        distiller=FakeDistiller(),
        preview_enabled=preview_enabled,
    )
    return svc, storage


# ============================================================
# find_related surfaces related memories in remember response
# ============================================================


class TestRelatedMemoriesSurfaced:
    """remember() should return related_memories when similar memories exist."""

    async def test_no_related_when_empty_db(self) -> None:
        svc, _storage = _service()
        result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        assert result["status"] == "preview"
        assert "related_memories" not in result

    async def test_related_returned_when_similar_exists(self) -> None:
        svc, _storage = _service(preview_enabled=False)

        # Store a first memory about PostgreSQL
        first = await svc.remember(
            "Chose PostgreSQL for concurrent access", "decision", ["repo"]
        )
        assert first["status"] == "saved"

        # Store a second, similar memory — should flag the first as related
        second = await svc.remember(
            "Migrated to PostgreSQL for pgvector support", "decision", ["repo"]
        )
        assert second["status"] == "saved"
        assert "related_memories" in second
        assert len(second["related_memories"]) >= 1
        assert second["related_memories"][0]["id"] == first["id"]

    async def test_unrelated_not_returned(self) -> None:
        svc, _storage = _service(preview_enabled=False)

        # Store a memory about Redis (very different vector)
        await svc.remember("Using Redis for caching layer", "decision", ["repo"])

        # Store about PostgreSQL — Redis should NOT be related
        result = await svc.remember(
            "Chose PostgreSQL for pgvector support", "decision", ["repo"]
        )
        assert result["status"] == "saved"
        # Related might be empty or absent
        related = result.get("related_memories", [])
        for r in related:
            assert "redis" not in r.get("snippet", "").lower()

    async def test_related_in_preview_response(self) -> None:
        svc, _storage = _service(preview_enabled=True)

        # Pre-populate storage with a matching memory
        first = await svc.remember(
            "Chose PostgreSQL for concurrent access", "decision", ["repo"]
        )
        assert first["status"] == "preview"
        await svc.confirm_memory(first["pending_id"])

        # Now store another related one — preview should include related
        second = await svc.remember(
            "Migrated to PostgreSQL for pgvector support", "decision", ["repo"]
        )
        assert second["status"] == "preview"
        assert "related_memories" in second

    async def test_related_contains_snippet_and_similarity(self) -> None:
        svc, _storage = _service(preview_enabled=False)

        await svc.remember(
            "Chose PostgreSQL for concurrent access", "decision", ["repo"]
        )

        second = await svc.remember(
            "Migrated to PostgreSQL for pgvector support", "decision", ["repo"]
        )

        related = second.get("related_memories", [])
        assert len(related) >= 1
        entry = related[0]
        assert "id" in entry
        assert "similarity" in entry
        assert "snippet" in entry
        assert "type" in entry
        assert "created_at" in entry
        assert entry["similarity"] >= 0.80

    async def test_related_filtered_by_repo(self) -> None:
        svc, _storage = _service(preview_enabled=False)

        # Store in repo-a
        await svc.remember("Chose PostgreSQL for repo-a", "decision", ["repo-a"])

        # Store in repo-b — should NOT see repo-a's memory as related
        result = await svc.remember(
            "Chose PostgreSQL for repo-b", "decision", ["repo-b"]
        )
        # Related should be empty since we filter by first repo
        related = result.get("related_memories", [])
        assert len(related) == 0


# ============================================================
# confirm_memory with supersedes
# ============================================================


class TestSupersession:
    """confirm_memory(supersedes=[...]) should soft-delete old memories."""

    async def test_supersede_deletes_old_memory(self) -> None:
        svc, storage = _service(preview_enabled=True)

        # Store an old decision
        old_preview = await svc.remember(
            "Chose SQLite for simplicity", "decision", ["repo"]
        )
        old_result = await svc.confirm_memory(old_preview["pending_id"])
        old_id = old_result["id"]

        # Verify old memory exists
        assert await storage.get(old_id) is not None

        # Store a new, contradicting decision
        new_preview = await svc.remember(
            "Migrated to PostgreSQL for concurrent access", "decision", ["repo"]
        )
        new_result = await svc.confirm_memory(
            new_preview["pending_id"], supersedes=[old_id]
        )

        assert new_result["status"] == "saved"
        assert new_result["superseded"] == [old_id]
        # Old memory should be soft-deleted
        assert await storage.get(old_id) is None

    async def test_supersede_nonexistent_id_ignored(self) -> None:
        svc, _storage = _service(preview_enabled=True)

        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        result = await svc.confirm_memory(
            preview["pending_id"], supersedes=["nonexistent-id"]
        )

        assert result["status"] == "saved"
        # No superseded IDs since the memory didn't exist
        assert "superseded" not in result

    async def test_supersede_empty_list_is_noop(self) -> None:
        svc, _storage = _service(preview_enabled=True)

        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        result = await svc.confirm_memory(preview["pending_id"], supersedes=[])

        assert result["status"] == "saved"
        assert "superseded" not in result

    async def test_supersede_multiple_memories(self) -> None:
        svc, storage = _service(preview_enabled=True)

        # Create two old decisions
        old1 = await svc.remember("Chose SQLite for dev", "decision", ["repo"])
        old1_result = await svc.confirm_memory(old1["pending_id"])

        old2 = await svc.remember("Using SQLite with FTS5", "pattern", ["repo"])
        old2_result = await svc.confirm_memory(old2["pending_id"])

        # Supersede both
        new = await svc.remember(
            "Migrated to PostgreSQL with pgvector", "decision", ["repo"]
        )
        result = await svc.confirm_memory(
            new["pending_id"],
            supersedes=[old1_result["id"], old2_result["id"]],
        )

        assert result["status"] == "saved"
        assert set(result["superseded"]) == {old1_result["id"], old2_result["id"]}
        assert await storage.get(old1_result["id"]) is None
        assert await storage.get(old2_result["id"]) is None
