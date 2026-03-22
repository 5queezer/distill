"""Unit tests for the Gemini embedding adapter.

All network calls are mocked — no API key required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from distill_mcp.adapters.embeddings.gemini_embed import GeminiEmbedder

pytestmark = pytest.mark.asyncio


# -- Construction --


def test_default_model() -> None:
    e = GeminiEmbedder(api_key="test-key")
    assert e._model == "gemini-embedding-001"


def test_custom_model() -> None:
    e = GeminiEmbedder(api_key="test-key", model="custom-embed")
    assert e._model == "custom-embed"


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


# -- Happy path --


async def test_embed_returns_vector() -> None:
    embedder = GeminiEmbedder(api_key="test-key")
    fake_vec = [0.1] * 768

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"embedding": {"values": fake_vec}}

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.embeddings.gemini_embed.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        result = await embedder.embed("hello world")

    assert result == fake_vec

    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "gemini-embedding-001" in url
    assert "key=test-key" in url

    body = call_args[1]["json"]
    assert body["content"]["parts"][0]["text"] == "hello world"


# -- HTTP errors --


async def test_http_error_raises_runtime_error() -> None:
    embedder = GeminiEmbedder(api_key="test-key")

    mock_response = MagicMock()
    mock_response.status_code = 403

    mock_client = _mock_async_client(
        post_side_effect=httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )
    )

    with patch(
        "distill_mcp.adapters.embeddings.gemini_embed.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini embedding failed: HTTP 403"):
            await embedder.embed("test")


async def test_connect_error_raises_runtime_error() -> None:
    embedder = GeminiEmbedder(api_key="test-key")
    mock_client = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))

    with patch(
        "distill_mcp.adapters.embeddings.gemini_embed.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini API is not reachable"):
            await embedder.embed("test")


async def test_timeout_raises_runtime_error() -> None:
    embedder = GeminiEmbedder(api_key="test-key")
    mock_client = _mock_async_client(post_side_effect=httpx.ReadTimeout("timed out"))

    with patch(
        "distill_mcp.adapters.embeddings.gemini_embed.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Gemini embedding request failed"):
            await embedder.embed("test")


# -- Malformed response --


async def test_malformed_response_raises_runtime_error() -> None:
    embedder = GeminiEmbedder(api_key="test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"wrong": "format"}

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.embeddings.gemini_embed.httpx.AsyncClient"
    ) as mock_cls:
        mock_cls.return_value = mock_client
        with pytest.raises(RuntimeError, match="Unexpected Gemini embedding response"):
            await embedder.embed("test")
