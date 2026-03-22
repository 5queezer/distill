# Auto-Observe Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the explicit `remember`/`confirm_memory` MCP tools with automatic background observation capture via Claude Code hooks, achieving zero-latency memory saves with 100% capture rate.

**Architecture:** A `PostToolUse` Claude Code hook POSTs tool I/O to a localhost HTTP endpoint (`/observe`) inside the distill process. The endpoint appends to a JSONL queue file and signals a background asyncio worker that processes entries through the existing distill→embed→dedup→save pipeline.

**Tech Stack:** aiohttp (HTTP server), asyncio (worker task), existing distill pipeline (DistillerPort, EmbeddingPort, StoragePort, ScannerPort)

**Design doc:** `docs/design/auto-observe.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/distill_mcp/ingest.py` | HTTP `/observe` endpoint — append JSONL, signal worker, return 202 |
| Create | `src/distill_mcp/worker.py` | Background asyncio task — read JSONL entries, run distill pipeline |
| Create | `tests/test_ingest.py` | Unit tests for `/observe` endpoint |
| Create | `tests/test_worker.py` | Unit tests for background worker |
| Create | `tests/test_auto_observe_integration.py` | Integration test: POST → JSONL → worker → searchable memory |
| Modify | `src/distill_mcp/settings.py:47` | Add `ingest_port` setting |
| Modify | `src/distill_mcp/server.py:18-164` | Remove `remember`/`confirm_memory` tools, update instructions |
| Modify | `src/distill_mcp/domain/services.py:75-428` | Remove `remember`/`confirm_memory` methods, `_PendingEntry`, preview logic |
| Modify | `src/distill_mcp/__main__.py:32-157` | Start HTTP server + worker alongside MCP stdio loop |
| Delete | `tests/test_remember_flow.py` | Tests for removed `remember` method |
| Delete | `tests/test_preview_flow.py` | Tests for removed preview/confirm flow |
| Delete | `tests/test_contradiction.py` | Tests for removed preview-based contradiction detection |

---

### Task 1: Add `ingest_port` setting

**Files:**
- Modify: `src/distill_mcp/settings.py:47`
- Test: manual — setting loads from env

- [ ] **Step 1: Add the setting**

In `src/distill_mcp/settings.py`, add to the `Settings` class after line 51 (`auth_enabled`):

```python
    ingest_port: int = 21746  # Local HTTP port for /observe endpoint
```

- [ ] **Step 2: Verify setting loads**

Run: `cd /home/christian/Projects/distill && python -c "from distill_mcp.settings import settings; print(settings.ingest_port)"`
Expected: `21746`

- [ ] **Step 3: Commit**

```bash
git add src/distill_mcp/settings.py
git commit -m "feat: add INGEST_PORT setting for auto-observe endpoint"
```

---

### Task 2: Create the ingest HTTP endpoint

**Files:**
- Create: `src/distill_mcp/ingest.py`
- Create: `tests/test_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest.py`:

```python
"""Ingest endpoint — POST /observe appends to JSONL and signals worker."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient

from distill_mcp.ingest import create_ingest_app


pytestmark = pytest.mark.asyncio


@pytest.fixture
def jsonl_path(tmp_path):
    return tmp_path / "observations.jsonl"


@pytest.fixture
def wake_event():
    return asyncio.Event()


@pytest.fixture
async def client(aiohttp_client, jsonl_path, wake_event):
    app = create_ingest_app(jsonl_path, wake_event)
    return await aiohttp_client(app)


async def test_post_observe_returns_202(client, jsonl_path):
    resp = await client.post(
        "/observe",
        json={"tool_name": "Bash", "input": "ls", "output": "file.py"},
    )
    assert resp.status == 202


async def test_post_observe_appends_jsonl(client, jsonl_path):
    await client.post(
        "/observe",
        json={"tool_name": "Read", "input": "/foo.py", "output": "contents"},
    )
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool_name"] == "Read"
    assert "timestamp" in entry


async def test_post_observe_signals_wake_event(client, wake_event):
    assert not wake_event.is_set()
    await client.post(
        "/observe",
        json={"tool_name": "Bash", "input": "echo hi", "output": "hi"},
    )
    assert wake_event.is_set()


async def test_post_observe_multiple_appends(client, jsonl_path):
    for i in range(3):
        await client.post(
            "/observe",
            json={"tool_name": "Bash", "input": f"cmd-{i}", "output": f"out-{i}"},
        )
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 3


async def test_post_observe_rejects_empty_body(client):
    resp = await client.post("/observe", json={})
    assert resp.status == 400


async def test_get_observe_returns_405(client):
    resp = await client.get("/observe")
    assert resp.status == 405
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'distill_mcp.ingest'`

- [ ] **Step 3: Write the ingest module**

Create `src/distill_mcp/ingest.py`:

```python
"""HTTP /observe endpoint — receives tool observations, appends to JSONL queue."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from aiohttp import web

logger = structlog.get_logger()


def create_ingest_app(
    jsonl_path: Path,
    wake_event: asyncio.Event,
) -> web.Application:
    """Create an aiohttp app with a single POST /observe route."""
    app = web.Application()
    app["jsonl_path"] = jsonl_path
    app["wake_event"] = wake_event
    app.router.add_post("/observe", _handle_observe)
    return app


async def _handle_observe(request: web.Request) -> web.Response:
    """Append observation to JSONL and signal the worker."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return web.Response(status=400, text="Invalid JSON")

    if not body.get("tool_name"):
        return web.Response(status=400, text="Missing tool_name")

    entry = {
        "tool_name": body.get("tool_name", ""),
        "input": body.get("input", ""),
        "output": body.get("output", ""),
        "timestamp": datetime.now(UTC).isoformat(),
        "retry_count": 0,
    }

    jsonl_path: Path = request.app["jsonl_path"]
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    wake_event: asyncio.Event = request.app["wake_event"]
    wake_event.set()

    logger.debug("observation_queued", tool=entry["tool_name"])
    return web.Response(status=202, text="Accepted")
```

- [ ] **Step 4: Add aiohttp dependencies**

Run: `cd /home/christian/Projects/distill && uv add aiohttp && uv add --dev pytest-aiohttp`

Both are required: `aiohttp` for the ingest HTTP server, `pytest-aiohttp` for the `aiohttp_client` test fixture used in all ingest tests.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/test_ingest.py -v`
Expected: all 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/distill_mcp/ingest.py tests/test_ingest.py pyproject.toml uv.lock
git commit -m "feat: add /observe HTTP ingest endpoint"
```

---

### Task 3: Create the background worker

**Files:**
- Create: `src/distill_mcp/worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worker.py`:

```python
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
    worker, storage, _, wake = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(jsonl_path, "Bash", "git status", "On branch main\nnothing to commit")

    processed = await worker.process_pending()
    assert processed == 1
    assert len(storage.saved) == 1


async def test_worker_processes_multiple_entries(tmp_path):
    worker, storage, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    for i in range(5):
        _write_entry(jsonl_path, "Bash", f"command-{i}", f"output-{i} with enough content to pass noise filter")

    processed = await worker.process_pending()
    assert processed == 5
    assert len(storage.saved) == 5


async def test_worker_skips_noise(tmp_path):
    worker, storage, distiller, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    # Short output that should be filtered as noise
    _write_entry(jsonl_path, "Bash", "echo hi", "hi")

    processed = await worker.process_pending()
    assert processed == 0
    assert distiller.call_count == 0


async def test_worker_cursor_persists(tmp_path):
    worker, storage, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(jsonl_path, "Bash", "first command", "first output with enough content to pass noise filter")

    await worker.process_pending()
    assert len(storage.saved) == 1

    # Add more entries and process again — should only process new ones
    _write_entry(jsonl_path, "Bash", "second command", "second output with enough content to pass noise filter")
    await worker.process_pending()
    assert len(storage.saved) == 2


async def test_worker_cursor_survives_restart(tmp_path):
    worker1, storage1, _, _ = _make_worker(tmp_path)
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(jsonl_path, "Bash", "first command", "first output with enough content to pass noise filter")
    await worker1.process_pending()

    # Create a new worker (simulating restart) with same paths
    worker2, storage2, _, _ = _make_worker(tmp_path, storage=FakeStorage())
    _write_entry(jsonl_path, "Bash", "second command", "second output with enough content to pass noise filter")
    await worker2.process_pending()

    # Should only process the second entry
    assert len(storage2.saved) == 1


async def test_worker_handles_poison_entry(tmp_path):
    """Entries that fail 3 times are skipped."""

    class FailingDistiller:
        async def distill(self, raw_text: str) -> str:
            raise RuntimeError("distillation failed")

    worker, storage, _, _ = _make_worker(
        tmp_path, distiller=FailingDistiller()
    )
    jsonl_path = tmp_path / "observations.jsonl"
    _write_entry(jsonl_path, "Bash", "bad command", "bad output with enough content to pass noise filter")

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
    _write_entry(jsonl_path, "Bash", "same command", "same output with enough content to pass noise filter")
    _write_entry(jsonl_path, "Bash", "same command", "same output with enough content to pass noise filter")

    await worker.process_pending()
    assert len(storage.saved) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/test_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'distill_mcp.worker'`

- [ ] **Step 3: Write the worker module**

Create `src/distill_mcp/worker.py`:

```python
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
        # Check if the output portion is trivial (exact match, consistent with MemoryService)
        if stripped.lower() in NOISE_PATTERNS:
            return True
        return False

    async def _process_entry(self, entry: dict) -> bool:
        """Process a single observation. Returns True if saved, False if skipped."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/test_worker.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/distill_mcp/worker.py tests/test_worker.py
git commit -m "feat: add background observation worker"
```

---

### Task 4: Remove `remember` and `confirm_memory` from server.py

**Files:**
- Modify: `src/distill_mcp/server.py:18-164`

- [ ] **Step 1: Update MCP instructions**

Replace the `instructions` string in `server.py` (lines 20-50) with:

```python
    instructions="""\
## Searching Memory

Memories are captured automatically from your tool usage — you don't need to save them.

Use `search_memory` proactively before proposing architecture, creating files,
refactoring, or answering "how should we..." questions.

Also search when the user says: "we decided", "last time", "previously",
"remember when", "what's our pattern for".

Use `update_memory` to correct outdated memories and `forget` to remove stale ones.
""",
```

- [ ] **Step 2: Remove `remember` and `confirm_memory` tool functions**

Delete the `remember` function (lines 82-135) and `confirm_memory` function (lines 138-164) from `server.py`. Also remove the `detect_repo` helper (lines 66-79) since it was only used by `remember`.

- [ ] **Step 3: Update module docstring**

Change line 1 from:
```python
"""MCP server — thin adapter exposing 8 tools + 1 prompt. No business logic here."""
```
to:
```python
"""MCP server — thin adapter exposing 7 tools + 1 prompt. No business logic here."""
```

- [ ] **Step 4: Run existing tests to check nothing else broke**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama and not remember_flow and not preview_flow and not contradiction" --no-cov`
Expected: all remaining tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/distill_mcp/server.py
git commit -m "feat: remove remember/confirm_memory tools, update MCP instructions"
```

---

### Task 5: Remove `remember` and `confirm_memory` from MemoryService

**Files:**
- Modify: `src/distill_mcp/domain/services.py:75-428`

- [ ] **Step 1: Remove dead code from services.py**

Remove these from `MemoryService`:

1. The `_PendingEntry` dataclass (lines 75-87)
2. The `PENDING_TTL` constant (line 72)
3. `MemoryService.__init__` parameters: `preview_enabled`, `preview_ttl_seconds`, `private_dir` and their corresponding `self._` attributes (lines 136-137, 148-150, 156)
4. `MemoryService._pending` dict (line 156)
5. `MemoryService._cleanup_private_file` static method (lines 175-184)
6. `MemoryService._prune_expired` method (lines 186-194)
7. `MemoryService._require_write` method (lines 196-203) — keep this, it's used by `update` and `forget`
8. `MemoryService._find_related_info` method (lines 205-225) — remove, was only used by `remember`
9. `MemoryService.remember` method (lines 227-349)
10. `MemoryService.confirm_memory` method (lines 351-428)

Update the class docstring (line 127) from:
```python
"""Core use cases: remember, search, get, update, list_recent, forget, confirm_memory."""
```
to:
```python
"""Core use cases: search, get, update, list_recent, forget."""
```

- [ ] **Step 2: Remove unused imports**

Remove the `os` import (line 8) — was only used by `remember` for private file writing. Keep `Path` in typing if still used.

- [ ] **Step 3: Run tests**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama and not remember_flow and not preview_flow and not contradiction" --no-cov`
Expected: all remaining tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/distill_mcp/domain/services.py
git commit -m "refactor: remove remember/confirm_memory from MemoryService"
```

---

### Task 6: Remove obsolete tests

**Files:**
- Delete: `tests/test_remember_flow.py`
- Delete: `tests/test_preview_flow.py`
- Delete: `tests/test_contradiction.py`

- [ ] **Step 1: Delete the test files**

```bash
cd /home/christian/Projects/distill
git rm tests/test_remember_flow.py tests/test_preview_flow.py tests/test_contradiction.py
```

- [ ] **Step 2: Run full test suite to confirm nothing references removed code**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama" --no-cov`
Expected: all tests PASS. Note any tests in other files that call `remember()` or `confirm_memory()` — those need updating too.

- [ ] **Step 3: Fix any broken tests that still reference `remember`/`confirm_memory`**

These files call `svc.remember()` and **will break** when the method is removed:

- `tests/test_security.py` — calls `.remember()` for scanner integration tests
- `tests/test_privacy.py` — calls `.remember()` for privacy flow tests
- `tests/test_agent_id.py` — calls `.remember()` for agent filtering tests
- `tests/test_search_quality.py` — calls `.remember()` 6 times to populate test data
- `tests/test_memory_levels.py` — calls `.remember()` 2 times for level derivation tests
- `tests/test_auth_rls.py` — calls `.remember()` 4 times for RLS tests
- `tests/test_access_reinforcement.py` — may call `.remember()` for access count tests

For each file: either rewrite the test to populate storage directly via `FakeStorage.save()` (for tests that just need data in the DB), or rewrite to test the worker pipeline instead (for tests that specifically test the save flow). Tests that only verify search/update/forget behavior and use `remember()` just for setup should switch to direct storage insertion.

- [ ] **Step 4: Commit**

```bash
git add -u tests/
git commit -m "test: remove obsolete remember/confirm/contradiction tests"
```

---

### Task 7: Wire ingest + worker into `__main__.py`

**Files:**
- Modify: `src/distill_mcp/__main__.py:32-157`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_auto_observe_integration.py`:

```python
"""Integration test — POST /observe -> JSONL -> worker -> searchable memory."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

    # Set up ingest
    app = create_ingest_app(jsonl_path, wake_event)
    client = await aiohttp_client(app)

    # Set up worker
    worker = ObservationWorker(
        jsonl_path=jsonl_path,
        cursor_path=cursor_path,
        wake_event=wake_event,
        distiller=FakeDistiller(),
        embedder=FakeEmbedder(),
        storage=storage,
        scanner=FakeScanner(),
    )

    # POST an observation
    resp = await client.post(
        "/observe",
        json={
            "tool_name": "Bash",
            "input": "git log --oneline -5",
            "output": "abc123 feat: add auth middleware\ndef456 fix: handle null tokens",
        },
    )
    assert resp.status == 202

    # Worker processes it
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

    # Burst 20 observations
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
```

- [ ] **Step 2: Run integration test to verify it passes**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/test_auto_observe_integration.py -v`
Expected: PASS (this tests ingest + worker together, no __main__ changes needed yet)

- [ ] **Step 3: Modify `__main__.py` to start ingest + worker**

In `_run_server()`, after `set_service(service)` and before `mcp.run(transport="stdio")`:

```python
    # Start the auto-observe pipeline on the shared event loop
    from aiohttp import web
    from distill_mcp.ingest import create_ingest_app
    from distill_mcp.worker import ObservationWorker

    observe_jsonl = Path(settings.data_dir).expanduser() / "private" / "observations.jsonl"
    observe_cursor = Path(settings.data_dir).expanduser() / "private" / ".cursor"
    wake_event = asyncio.Event()

    worker = ObservationWorker(
        jsonl_path=observe_jsonl,
        cursor_path=observe_cursor,
        wake_event=wake_event,
        distiller=distiller,
        embedder=embedder,
        storage=store,
        scanner=scanner,
        distill_enabled=settings.distill_enabled,
        max_memory_size=settings.max_memory_size,
    )

    ingest_app = create_ingest_app(observe_jsonl, wake_event)

    async def _start_background() -> None:
        """Start ingest HTTP server + worker on the running event loop."""
        runner = web.AppRunner(ingest_app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", settings.ingest_port)
        await site.start()
        logger.info("ingest_server_started", port=settings.ingest_port)
        # Worker runs forever as a background task on this same loop
        asyncio.create_task(worker.run_forever())

    # Hook into the event loop that mcp.run() will create.
    # mcp.run(transport="stdio") calls asyncio.run() internally,
    # so we replace it with explicit control:
    async def _run_all() -> None:
        await _start_background()
        # Run the MCP server — this blocks until stdin closes
        await mcp.run_stdio_async()

    asyncio.run(_run_all())
    return  # Don't call mcp.run() below
```

Note: Add `import structlog` and `logger = structlog.get_logger()` to `__main__.py` for the `logger.info()` call. The plan uses `mcp.run_stdio_async()` which is FastMCP's async entry point. If this method name differs in the installed version, check `dir(mcp)` for the correct async method (e.g., `run_async(transport="stdio")`). The key constraint: ingest server + worker + MCP stdio must share one `asyncio` event loop so the `asyncio.Event` works correctly.

**Threading note:** Per design decision #7, the ingest HTTP server and worker run on the **same asyncio event loop** as the MCP server. `mcp.run(transport="stdio")` internally calls `asyncio.run()`, so we hook into the startup lifecycle to start the ingest server and worker as concurrent tasks on the same loop. The `asyncio.Event` used to signal the worker is safe because all code shares one event loop. We use `mcp.settings.on_duplicate_tools = "warn"` if needed and hook `lifespan` or `startup` events.

The approach: use `aiohttp.web.AppRunner` + `TCPSite` to start the HTTP server as an asyncio task, then start the worker's `run_forever()` as another asyncio task, all before `mcp.run()` takes over. Since FastMCP uses `anyio` internally, we use `mcp.run()` but start background tasks via the MCP app lifecycle.

Alternative if FastMCP doesn't expose lifecycle hooks: wrap the startup in an `async def main()` that starts the ingest site and worker task, then calls `mcp.run()` — or use `asyncio.run()` directly with `mcp.run(transport="stdio")` replaced by explicit server startup.

Also remove the `preview_enabled` and `preview_ttl_seconds` parameters from the `MemoryService(...)` constructor call, and `private_dir` if no longer needed by the service.

- [ ] **Step 4: Remove obsolete settings from `__main__.py` MemoryService construction**

Remove these kwargs from the `MemoryService(...)` call:
- `preview_enabled=settings.preview_enabled`
- `preview_ttl_seconds=settings.preview_ttl_seconds`
- `private_dir=private_dir`

- [ ] **Step 5: Run full test suite**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama" --no-cov`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/distill_mcp/__main__.py tests/test_auto_observe_integration.py
git commit -m "feat: wire ingest server + worker into main entry point"
```

---

### Task 8: Clean up obsolete settings

**Files:**
- Modify: `src/distill_mcp/settings.py:47-49`

- [ ] **Step 1: Remove obsolete settings**

Remove from `Settings` class:
- `preview_enabled: bool = True` (line 48)
- `preview_ttl_seconds: int = 300` (line 49)

- [ ] **Step 2: Run tests**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama" --no-cov`
Expected: PASS. If any test references `settings.preview_enabled`, fix it.

- [ ] **Step 3: Commit**

```bash
git add src/distill_mcp/settings.py
git commit -m "chore: remove obsolete preview settings"
```

---

### Task 9: Update CLAUDE.md files

**Files:**
- Modify: `CLAUDE.md`
- Modify: `src/distill_mcp/CLAUDE.md`
- Modify: `src/distill_mcp/domain/CLAUDE.md`

- [ ] **Step 1: Update root CLAUDE.md**

In `CLAUDE.md`, update the architecture section:
- Change "8 MCP tools" references to "7 MCP tools"
- Update the directory structure to include `ingest.py` and `worker.py`
- Remove `remember` and `confirm_memory` from the "What NOT to do" section references where appropriate
- Add `DISTILL_INGEST_PORT` to any config references

- [ ] **Step 2: Update `src/distill_mcp/CLAUDE.md`**

Update the tool table:
- Remove `remember` and `confirm_memory` rows
- Change "8 MCP tools" to "7 MCP tools"
- Add a note about auto-observe pipeline

- [ ] **Step 3: Update `src/distill_mcp/domain/CLAUDE.md`**

Remove `remember` from the services description. The domain layer no longer has a remember use case.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/distill_mcp/CLAUDE.md src/distill_mcp/domain/CLAUDE.md
git commit -m "docs: update CLAUDE.md files for auto-observe pipeline"
```

---

### Task 10: Verify full test suite and lint

- [ ] **Step 1: Run full test suite**

Run: `cd /home/christian/Projects/distill && uv run pytest tests/ -v -k "not ollama" --no-cov`
Expected: all tests PASS

- [ ] **Step 2: Run linter**

Run: `cd /home/christian/Projects/distill && uv run ruff check . && uv run ruff format --check .`
Expected: no errors

- [ ] **Step 3: Run type checker**

Run: `cd /home/christian/Projects/distill && uvx ty check src/`
Expected: no errors (or only pre-existing ones)

- [ ] **Step 4: Fix any issues found in steps 1-3**

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: address lint/type issues from auto-observe migration"
```
