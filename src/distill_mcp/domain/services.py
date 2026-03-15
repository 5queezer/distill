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

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, SearchResult
    from distill_mcp.domain.ports import (
        DistillerPort,
        EmbeddingPort,
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
RECENCY_HALFLIFE_DAYS = 30
ACCESS_BOOST_WEIGHT = 0.1


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
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._distiller = distiller
        self._distill_enabled = distill_enabled
        self._preview_enabled = preview_enabled
        self._preview_ttl_seconds = preview_ttl_seconds
        self._private_dir = private_dir
        self._scanner = scanner
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._pending: dict[str, _PendingEntry] = {}

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

    async def remember(
        self,
        raw_text: str,
        type: str,
        repos: list[str],
        tags: list[str] | None = None,
    ) -> dict:
        from distill_mcp.domain.models import Memory

        # Prune expired pending entries
        self._prune_expired()

        # 0. Noise filter — reject before wasting Ollama cycles
        noise_reason = self._is_noise(raw_text)
        if noise_reason:
            return {"status": "rejected", "reason": noise_reason}

        # Layer 1: Pre-distillation secret scan — redact before Ollama sees it
        pre_findings: list = []
        if self._scanner is not None:
            raw_text, pre_findings = self._scanner.redact(raw_text)

        # 1. Distill
        if self._distill_enabled:
            distilled = await self._distiller.distill(raw_text)
        else:
            distilled = raw_text

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

        # If preview is disabled, store immediately (old behavior)
        if not self._preview_enabled:
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
            return {
                "status": "saved",
                "id": saved_id,
                "distilled": distilled,
                "redacted_count": len(pre_findings),
            }

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
        )
        return {
            "status": "preview",
            "pending_id": pending_id,
            "distilled": distilled,
            "expires_in_seconds": self._preview_ttl_seconds,
            "redacted_count": len(pre_findings),
        }

    async def confirm_memory(
        self, pending_id: str, override: str | None = None
    ) -> dict:
        from distill_mcp.domain.models import Memory

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
        # override is stored as-is (user-edited text bypasses distillation by design).
        try:
            if override is not None:
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
                author=None,
                created_at=datetime.now(UTC),
            )
            saved_id = await self._storage.save(memory, vec)
        except Exception:
            # Re-insert so the caller can retry; entry TTL is still valid
            self._pending[pending_id] = entry
            raise

        self._cleanup_private_file(entry)
        return {"status": "saved", "id": saved_id, "distilled": final_text}

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

        # Access-frequency boost: frequently retrieved memories score higher
        for r in results:
            access_boost = math.log(r.memory.access_count + 1) * ACCESS_BOOST_WEIGHT
            r.score *= 1.0 + access_boost

        # Hard min score: drop irrelevant results
        results = [r for r in results if r.score >= MIN_SEARCH_SCORE]

        # Re-sort after recency + access adjustment
        results.sort(key=lambda r: r.score, reverse=True)

        # Record access (fire-and-forget, non-blocking)
        for r in results:
            task = asyncio.create_task(self._storage.record_access(r.memory.id))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

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
