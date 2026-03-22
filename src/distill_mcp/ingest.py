"""HTTP /observe endpoint — receives tool observations, appends to JSONL queue."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from aiohttp import web

logger = structlog.get_logger()


MAX_FIELD_LENGTH = 8000  # Truncate individual fields to match max_memory_size


def create_ingest_app(
    jsonl_path: Path,
    wake_event: asyncio.Event,
) -> web.Application:
    """Create an aiohttp app with a single POST /observe route."""
    app = web.Application(client_max_size=64 * 1024)  # 64 KiB per request
    app["jsonl_path"] = jsonl_path
    app["wake_event"] = wake_event
    app.router.add_post("/observe", _handle_observe)
    return app


async def _handle_observe(request: web.Request) -> web.Response:
    """Append observation to JSONL and signal the worker."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    tool_name = body.get("tool_name", "")
    inp = body.get("input", "")
    out = body.get("output", "")

    # Validate types
    if not isinstance(tool_name, str) or not tool_name:
        return web.Response(status=400, text="Missing tool_name")
    if not isinstance(inp, str) or not isinstance(out, str):
        return web.Response(status=400, text="input and output must be strings")

    entry = {
        "tool_name": tool_name,
        "input": inp[:MAX_FIELD_LENGTH],
        "output": out[:MAX_FIELD_LENGTH],
        "timestamp": datetime.now(UTC).isoformat(),
        "retry_count": 0,
    }

    jsonl_path: Path = request.app["jsonl_path"]
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    wake_event: asyncio.Event = request.app["wake_event"]
    wake_event.set()

    logger.debug("observation_queued", tool=entry["tool_name"])
    return web.Response(status=202, text="Accepted")
