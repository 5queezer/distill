"""Background worker — reads JSONL, runs distill pipeline, saves memories."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from distill_mcp.worker import ObservationWorker

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output
        self.call_count = 0

    async def distill(self, raw_text: str) -> str:
        self.call_count += 1
        return self._output


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def check_duplicate(self, vec, threshold=0.95):
        return None

    async def save(self, memory, vec, **kw):
        self.saved.append(memory)
        return memory.id

    async def get(self, id):
        return None

    async def delete(self, id):
        pass

    async def find_related(self, vec, **kw):
        return []


class FakeScanner:
    def redact(self, text):
        return text, []

    def has_secrets(self, text):
        return False


def _write_entry(jsonl_path: Path, tool_name: str, inp: str, out: str) -> None:
    entry = {
        "tool_name": tool_name,
        "input": inp,
        "output": out,
        "timestamp": datetime.now(UTC).isoformat(),
        "retry_count": 0,
    }
    with jsonl_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _make_worker(
    tmp_path: Path,
    storage: FakeStorage | None = None,
    distiller: FakeDistiller | None = None,
) -> tuple[ObservationWorker, FakeStorage, FakeDistiller, asyncio.Event]:
    storage = storage or FakeStorage()
    distiller = distiller or FakeDistiller()
    wake = asyncio.Event()
    jsonl_path = tmp_path / "observations.jsonl"
    worker = ObservationWorker(
        jsonl_path=jsonl_path,
        cursor_path=tmp_path / ".cursor",
        wake_event=wake,
        distiller=distiller,
        embedder=FakeEmbedder(),
        storage=storage,
        scanner=FakeScanner(),
        distill_enabled=True,
    )
    return worker, storage, distiller, wake


async def test_worker_processes_single_entry(tmp_path):
    worker, storage, _, _wake = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(jsonl_path, "Bash", "git status", "On branch main\nnothing to commit")

    processed = await worker.process_pending()
    assert processed == 1
    assert len(storage.saved) == 1


async def test_worker_processes_multiple_entries(tmp_path):
    worker, storage, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    for i in range(5):
        _write_entry(
            jsonl_path,
            "Bash",
            f"command-{i}",
            f"output-{i} with enough content to pass noise filter",
        )

    processed = await worker.process_pending()
    assert processed == 5
    assert len(storage.saved) == 5


async def test_worker_skips_noise(tmp_path):
    worker, _storage, distiller, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    # Short output that should be filtered as noise
    _write_entry(jsonl_path, "Bash", "echo hi", "hi")

    processed = await worker.process_pending()
    assert processed == 0
    assert distiller.call_count == 0


async def test_worker_cursor_persists(tmp_path):
    worker, storage, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(
        jsonl_path,
        "Bash",
        "first command",
        "first output with enough content to pass noise filter",
    )

    await worker.process_pending()
    assert len(storage.saved) == 1

    # Add more entries and process again — should only process new ones
    _write_entry(
        jsonl_path,
        "Bash",
        "second command",
        "second output with enough content to pass noise filter",
    )
    await worker.process_pending()
    assert len(storage.saved) == 2


async def test_worker_cursor_survives_restart(tmp_path):
    worker1, _storage1, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(
        jsonl_path,
        "Bash",
        "first command",
        "first output with enough content to pass noise filter",
    )
    await worker1.process_pending()

    # Create a new worker (simulating restart) with same paths
    worker2, storage2, _, _ = _make_worker(tmp_path, storage=FakeStorage())
    _write_entry(
        jsonl_path,
        "Bash",
        "second command",
        "second output with enough content to pass noise filter",
    )
    await worker2.process_pending()

    # Should only process the second entry
    assert len(storage2.saved) == 1


async def test_worker_handles_poison_entry(tmp_path):
    """Entries that fail 3 times are skipped."""

    class FailingDistiller:
        async def distill(self, raw_text: str) -> str:
            raise RuntimeError("distillation failed")

    worker, storage, _, _ = _make_worker(tmp_path, distiller=FailingDistiller())
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(
        jsonl_path,
        "Bash",
        "bad command",
        "bad output with enough content to pass noise filter",
    )

    # Process 3 times — entry should be retried then skipped
    for _ in range(3):
        await worker.process_pending()

    # After 3 failures, entry is skipped — no saved memories
    assert len(storage.saved) == 0

    # Fourth process should not retry the poison entry
    await worker.process_pending()
    assert len(storage.saved) == 0


async def test_worker_dedup_rejects_identical(tmp_path):
    """Duplicate observations produce only one memory."""

    class DedupStorage(FakeStorage):
        async def check_duplicate(self, vec, threshold=0.95):
            if self.saved:
                return self.saved[0].id
            return None

    storage = DedupStorage()
    worker, _, _, _ = _make_worker(tmp_path, storage=storage)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(
        jsonl_path,
        "Bash",
        "same command",
        "same output with enough content to pass noise filter",
    )
    _write_entry(
        jsonl_path,
        "Bash",
        "same command",
        "same output with enough content to pass noise filter",
    )

    await worker.process_pending()
    assert len(storage.saved) == 1
