"""Integration test — POST /observe -> JSONL -> worker -> memory saved."""

from __future__ import annotations

import asyncio

import pytest

from distill_mcp.ingest import create_ingest_app
from distill_mcp.worker import ObservationWorker

pytestmark = pytest.mark.asyncio


class FakeDistiller:
    async def distill(self, raw_text: str) -> str:
        return "Distilled: " + raw_text[:50]


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self):
        self.saved = []

    async def check_duplicate(self, vec, threshold=0.95):
        return None

    async def save(self, memory, vec, **kw):
        self.saved.append(memory)
        return memory.id

    async def get(self, id):
        return None

    async def find_related(self, vec, **kw):
        return []


class FakeScanner:
    def redact(self, text):
        return text, []

    def has_secrets(self, text):
        return False


async def test_end_to_end_observe_to_save(tmp_path, aiohttp_client):
    """POST to /observe -> JSONL -> worker processes -> memory saved."""
    jsonl_path = tmp_path / "observations.jsonl"
    cursor_path = tmp_path / ".cursor"
    wake_event = asyncio.Event()
    storage = FakeStorage()

    app = create_ingest_app(jsonl_path, wake_event)
    client = await aiohttp_client(app)

    worker = ObservationWorker(
        jsonl_path=jsonl_path,
        cursor_path=cursor_path,
        wake_event=wake_event,
        distiller=FakeDistiller(),
        embedder=FakeEmbedder(),
        storage=storage,
        scanner=FakeScanner(),
    )

    resp = await client.post(
        "/observe",
        json={
            "tool_name": "Bash",
            "input": "git log --oneline -5",
            "output": "abc123 feat: add auth middleware\ndef456 fix: handle null tokens",
        },
    )
    assert resp.status == 202

    count = await worker.process_pending()
    assert count == 1
    assert len(storage.saved) == 1
    assert storage.saved[0].tags == ["auto-observed"]


async def test_burst_of_observations(tmp_path, aiohttp_client):
    """Multiple rapid POSTs all get processed."""
    jsonl_path = tmp_path / "observations.jsonl"
    cursor_path = tmp_path / ".cursor"
    wake_event = asyncio.Event()
    storage = FakeStorage()

    app = create_ingest_app(jsonl_path, wake_event)
    client = await aiohttp_client(app)

    worker = ObservationWorker(
        jsonl_path=jsonl_path,
        cursor_path=cursor_path,
        wake_event=wake_event,
        distiller=FakeDistiller(),
        embedder=FakeEmbedder(),
        storage=storage,
        scanner=FakeScanner(),
    )

    for i in range(20):
        await client.post(
            "/observe",
            json={
                "tool_name": "Read",
                "input": f"/path/to/file_{i}.py",
                "output": f"Content of file {i} with enough text to pass filters and be meaningful",
            },
        )

    count = await worker.process_pending()
    assert count == 20
    assert len(storage.saved) == 20
