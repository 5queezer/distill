"""Unit tests for the Azure OpenAI embedding adapter.

All network calls are mocked — no Azure credentials required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from distill_mcp.adapters.embeddings.azure_embed import AzureOpenAIEmbedder

pytestmark = pytest.mark.asyncio


# -- Construction --


def test_default_deployment() -> None:
    e = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )
    assert e._endpoint == "https://myinstance.openai.azure.com"
    assert e._api_key == "key123"
    assert e._deployment == "text-embedding-3-small"


def test_custom_deployment() -> None:
    e = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
        deployment="custom-deploy",
    )
    assert e._deployment == "custom-deploy"


def test_endpoint_trailing_slash_stripped() -> None:
    e = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com/",
        api_key="key123",
    )
    assert e._endpoint == "https://myinstance.openai.azure.com"


# -- Helpers --


def _mock_async_client(*, post_return=None, post_side_effect=None) -> MagicMock:
    """Build a mock httpx.AsyncClient that works with `async with`."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_client.post = AsyncMock(return_value=post_return)
    return mock_client


def _azure_response(embedding: list[float]) -> dict:
    return {
        "data": [{"embedding": embedding, "index": 0}],
        "model": "text-embedding-3-small",
    }


# -- Happy path --


async def test_embed_calls_correct_url() -> None:
    embedder = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )
    fake_vec = [0.1] * 768

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _azure_response(fake_vec)

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.embeddings.azure_embed.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value = mock_client
        result = await embedder.embed("hello world")

    assert result == fake_vec

    # Verify URL
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "myinstance.openai.azure.com" in url
    assert "text-embedding-3-small" in url
    assert "api-version=2024-06-01" in url

    # Verify auth header
    headers = call_args[1]["headers"]
    assert headers["api-key"] == "key123"

    # Verify request body
    body = call_args[1]["json"]
    assert body == {"input": "hello world", "dimensions": 768}


# -- HTTP errors --


async def test_http_error_raises_runtime_error() -> None:
    embedder = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )

    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_client = _mock_async_client(
        post_side_effect=httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )
    )

    with patch(
        "distill_mcp.adapters.embeddings.azure_embed.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value = mock_client

        with pytest.raises(
            RuntimeError, match="Azure OpenAI embedding failed: HTTP 401"
        ):
            await embedder.embed("test")


async def test_connect_error_raises_runtime_error() -> None:
    embedder = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )
    mock_client = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))

    with patch(
        "distill_mcp.adapters.embeddings.azure_embed.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Azure OpenAI is not reachable"):
            await embedder.embed("test")


async def test_timeout_raises_runtime_error() -> None:
    embedder = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )
    mock_client = _mock_async_client(post_side_effect=httpx.ReadTimeout("timed out"))

    with patch(
        "distill_mcp.adapters.embeddings.azure_embed.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Azure OpenAI embedding request failed"):
            await embedder.embed("test")


# -- Malformed response --


async def test_malformed_response_raises_runtime_error() -> None:
    embedder = AzureOpenAIEmbedder(
        endpoint="https://myinstance.openai.azure.com",
        api_key="key123",
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": []}  # missing embedding

    mock_client = _mock_async_client(post_return=mock_resp)

    with patch(
        "distill_mcp.adapters.embeddings.azure_embed.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client_cls.return_value = mock_client

        with pytest.raises(
            RuntimeError, match="Unexpected Azure OpenAI embedding response"
        ):
            await embedder.embed("test")
