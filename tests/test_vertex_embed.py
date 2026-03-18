"""Unit tests for the Vertex AI embedding adapter.

All network calls are mocked — no GCP credentials required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

google_auth = pytest.importorskip("google.auth", reason="google-auth not installed")

from distill_mcp.adapters.embeddings.vertex_embed import VertexEmbedder  # noqa: E402

pytestmark = pytest.mark.asyncio


# -- Construction --


def test_default_location_and_model() -> None:
    e = VertexEmbedder(project="my-proj")
    assert e._project == "my-proj"
    assert e._location == "us-central1"
    assert e._model == "text-embedding-005"


def test_custom_location_and_model() -> None:
    e = VertexEmbedder(project="p", location="europe-west1", model="custom-model")
    assert e._location == "europe-west1"
    assert e._model == "custom-model"


# -- Helpers --


def _fake_credentials() -> MagicMock:
    creds = MagicMock()
    creds.token = "fake-token"
    creds.refresh = MagicMock()
    return creds


def _vertex_response(values: list[float]) -> dict:
    return {"predictions": [{"embeddings": {"values": values}}]}


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


def _patch_auth_and_client(mock_default, mock_client_cls, mock_client):
    """Wire up standard auth + client mocks."""
    mock_default.return_value = (_fake_credentials(), "p")
    mock_client_cls.return_value = mock_client


# -- Happy path --


async def test_embed_calls_correct_url() -> None:
    embedder = VertexEmbedder(project="my-proj", location="us-central1")
    fake_vec = [0.1] * 768

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _vertex_response(fake_vec)

    mock_client = _mock_async_client(post_return=mock_resp)

    with (
        patch("google.auth.default") as mock_default,
        patch("google.auth.transport.requests.Request"),
        patch(
            "distill_mcp.adapters.embeddings.vertex_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        mock_default.return_value = (_fake_credentials(), "my-proj")
        mock_client_cls.return_value = mock_client

        result = await embedder.embed("hello world")

    assert result == fake_vec

    # Verify the URL used
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "us-central1-aiplatform.googleapis.com" in url
    assert "my-proj" in url
    assert "text-embedding-005:predict" in url

    # Verify auth header
    headers = call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer fake-token"

    # Verify request body
    body = call_args[1]["json"]
    assert body == {"instances": [{"content": "hello world"}]}


# -- Auth errors --


async def test_missing_credentials_raises_runtime_error() -> None:
    import google.auth.exceptions

    embedder = VertexEmbedder(project="p")

    with (
        patch(
            "google.auth.default",
            side_effect=google.auth.exceptions.DefaultCredentialsError("no creds"),
        ),
        pytest.raises(RuntimeError, match="GCP credentials not found"),
    ):
        await embedder.embed("test")


async def test_refresh_failure_raises_runtime_error() -> None:
    import google.auth.exceptions

    embedder = VertexEmbedder(project="p")
    creds = _fake_credentials()
    creds.refresh.side_effect = google.auth.exceptions.RefreshError("expired")

    with (
        patch(
            "google.auth.default",
            return_value=(creds, "p"),
        ),
        patch("google.auth.transport.requests.Request"),
        pytest.raises(RuntimeError, match="credential refresh failed"),
    ):
        await embedder.embed("test")


# -- HTTP errors --


async def test_http_error_raises_runtime_error() -> None:
    embedder = VertexEmbedder(project="p")

    mock_response = MagicMock()
    mock_response.status_code = 403

    mock_client = _mock_async_client(
        post_side_effect=httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )
    )

    with (
        patch("google.auth.default") as mock_default,
        patch("google.auth.transport.requests.Request"),
        patch(
            "distill_mcp.adapters.embeddings.vertex_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_auth_and_client(mock_default, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Vertex AI embedding failed: HTTP 403"):
            await embedder.embed("test")


async def test_connect_error_raises_runtime_error() -> None:
    embedder = VertexEmbedder(project="p")
    mock_client = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))

    with (
        patch("google.auth.default") as mock_default,
        patch("google.auth.transport.requests.Request"),
        patch(
            "distill_mcp.adapters.embeddings.vertex_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_auth_and_client(mock_default, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Vertex AI is not reachable"):
            await embedder.embed("test")


async def test_timeout_raises_runtime_error() -> None:
    embedder = VertexEmbedder(project="p")
    mock_client = _mock_async_client(post_side_effect=httpx.ReadTimeout("timed out"))

    with (
        patch("google.auth.default") as mock_default,
        patch("google.auth.transport.requests.Request"),
        patch(
            "distill_mcp.adapters.embeddings.vertex_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_auth_and_client(mock_default, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Vertex AI embedding request failed"):
            await embedder.embed("test")


# -- Malformed response --


async def test_malformed_response_raises_runtime_error() -> None:
    embedder = VertexEmbedder(project="p")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"predictions": []}  # missing embeddings

    mock_client = _mock_async_client(post_return=mock_resp)

    with (
        patch("google.auth.default") as mock_default,
        patch("google.auth.transport.requests.Request"),
        patch(
            "distill_mcp.adapters.embeddings.vertex_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_auth_and_client(mock_default, mock_client_cls, mock_client)

        with pytest.raises(
            RuntimeError, match="Unexpected Vertex AI embedding response"
        ):
            await embedder.embed("test")
