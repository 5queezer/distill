"""Use cases — orchestrates domain logic via ports."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, MemoryDetail, MemoryIndex, SearchResult
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
ACCESS_BOOST_WEIGHT = 0.1

# Preview TTL in seconds
PENDING_TTL = 300


def _to_index(memory: Memory, score: float = 0.0) -> MemoryIndex:
    """Convert a Memory to a compact MemoryIndex for progressive disclosure."""
    from distill_mcp.domain.models import MemoryIndex

    snippet = memory.content[:80] + ("..." if len(memory.content) > 80 else "")
    return MemoryIndex(
        id=memory.id,
        type=memory.type,
        snippet=snippet,
        repos=memory.repos,
        score=score,
        created_at=memory.created_at,
        est_tokens=len(memory.content) // 4,
        agent_id=memory.agent_id,
    )


def _to_detail(memory: Memory, score: float | None = None) -> MemoryDetail:
    """Convert a Memory to a full MemoryDetail."""
    from distill_mcp.domain.models import MemoryDetail

    return MemoryDetail(
        id=memory.id,
        content=memory.content,
        type=memory.type,
        repos=memory.repos,
        tags=memory.tags,
        score=score,
        created_at=memory.created_at,
        author=memory.author,
        agent_id=memory.agent_id,
        est_tokens=len(memory.content) // 4,
    )


class MemoryService:
    """Core use cases: remember, search, get, update, list_recent, forget."""

    def __init__(
        self,
        storage: StoragePort,
        embedder: EmbeddingPort,
        distiller: DistillerPort,
        *,
        distill_enabled: bool = True,
        distill_preview: bool = True,
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._distiller = distiller
        self._distill_enabled = distill_enabled
        self._distill_preview = distill_preview
        self._bg_tasks: set[asyncio.Task[None]] = set()
        # pending_id -> {memory, vec, expires_at}
        self._pending: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Pending store helpers
    # ------------------------------------------------------------------

    def cleanup_expired_pending(self) -> int:
        """Remove expired pending entries. Returns count removed."""
        now = time.time()
        expired = [pid for pid, e in self._pending.items() if e["expires_at"] <= now]
        for pid in expired:
            del self._pending[pid]
        return len(expired)

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
        agent_id: str | None = None,
    ) -> dict:
        from distill_mcp.domain.models import Memory

        # Opportunistic cleanup
        self.cleanup_expired_pending()

        # 0. Noise filter
        noise_reason = self._is_noise(raw_text)
        if noise_reason:
            return {"status": "rejected", "reason": noise_reason}

        # 1. Distill — inject agent_id prefix when present
        distill_input = raw_text
        if agent_id is not None:
            distill_input = f"[Agent: {agent_id}]\n{raw_text}"

        if self._distill_enabled:
            distilled = await self._distiller.distill(distill_input)
        else:
            distilled = raw_text  # no prefix in stored content when distill off

        if "no_factual_content" in distilled.lower().replace(" ", "_"):
            return {"status": "rejected", "reason": "no factual content"}

        # 2. Embed
        vec = await self._embedder.embed(distilled)

        # 3. Dedup
        existing_id = await self._storage.check_duplicate(vec)
        if existing_id:
            return {"status": "duplicate", "existing_id": existing_id}

        # 4. Build memory object
        memory = Memory(
            id=uuid4().hex,
            content=distilled,
            type=type,
            repos=repos,
            tags=tags or [],
            author=None,
            created_at=datetime.now(UTC),
            agent_id=agent_id,
        )

        # 5. Preview gate
        if self._distill_preview:
            pending_id = uuid4().hex
            self._pending[pending_id] = {
                "memory": memory,
                "vec": vec,
                "expires_at": time.time() + PENDING_TTL,
            }
            return {
                "status": "pending",
                "pending_id": pending_id,
                "distilled": distilled,
                "message": (
                    f"Call confirm_memory(id='{pending_id}') to store, "
                    "or pass override='...' to edit first. Expires in 5 min."
                ),
            }

        # 6. Direct save (preview disabled)
        saved_id = await self._storage.save(memory, vec)
        return {"status": "saved", "id": saved_id, "distilled": distilled}

    async def confirm_memory(
        self, pending_id: str, override: str | None = None
    ) -> dict:
        """Commit a pending preview to storage."""
        from distill_mcp.domain.models import Memory

        entry = self._pending.get(pending_id)
        if entry is None:
            self.cleanup_expired_pending()
            return {"status": "not_found", "pending_id": pending_id}

        if entry["expires_at"] <= time.time():
            del self._pending[pending_id]
            self.cleanup_expired_pending()
            return {"status": "expired", "pending_id": pending_id}

        self.cleanup_expired_pending()

        memory: Memory = entry["memory"]
        vec: list[float] = entry["vec"]

        if override is not None:
            if self._distill_enabled:
                distilled = await self._distiller.distill(override)
            else:
                distilled = override
            vec = await self._embedder.embed(distilled)
            memory = Memory(
                id=uuid4().hex,
                content=distilled,
                type=memory.type,
                repos=memory.repos,
                tags=memory.tags,
                author=memory.author,
                created_at=datetime.now(UTC),
                agent_id=memory.agent_id,
            )

        try:
            saved_id = await self._storage.save(memory, vec)
        except Exception:
            self._pending[pending_id] = entry  # restore on failure
            raise
        del self._pending[pending_id]

        return {"status": "saved", "id": saved_id, "distilled": memory.content}

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        repo: str | None = None,
        agent_id: str | None = None,
    ) -> list[MemoryIndex]:
        vec = await self._embedder.embed(query)
        results = await self._storage.search(
            query, vec, top_k, repo=repo, agent_id=agent_id
        )

        # Recency boost
        now = datetime.now(UTC)
        for r in results:
            age_days = (now - r.memory.created_at).days
            recency = 1.0 / (1.0 + age_days / RECENCY_HALFLIFE_DAYS)
            r.score = (1.0 - RECENCY_WEIGHT) * r.score + RECENCY_WEIGHT * recency

        # Access-frequency boost
        for r in results:
            access_boost = math.log(r.memory.access_count + 1) * ACCESS_BOOST_WEIGHT
            r.score *= 1.0 + access_boost

        results = [r for r in results if r.score >= MIN_SEARCH_SCORE]
        results.sort(key=lambda r: r.score, reverse=True)

        for r in results:
            task = asyncio.create_task(self._storage.record_access(r.memory.id))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

        return [_to_index(r.memory, r.score) for r in results]

    async def get(self, id: str) -> Memory | None:
        return await self._storage.get(id)

    async def get_batch(self, ids: list[str]) -> list[MemoryDetail]:
        """Fetch full details for multiple memory IDs (Layer 2)."""
        details: list[MemoryDetail] = []
        for mid in ids:
            if not mid:
                continue
            mem = await self._storage.get(mid)
            if mem is not None:
                details.append(_to_detail(mem))
        return details

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
            agent_id=old.agent_id,
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
        agent_id: str | None = None,
    ) -> list[MemoryIndex]:
        memories = await self._storage.list_recent(
            repo=repo, tag=tag, type=type, limit=limit, agent_id=agent_id
        )
        return [_to_index(m) for m in memories]

    async def forget(self, id: str, *, agent_id: str | None = None) -> dict:
        mem = await self._storage.get(id)
        if not mem:
            return {"status": "not_found"}
        if agent_id is not None and mem.agent_id != agent_id:
            return {
                "status": "forbidden",
                "reason": "Memory belongs to a different agent",
            }
        await self._storage.delete(id)
        return {"status": "forgotten", "id": id}
