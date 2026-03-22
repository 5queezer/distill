"""Port interfaces — abstract boundaries the domain depends on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from distill_mcp.domain.models import Memory, SearchResult


class StoragePort(Protocol):
    async def save(
        self, memory: Memory, vec: list[float], *, supersedes: str | None = None
    ) -> str: ...
    async def get(self, id: str) -> Memory | None: ...
    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[SearchResult]: ...
    async def delete(self, id: str) -> None: ...
    async def record_access(self, id: str) -> None: ...
    async def list_recent(
        self,
        *,
        repo: str | None = None,
        tag: str | None = None,
        type: str | None = None,
        limit: int = 20,
        agent_id: str | None = None,
    ) -> list[Memory]: ...
    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None: ...
    async def find_related(
        self,
        vec: list[float],
        *,
        threshold: float = 0.80,
        top_k: int = 3,
        repo: str | None = None,
    ) -> list[tuple[str, float]]:
        """Find memories above similarity threshold.

        Returns list of (id, similarity_score) sorted by similarity desc.
        Used for contradiction detection — caller decides if results conflict.
        """
        ...

    async def get_lineage(self, memory_id: str) -> list[dict]:
        """Return the supersedes chain for a memory (both directions).

        Returns list of dicts with id, content snippet, created_at, direction
        ("predecessor" or "successor"), ordered from oldest to newest.
        """
        ...

    async def purge_expired(self, retention_days: int) -> int:
        """Hard-delete memories soft-deleted more than retention_days ago.

        Also removes associated vectors. Returns count of purged memories.
        """
        ...


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class DistillerPort(Protocol):
    async def distill(self, raw_text: str) -> str: ...


class ScannerPort(Protocol):
    def scan(self, text: str) -> list: ...
    def redact(self, text: str) -> tuple[str, list]: ...
    def has_secrets(self, text: str) -> bool: ...


class RerankerPort(Protocol):
    async def rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        Returns list of (original_index, relevance_score) sorted by score desc.
        """
        ...
