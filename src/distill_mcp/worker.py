"""Background distillation worker — reads observation JSONL, runs pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MIN_CONTENT_LENGTH, NOISE_PATTERNS

if TYPE_CHECKING:
    from distill_mcp.domain.ports import (
        DistillerPort,
        EmbeddingPort,
        ScannerPort,
        StoragePort,
    )

logger = structlog.get_logger()

MAX_RETRIES = 3


class ObservationWorker:
    """Consumes observation entries from JSONL and saves distilled memories."""

    def __init__(
        self,
        *,
        jsonl_path: Path,
        cursor_path: Path,
        wake_event: asyncio.Event,
        distiller: DistillerPort,
        embedder: EmbeddingPort,
        storage: StoragePort,
        scanner: ScannerPort | None = None,
        distill_enabled: bool = True,
        max_memory_size: int = 8000,
    ) -> None:
        self._jsonl_path = jsonl_path
        self._cursor_path = cursor_path
        self._wake_event = wake_event
        self._distiller = distiller
        self._embedder = embedder
        self._storage = storage
        self._scanner = scanner
        self._distill_enabled = distill_enabled
        self._max_memory_size = max_memory_size
        self._failed: dict[int, int] = {}  # line_offset -> retry_count

    def _read_cursor(self) -> int:
        """Read the last processed line offset from cursor file."""
        if self._cursor_path.exists():
            try:
                return int(self._cursor_path.read_text().strip())
            except (ValueError, OSError):
                return 0
        return 0

    def _write_cursor(self, offset: int) -> None:
        """Persist the cursor to disk."""
        self._cursor_path.write_text(str(offset))

    def _format_observation(self, entry: dict) -> str:
        """Convert a JSONL entry into text suitable for distillation."""
        tool = entry.get("tool_name", "unknown")
        inp = entry.get("input", "")
        out = entry.get("output", "")
        return f"[{tool}] Input: {inp}\nOutput: {out}"

    @staticmethod
    def _is_noise(text: str) -> bool:
        """Return True if the observation text is too short or trivial."""
        stripped = text.strip()
        if len(stripped) < MIN_CONTENT_LENGTH:
            return True
        return stripped.lower() in NOISE_PATTERNS

    async def _process_entry(self, entry: dict) -> bool:
        """Process a single observation. Returns True if saved, False if skipped."""
        # Noise check on the raw output — the formatted string is always longer
        # due to the tool prefix, so checking the output field is more meaningful.
        raw_output = entry.get("output", "")
        if self._is_noise(raw_output):
            return False

        text = self._format_observation(entry)

        if self._is_noise(text):
            return False

        if len(text) > self._max_memory_size:
            text = text[: self._max_memory_size]

        # Pre-distillation scan
        if self._scanner is not None:
            text, _ = self._scanner.redact(text)

        # Distill
        if self._distill_enabled:
            distilled = await self._distiller.distill(text)
        else:
            distilled = text

        if "no_factual_content" in distilled.lower().replace(" ", "_"):
            return False

        # Post-distillation scan
        if self._scanner is not None and self._scanner.has_secrets(distilled):
            logger.warning("observation_blocked", reason="secrets in distilled output")
            return False

        # Embed
        vec = await self._embedder.embed(distilled)

        # Dedup
        existing_id = await self._storage.check_duplicate(vec)
        if existing_id:
            logger.debug("observation_duplicate", existing_id=existing_id)
            return False

        # Save
        memory = Memory(
            id=uuid4().hex,
            content=distilled,
            type="context",  # auto-observed memories default to context type
            repos=[],
            tags=["auto-observed"],
            author=None,
            created_at=datetime.now(UTC),
        )
        await self._storage.save(memory, vec)
        logger.debug("observation_saved", id=memory.id, tool=entry.get("tool_name"))
        return True

    async def process_pending(self) -> int:
        """Process all unprocessed JSONL entries. Returns count of saved memories."""
        if not self._jsonl_path.exists():
            return 0

        cursor = self._read_cursor()
        saved_count = 0

        with self._jsonl_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f):
                if line_num < cursor:
                    continue

                line = line.strip()
                if not line:
                    cursor = line_num + 1
                    continue

                # Skip poison entries
                if self._failed.get(line_num, 0) >= MAX_RETRIES:
                    cursor = line_num + 1
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("invalid_jsonl_entry", line_num=line_num)
                    cursor = line_num + 1
                    continue

                try:
                    if await self._process_entry(entry):
                        saved_count += 1
                    cursor = line_num + 1
                except Exception:
                    self._failed[line_num] = self._failed.get(line_num, 0) + 1
                    logger.warning(
                        "observation_processing_failed",
                        line_num=line_num,
                        retry_count=self._failed[line_num],
                        exc_info=True,
                    )
                    # Don't advance cursor — will retry on next process_pending
                    break

        self._write_cursor(cursor)
        return saved_count

    async def run_forever(self) -> None:
        """Main loop — wait for wake signal, process pending entries."""
        logger.info("observation_worker_started")
        while True:
            await self._wake_event.wait()
            self._wake_event.clear()
            try:
                count = await self.process_pending()
                if count > 0:
                    logger.info("observations_processed", saved=count)
            except Exception:
                logger.error("observation_worker_error", exc_info=True)
