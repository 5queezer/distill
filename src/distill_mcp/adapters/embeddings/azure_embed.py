"""EmbeddingPort implementation — Azure OpenAI text embeddings."""

from __future__ import annotations

import httpx


class AzureOpenAIEmbedder:
    """Embeds text via Azure OpenAI embeddings API. Implements EmbeddingPort."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str = "text-embedding-3-small",
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._deployment = deployment

    async def embed(self, text: str) -> list[float]:
        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/embeddings?api-version=2024-06-01"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"api-key": self._api_key},
                    json={"input": text, "dimensions": 768},
                    timeout=30.0,
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Azure OpenAI embedding failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                f"Azure OpenAI is not reachable at {self._endpoint}"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Azure OpenAI embedding request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected Azure OpenAI embedding response format: {e}"
            ) from e
