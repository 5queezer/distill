"""Port interfaces — abstract boundaries the domain depends on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, SearchResult


class StoragePort(Protocol):
    async def save(self, memory: Memory) -> str: ...
    async def get(self, id: str) -> Memory | None: ...
    async def search(
        self, query_text: str, query_vec: list[float], top_k: int
    ) -> list[SearchResult]: ...
    async def delete(self, id: str) -> None: ...


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class DistillerPort(Protocol):
    async def distill(self, raw_text: str) -> str: ...
