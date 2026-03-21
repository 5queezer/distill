"""Unit tests for the Gemini distiller adapter.

All network calls are mocked — no API key required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from distill_mcp.adapters.distiller.gemini_distill import GeminiDistiller

pytestmark = pytest.mark.asyncio


# -- Construction --


def test_default_model() -> None:
    d = GeminiDistiller(api_key="test-key")
    assert d._model == "gemini-2.0-flash"


def test_custom_model() -> None:
    d = GeminiDistiller(api_key="test-key", model="gemini-2.0-flash-lite")
    assert d._model == "gemini-2.0-flash-lite"


# -- Helpers --


def _mock_async_client(*, post_return=None, post_side_effect=None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_client.post = AsyncMock(return_value=post_return)
    return mock_client


def _gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


# -- Happy path --


async def test_distill_returns_text() -> None:
    distiller = GeminiDistiller(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _gemini_response(
        "PostgreSQL was migrated to version 16 in 2026-03."
    )

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        result = await distiller.distill("I upgraded postgres to 16 yesterday")

    assert "PostgreSQL" in result
    assert "version 16" in result

    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "gemini-2.0-flash" in url
    assert "key=test-key" in url

    body = call_args[1]["json"]
    assert "systemInstruction" in body
    assert body["contents"][0]["role"] == "user"


async def test_distill_strips_whitespace() -> None:
    distiller = GeminiDistiller(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _gemini_response("  result with spaces  \n")

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        result = await distiller.distill("test input")

    assert result == "result with spaces"


# -- HTTP errors --


async def test_http_error_raises_runtime_error() -> None:
    distiller = GeminiDistiller(api_key="test-key")

    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_client = _mock_async_client(
        post_side_effect=httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )
    )

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini distillation failed: HTTP 429"):
            await distiller.distill("test")


async def test_connect_error_raises_runtime_error() -> None:
    distiller = GeminiDistiller(api_key="test-key")
    mock_client = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini API is not reachable"):
            await distiller.distill("test")


async def test_timeout_raises_runtime_error() -> None:
    distiller = GeminiDistiller(api_key="test-key")
    mock_client = _mock_async_client(post_side_effect=httpx.ReadTimeout("timed out"))

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini distillation request failed"):
            await distiller.distill("test")


# -- Malformed response --


async def test_malformed_response_raises_runtime_error() -> None:
    distiller = GeminiDistiller(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"candidates": []}

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.distiller.gemini_distill.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Unexpected Gemini response"):
            await distiller.distill("test")
