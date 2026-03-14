"""Golden-pair tests for the Ollama distiller.

Each test sends raw input and asserts properties of the distilled output.
Requires a running Ollama instance. Set DISTILL_TEST_MODEL to override the model.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest

from distill_mcp.adapters.distiller.ollama_distill import OllamaDistiller

_MODEL = os.environ.get("DISTILL_TEST_MODEL", "gemma3:4b")


def _ollama_available() -> bool:
    try:
        resp = httpx.get("http://localhost:11434/api/version", timeout=2.0)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _ollama_available(), reason="Ollama not running"),
]

FIRST_PERSON = re.compile(r"\b(I|my|me|we|our|us)\b", re.IGNORECASE)


@pytest.fixture
def distiller() -> OllamaDistiller:
    return OllamaDistiller(model=_MODEL)


# 1. First-person removal
async def test_removes_first_person(distiller: OllamaDistiller) -> None:
    raw = "I decided to switch our API gateway from Kong to Envoy because I found Kong's plugin system too limiting."
    out = await distiller.distill(raw)
    assert not FIRST_PERSON.search(out), f"First-person language found: {out}"
    assert "envoy" in out.lower() or "kong" in out.lower()


# 2. Name removal
async def test_removes_names(distiller: OllamaDistiller) -> None:
    raw = "Bob and Alice paired on the fix for the auth token refresh bug in the user-service repo."
    out = await distiller.distill(raw)
    assert "bob" not in out.lower(), f"Name 'Bob' found: {out}"
    assert "alice" not in out.lower(), f"Name 'Alice' found: {out}"
    assert "auth" in out.lower() or "token" in out.lower()


# 3. Emotion removal
async def test_removes_emotion(distiller: OllamaDistiller) -> None:
    raw = "I'm so frustrated with this garbage CI pipeline. It keeps failing randomly and nobody cares enough to fix the flaky Selenium tests."
    out = await distiller.distill(raw)
    for word in ("frustrated", "garbage", "nobody cares"):
        assert word not in out.lower(), f"Emotional language '{word}' found: {out}"


# 4. Vague time → date
async def test_replaces_vague_time(distiller: OllamaDistiller) -> None:
    raw = "Yesterday we deployed the new search indexer to production."
    out = await distiller.distill(raw)
    assert "yesterday" not in out.lower(), (
        f"Vague time 'yesterday' still present: {out}"
    )
    # Should contain a date-like pattern (YYYY-MM-DD or YYYY-MM or month name)
    has_date = bool(
        re.search(r"\d{4}-\d{2}", out) or re.search(r"march|2026", out.lower())
    )
    assert has_date, f"No date-like reference found: {out}"


# 5. Technical decision preserved
async def test_preserves_decision(distiller: OllamaDistiller) -> None:
    raw = "We chose PostgreSQL over MySQL for the analytics service because we need jsonb support and partial indexes."
    out = await distiller.distill(raw)
    assert "postgresql" in out.lower() or "postgres" in out.lower()
    assert "jsonb" in out.lower() or "partial index" in out.lower()


# 6. Error description preserved
async def test_preserves_error_info(distiller: OllamaDistiller) -> None:
    raw = "The worker pod kept getting OOMKilled because the default memory limit was set to 256Mi but the batch job needs at least 1Gi."
    out = await distiller.distill(raw)
    assert "oom" in out.lower() or "memory" in out.lower()
    assert "256" in out or "1gi" in out.lower() or "1 gi" in out.lower()


# 7. Short input → short output
async def test_short_output(distiller: OllamaDistiller) -> None:
    raw = "Switched the logging library from loguru to structlog."
    out = await distiller.distill(raw)
    # Split on sentence-ending punctuation followed by space or end-of-string,
    # avoiding splits inside version numbers like "2.1.3"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", out) if s.strip()]
    assert len(sentences) <= 3, f"Output too long ({len(sentences)} sentences): {out}"


# 8. No factual content
async def test_no_fact_input(distiller: OllamaDistiller) -> None:
    raw = "I'm really tired today and just can't focus on anything."
    out = await distiller.distill(raw)
    assert len(out) < 80 or "no_factual_content" in out.lower().replace(" ", "_"), (
        f"Expected minimal output for non-technical input: {out}"
    )


# 9. Repo name preserved
async def test_preserves_repo_name(distiller: OllamaDistiller) -> None:
    raw = "I pushed a hotfix to the distill-mcp repo to handle the edge case where embeddings return empty vectors."
    out = await distiller.distill(raw)
    assert "distill-mcp" in out.lower() or "distill_mcp" in out.lower()


# 10. Version numbers preserved
async def test_preserves_versions(distiller: OllamaDistiller) -> None:
    raw = "We upgraded from Python 3.11 to Python 3.12 and bumped FastAPI from 0.109 to 0.115 in the payment-service."
    out = await distiller.distill(raw)
    assert "3.12" in out
    assert "0.115" in out or "fastapi" in out.lower()
