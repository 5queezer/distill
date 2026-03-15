"""Use cases — orchestrates domain logic via ports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, SearchResult
    from distill_mcp.domain.ports import DistillerPort, EmbeddingPort, StoragePort

# Noise filter: trivial inputs that should never be stored
NOISE_PATTERNS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "yes",
        "no",
        "sure",
        "lgtm",
        "\U0001f44d",
        "\U0001f44e",
        "\U0001f64f",
    }
)
MIN_CONTENT_LENGTH = 20

# Search quality thresholds
MIN_SEARCH_SCORE = 0.35
RECENCY_WEIGHT = 0.15
RECENCY_HALFLIFE_DAYS = 30


class MemoryService:
    """Core use cases: remember, search, get, update, list_recent, forget."""

    def __init__(
        self,
        storage: StoragePort,
        embedder: EmbeddingPort,
        distiller: DistillerPort,
        *,
        distill_enabled: bool = True,
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._distiller = distiller
        self._distill_enabled = distill_enabled

    @staticmethod
    def _is_noise(text: str) -> str | None:
        """Return rejection reason if text is noise, None otherwise."""
        stripped = text.strip()
        if stripped.lower() in NOISE_PATTERNS:
            return "Input is trivial (greeting/reaction). Nothing to store."
        if len(stripped) < MIN_CONTENT_LENGTH:
            return f"Input too short ({len(stripped)} chars). Minimum {MIN_CONTENT_LENGTH}."
        return None

    async def remember(
        self,
        raw_text: str,
        type: str,
        repos: list[str],
        tags: list[str] | None = None,
    ) -> dict:
        from distill_mcp.domain.models import Memory

        # 0. Noise filter — reject before wasting Ollama cycles
        noise_reason = self._is_noise(raw_text)
        if noise_reason:
            return {"status": "rejected", "reason": noise_reason}

        # 1. Distill
        if self._distill_enabled:
            distilled = await self._distiller.distill(raw_text)
        else:
            distilled = raw_text

        if "no_factual_content" in distilled.lower().replace(" ", "_"):
            return {"status": "rejected", "reason": "no factual content"}

        # 2. Embed
        vec = await self._embedder.embed(distilled)

        # 3. Dedup
        existing_id = await self._storage.check_duplicate(vec)
        if existing_id:
            return {"status": "duplicate", "existing_id": existing_id}

        # 4. Save
        memory = Memory(
            id=uuid4().hex,
            content=distilled,
            type=type,
            repos=repos,
            tags=tags or [],
            author=None,
            created_at=datetime.now(UTC),
        )
        saved_id = await self._storage.save(memory, vec)
        return {"status": "saved", "id": saved_id, "distilled": distilled}

    async def search(
        self, query: str, top_k: int = 5, *, repo: str | None = None
    ) -> list[SearchResult]:
        vec = await self._embedder.embed(query)
        results = await self._storage.search(query, vec, top_k, repo=repo)

        # Recency boost: blend RRF score with recency signal
        now = datetime.now(UTC)
        for r in results:
            age_days = (now - r.memory.created_at).days
            recency = 1.0 / (1.0 + age_days / RECENCY_HALFLIFE_DAYS)
            r.score = (1.0 - RECENCY_WEIGHT) * r.score + RECENCY_WEIGHT * recency

        # Hard min score: drop irrelevant results
        results = [r for r in results if r.score >= MIN_SEARCH_SCORE]

        # Re-sort after recency adjustment
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def get(self, id: str) -> Memory | None:
        return await self._storage.get(id)

    async def update(self, id: str, raw_text: str) -> dict:
        from distill_mcp.domain.models import Memory

        old = await self._storage.get(id)
        if not old:
            return {"status": "not_found"}

        if self._distill_enabled:
            distilled = await self._distiller.distill(raw_text)
        else:
            distilled = raw_text

        vec = await self._embedder.embed(distilled)

        new_memory = Memory(
            id=uuid4().hex,
            content=distilled,
            type=old.type,
            repos=old.repos,
            tags=old.tags,
            author=old.author,
            created_at=datetime.now(UTC),
        )
        await self._storage.save(new_memory, vec, supersedes=id)
        await self._storage.delete(id)
        return {
            "status": "updated",
            "old_id": id,
            "new_id": new_memory.id,
            "distilled": distilled,
        }

    async def list_recent(
        self,
        *,
        repo: str | None = None,
        tag: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        return await self._storage.list_recent(
            repo=repo, tag=tag, type=type, limit=limit
        )

    async def forget(self, id: str) -> dict:
        mem = await self._storage.get(id)
        if not mem:
            return {"status": "not_found"}
        await self._storage.delete(id)
        return {"status": "forgotten", "id": id}
