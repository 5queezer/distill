"""Use cases — orchestrates domain logic via ports."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from distill_mcp.domain.identity import Identity

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, MemoryDetail, MemoryIndex
    from distill_mcp.domain.ports import (
        DistillerPort,
        EmbeddingPort,
        RerankerPort,
        ScannerPort,
        StoragePort,
    )

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
ACCESS_BOOST_WEIGHT = 0.1

# Weibull decay parameters per memory type: (scale λ in days, shape k)
# S(t) = exp(-(t/λ)^k)  — 1.0 at t=0, decays toward 0
WEIBULL_PARAMS: dict[str, tuple[float, float]] = {
    "decision": (14.0, 1.5),  # fast decay — decisions get superseded
    "context": (7.0, 2.0),  # fast decay — context is ephemeral
    "failure": (45.0, 1.2),  # medium decay — failures become less relevant
    "pattern": (90.0, 0.8),  # slow decay — patterns are durable
    "dependency": (180.0, 0.7),  # very slow — dependency choices are long-lived
}
WEIBULL_DEFAULT = (30.0, 1.0)  # fallback: exponential decay, ~30 day halflife

# Preview TTL in seconds
PENDING_TTL = 300


@dataclass
class _PendingEntry:
    id: str
    raw_text: str
    distilled: str
    type: str
    repos: list[str]
    tags: list[str]
    vec: list[float]
    expires_at: datetime
    private_file: Path | None
    agent_id: str | None = None


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
    """Core use cases: remember, search, get, update, list_recent, forget, confirm_memory."""

    def __init__(
        self,
        storage: StoragePort,
        embedder: EmbeddingPort,
        distiller: DistillerPort,
        *,
        distill_enabled: bool = True,
        preview_enabled: bool = True,
        preview_ttl_seconds: int = 300,
        private_dir: Path | None = None,
        scanner: ScannerPort | None = None,
        max_memory_size: int = 8000,
        identity: Identity | None = None,
        reranker: RerankerPort | None = None,
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._distiller = distiller
        self._distill_enabled = distill_enabled
        self._preview_enabled = preview_enabled
        self._preview_ttl_seconds = preview_ttl_seconds
        self._private_dir = private_dir
        self._scanner = scanner
        self._max_memory_size = max_memory_size
        self._identity = identity
        self._reranker = reranker
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._pending: dict[str, _PendingEntry] = {}

    @property
    def identity_repos(self) -> list[str] | None:
        """Return repos from identity, or None if auth disabled/anonymous."""
        if self._identity and not self._identity.is_anonymous:
            return self._identity.repos
        return None

    @staticmethod
    def _is_noise(text: str) -> str | None:
        """Return rejection reason if text is noise, None otherwise."""
        stripped = text.strip()
        if stripped.lower() in NOISE_PATTERNS:
            return "Input is trivial (greeting/reaction). Nothing to store."
        if len(stripped) < MIN_CONTENT_LENGTH:
            return f"Input too short ({len(stripped)} chars). Minimum {MIN_CONTENT_LENGTH}."
        return None

    @staticmethod
    def _cleanup_private_file(entry: _PendingEntry) -> None:
        """Delete the raw-text private file for an entry, ignoring errors."""
        if entry.private_file is not None:
            try:
                entry.private_file.unlink(missing_ok=True)
            except OSError as exc:
                logging.debug(
                    "Could not delete private file %s: %s", entry.private_file, exc
                )

    def _prune_expired(self) -> None:
        """Remove expired entries from pending dict and delete their private files."""
        now = datetime.now(UTC)
        expired_ids = [
            pid for pid, entry in self._pending.items() if entry.expires_at < now
        ]
        for pid in expired_ids:
            entry = self._pending.pop(pid)
            self._cleanup_private_file(entry)

    def _require_write(self) -> dict | None:
        """Return rejection dict if writes are blocked, None if allowed."""
        if self._identity is not None and self._identity.is_anonymous:
            return {
                "status": "rejected",
                "reason": "Identity required for writes. Configure git user.email.",
            }
        return None

    async def _find_related_info(
        self, vec: list[float], *, repo: str | None = None
    ) -> list[dict]:
        """Find related memories and return compact info for contradiction detection."""
        pairs = await self._storage.find_related(vec, repo=repo)
        related: list[dict] = []
        for mid, sim in pairs:
            mem = await self._storage.get(mid)
            if mem is None:
                continue
            snippet = mem.content[:120] + ("..." if len(mem.content) > 120 else "")
            related.append(
                {
                    "id": mid,
                    "similarity": sim,
                    "type": mem.type,
                    "snippet": snippet,
                    "created_at": mem.created_at.isoformat(),
                }
            )
        return related

    async def remember(
        self,
        raw_text: str,
        type: str,
        repos: list[str],
        tags: list[str] | None = None,
        agent_id: str | None = None,
        confirmed: bool = False,
    ) -> dict:
        from distill_mcp.domain.models import Memory

        # Prune expired pending entries
        self._prune_expired()

        if block := self._require_write():
            return block

        # 0a. Size limit
        if len(raw_text) > self._max_memory_size:
            return {
                "status": "rejected",
                "reason": f"Content exceeds maximum size ({self._max_memory_size} chars)",
            }

        # 0b. Noise filter — reject before wasting Ollama cycles
        noise_reason = self._is_noise(raw_text)
        if noise_reason:
            return {"status": "rejected", "reason": noise_reason}

        # Layer 1: Pre-distillation secret scan — redact before Ollama sees it
        pre_findings: list = []
        if self._scanner is not None:
            raw_text, pre_findings = self._scanner.redact(raw_text)

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

        # Layer 3: Post-distillation secret scan — hard block if LLM leaked secrets
        if self._scanner is not None and self._scanner.has_secrets(distilled):
            return {
                "status": "blocked",
                "reason": "Distilled output contained potential secrets. Nothing was saved.",
            }

        # 2. Embed
        vec = await self._embedder.embed(distilled)

        # 2b. Find related memories for contradiction detection
        repo_filter = repos[0] if repos else None
        related = await self._find_related_info(vec, repo=repo_filter)

        # Store immediately when preview is disabled or caller confirmed proactively
        if not self._preview_enabled or confirmed:
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
                author=self._identity.email if self._identity else None,
                created_at=datetime.now(UTC),
                agent_id=agent_id,
            )
            saved_id = await self._storage.save(memory, vec)
            result: dict = {
                "status": "saved",
                "id": saved_id,
                "distilled": distilled,
                "redacted_count": len(pre_findings),
            }
            if related:
                result["related_memories"] = related
            return result

        # Preview enabled: save to pending, write raw text to private file
        pending_id = uuid4().hex
        private_file: Path | None = None
        if self._private_dir is not None:
            self._private_dir.mkdir(parents=True, exist_ok=True)
            private_file = self._private_dir / f"{pending_id}.txt"
            fd = os.open(private_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(raw_text)

        expires_at = datetime.now(UTC) + timedelta(seconds=self._preview_ttl_seconds)
        self._pending[pending_id] = _PendingEntry(
            id=pending_id,
            raw_text=raw_text,
            distilled=distilled,
            type=type,
            repos=repos,
            tags=tags or [],
            vec=vec,
            expires_at=expires_at,
            private_file=private_file,
            agent_id=agent_id,
        )
        result = {
            "status": "preview",
            "pending_id": pending_id,
            "distilled": distilled,
            "expires_in_seconds": self._preview_ttl_seconds,
            "redacted_count": len(pre_findings),
        }
        if related:
            result["related_memories"] = related
        return result

    async def confirm_memory(
        self,
        pending_id: str,
        override: str | None = None,
        supersedes: list[str] | None = None,
    ) -> dict:
        from distill_mcp.domain.models import Memory

        if block := self._require_write():
            return block

        # Optimistic claim: pop before any await to prevent concurrent confirms
        # of the same pending_id from both succeeding.
        entry = self._pending.pop(pending_id, None)
        if entry is None:
            return {"status": "not_found", "reason": "pending_id not found or expired"}

        # Prune other expired entries now that ours is safely claimed
        self._prune_expired()

        # Check expiry (entry is already removed from pending)
        if entry.expires_at < datetime.now(UTC):
            self._cleanup_private_file(entry)
            return {"status": "expired"}

        # Determine final text and vector.
        try:
            if override is not None:
                # Block override if it contains secrets or PII — user must fix it
                if self._scanner is not None and self._scanner.has_secrets(override):
                    self._pending[pending_id] = entry
                    return {
                        "status": "blocked",
                        "reason": "Override text contained secrets or PII. Edit and retry.",
                    }
                final_text = override
                vec = await self._embedder.embed(final_text)
            else:
                final_text = entry.distilled
                vec = entry.vec

            # Dedup check
            existing_id = await self._storage.check_duplicate(vec)
            if existing_id:
                self._cleanup_private_file(entry)
                return {"status": "duplicate", "existing_id": existing_id}

            # Save
            memory = Memory(
                id=uuid4().hex,
                content=final_text,
                type=entry.type,
                repos=entry.repos,
                tags=entry.tags,
                author=self._identity.email if self._identity else None,
                created_at=datetime.now(UTC),
                agent_id=entry.agent_id,
            )
            saved_id = await self._storage.save(memory, vec)
        except Exception:
            # Re-insert so the caller can retry; entry TTL is still valid
            self._pending[pending_id] = entry
            raise

        # Supersede related memories if caller chose to replace them
        superseded_ids: list[str] = []
        if supersedes:
            for old_id in supersedes:
                old_mem = await self._storage.get(old_id)
                if old_mem is not None:
                    await self._storage.delete(old_id)
                    superseded_ids.append(old_id)

        self._cleanup_private_file(entry)
        result: dict = {"status": "saved", "id": saved_id, "distilled": final_text}
        if superseded_ids:
            result["superseded"] = superseded_ids
        return result

    @staticmethod
    def _weibull_recency(age_days: int, memory_type: str) -> float:
        """Weibull survival function: S(t) = exp(-(t/λ)^k).

        Returns 1.0 for fresh memories, decays toward 0 at type-specific rates.
        """
        scale, shape = WEIBULL_PARAMS.get(memory_type, WEIBULL_DEFAULT)
        if age_days <= 0:
            return 1.0
        return math.exp(-((age_days / scale) ** shape))

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

        # Rerank step (optional, typically GCP-only)
        if self._reranker is not None and results:
            docs = [r.memory.content for r in results]
            reranked = await self._reranker.rerank(query, docs, top_k)
            reranked_results = []
            for orig_idx, score in reranked:
                r = results[orig_idx]
                r.score = score
                reranked_results.append(r)
            results = reranked_results

        # Weibull recency boost — type-aware decay
        now = datetime.now(UTC)
        for r in results:
            age_days = (now - r.memory.created_at).days
            recency = self._weibull_recency(age_days, r.memory.type)
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

        if block := self._require_write():
            return block

        old = await self._storage.get(id)
        if not old:
            return {"status": "not_found"}

        # Pre-distillation secret/PII scan — redact before Ollama sees it
        if self._scanner is not None:
            raw_text, _ = self._scanner.redact(raw_text)

        if self._distill_enabled:
            distilled = await self._distiller.distill(raw_text)
        else:
            distilled = raw_text

        # Post-distillation secret scan — hard block if LLM leaked secrets
        if self._scanner is not None and self._scanner.has_secrets(distilled):
            return {
                "status": "blocked",
                "reason": "Distilled output contained potential secrets. Nothing was saved.",
            }

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
        if block := self._require_write():
            return block

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
