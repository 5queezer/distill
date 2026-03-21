"""Unit tests for the AWS Bedrock embedding adapter.

All network calls are mocked — no AWS credentials required.
botocore is mocked via sys.modules so the test runs without it installed.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Inject fake botocore modules so the lazy import inside embed() resolves
_botocore = ModuleType("botocore")
_botocore_session = ModuleType("botocore.session")
_botocore_auth = ModuleType("botocore.auth")
_botocore_awsrequest = ModuleType("botocore.awsrequest")

_botocore_session.Session = MagicMock  # type: ignore[attr-defined]
_botocore_auth.SigV4Auth = MagicMock  # type: ignore[attr-defined]
_botocore_awsrequest.AWSRequest = MagicMock  # type: ignore[attr-defined]

_botocore.session = _botocore_session  # type: ignore[attr-defined]
_botocore.auth = _botocore_auth  # type: ignore[attr-defined]
_botocore.awsrequest = _botocore_awsrequest  # type: ignore[attr-defined]

sys.modules.setdefault("botocore", _botocore)
sys.modules.setdefault("botocore.session", _botocore_session)
sys.modules.setdefault("botocore.auth", _botocore_auth)
sys.modules.setdefault("botocore.awsrequest", _botocore_awsrequest)

from distill_mcp.adapters.embeddings.bedrock_embed import BedrockEmbedder  # noqa: E402

pytestmark = pytest.mark.asyncio


# -- Construction --


def test_default_model() -> None:
    e = BedrockEmbedder(region="us-east-1")
    assert e._region == "us-east-1"
    assert e._model == "amazon.titan-embed-text-v2:0"


def test_custom_region_and_model() -> None:
    e = BedrockEmbedder(region="eu-west-1", model="custom-model")
    assert e._region == "eu-west-1"
    assert e._model == "custom-model"


# -- Helpers --


def _fake_credentials() -> MagicMock:
    creds = MagicMock()
    creds.access_key = "AKID"
    creds.secret_key = "secret"
    creds.token = None
    return creds


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


def _patch_botocore(mock_session_cls, mock_client_cls, mock_client):
    """Wire up standard botocore + client mocks."""
    session = MagicMock()
    creds = _fake_credentials()
    session.get_credentials.return_value.get_frozen_credentials.return_value = creds
    mock_session_cls.return_value = session
    mock_client_cls.return_value = mock_client


# -- Happy path --


async def test_embed_calls_correct_url() -> None:
    embedder = BedrockEmbedder(region="us-east-1")
    fake_vec = [0.1] * 768

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"embedding": fake_vec}

    mock_client = _mock_async_client(post_return=mock_resp)

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        patch.object(_botocore_auth, "SigV4Auth"),
        patch.object(_botocore_awsrequest, "AWSRequest"),
        patch(
            "distill_mcp.adapters.embeddings.bedrock_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_botocore(mock_session_cls, mock_client_cls, mock_client)
        result = await embedder.embed("hello world")

    assert result == fake_vec

    # Verify URL
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "bedrock-runtime.us-east-1.amazonaws.com" in url
    assert "amazon.titan-embed-text-v2:0" in url
    assert "/invoke" in url


# -- Credential errors --


async def test_missing_credentials_raises_runtime_error() -> None:
    embedder = BedrockEmbedder(region="us-east-1")

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        pytest.raises(RuntimeError, match="AWS credentials not found"),
    ):
        session = MagicMock()
        session.get_credentials.return_value = None
        mock_session_cls.return_value = session
        await embedder.embed("test")


# -- HTTP errors --


async def test_http_error_raises_runtime_error() -> None:
    embedder = BedrockEmbedder(region="us-east-1")

    mock_response = MagicMock()
    mock_response.status_code = 403

    mock_client = _mock_async_client(
        post_side_effect=httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )
    )

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        patch.object(_botocore_auth, "SigV4Auth"),
        patch.object(_botocore_awsrequest, "AWSRequest"),
        patch(
            "distill_mcp.adapters.embeddings.bedrock_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_botocore(mock_session_cls, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Bedrock embedding failed: HTTP 403"):
            await embedder.embed("test")


async def test_connect_error_raises_runtime_error() -> None:
    embedder = BedrockEmbedder(region="us-east-1")
    mock_client = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        patch.object(_botocore_auth, "SigV4Auth"),
        patch.object(_botocore_awsrequest, "AWSRequest"),
        patch(
            "distill_mcp.adapters.embeddings.bedrock_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_botocore(mock_session_cls, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Bedrock is not reachable"):
            await embedder.embed("test")


async def test_timeout_raises_runtime_error() -> None:
    embedder = BedrockEmbedder(region="us-east-1")
    mock_client = _mock_async_client(post_side_effect=httpx.ReadTimeout("timed out"))

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        patch.object(_botocore_auth, "SigV4Auth"),
        patch.object(_botocore_awsrequest, "AWSRequest"),
        patch(
            "distill_mcp.adapters.embeddings.bedrock_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_botocore(mock_session_cls, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Bedrock embedding request failed"):
            await embedder.embed("test")


# -- Malformed response --


async def test_malformed_response_raises_runtime_error() -> None:
    embedder = BedrockEmbedder(region="us-east-1")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"wrong_key": []}  # missing "embedding"

    mock_client = _mock_async_client(post_return=mock_resp)

    with (
        patch.object(_botocore_session, "Session") as mock_session_cls,
        patch.object(_botocore_auth, "SigV4Auth"),
        patch.object(_botocore_awsrequest, "AWSRequest"),
        patch(
            "distill_mcp.adapters.embeddings.bedrock_embed.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        _patch_botocore(mock_session_cls, mock_client_cls, mock_client)

        with pytest.raises(RuntimeError, match="Unexpected Bedrock embedding response"):
            await embedder.embed("test")
