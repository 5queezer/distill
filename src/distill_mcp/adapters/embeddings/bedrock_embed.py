"""EmbeddingPort implementation — AWS Bedrock Titan text embeddings."""

from __future__ import annotations

import json

import httpx


class BedrockEmbedder:
    """Embeds text via AWS Bedrock Titan Embed v2. Implements EmbeddingPort."""

    def __init__(
        self,
        region: str,
        model: str = "amazon.titan-embed-text-v2:0",
    ) -> None:
        self._region = region
        self._model = model

    async def embed(self, text: str) -> list[float]:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.session import Session

        try:
            session = Session()
            credentials = session.get_credentials()
            if credentials is None:
                raise RuntimeError(
                    "AWS credentials not found — configure via environment, "
                    "~/.aws/credentials, or IAM role"
                )
            credentials = credentials.get_frozen_credentials()
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"AWS credential resolution failed: {e}") from e

        url = (
            f"https://bedrock-runtime.{self._region}.amazonaws.com"
            f"/model/{self._model}/invoke"
        )
        body = json.dumps({"inputText": text, "dimensions": 768, "normalize": True})

        aws_request = AWSRequest(
            method="POST",
            url=url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        SigV4Auth(credentials, "bedrock", self._region).add_auth(aws_request)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    content=body,
                    headers=dict(aws_request.headers),
                    timeout=30.0,
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Bedrock embedding failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                f"Bedrock is not reachable at bedrock-runtime.{self._region}.amazonaws.com"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Bedrock embedding request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected Bedrock embedding response format: {e}"
            ) from e
