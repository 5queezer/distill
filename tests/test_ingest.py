"""Ingest endpoint — POST /observe appends to JSONL and signals worker."""

from __future__ import annotations

import asyncio
import json

import pytest

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


async def test_rejects_non_string_input(client):
    resp = await client.post(
        "/observe",
        json={"tool_name": "Bash", "input": {"nested": "dict"}, "output": "ok"},
    )
    assert resp.status == 400


async def test_truncates_oversized_fields(client, jsonl_path):
    long_output = "x" * 20000
    await client.post(
        "/observe",
        json={"tool_name": "Bash", "input": "cmd", "output": long_output},
    )
    lines = jsonl_path.read_text().strip().split("\n")
    entry = json.loads(lines[0])
    assert len(entry["output"]) == 8000


async def test_newlines_in_fields_produce_single_jsonl_line(client, jsonl_path):
    await client.post(
        "/observe",
        json={"tool_name": "Bash", "input": "echo\nhi", "output": "line1\nline2"},
    )
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert "\n" in entry["input"]
