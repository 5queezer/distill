"""EmbeddingPort implementation — Google Gemini API text embeddings."""

from __future__ import annotations

import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEmbedder:
    """Embeds text via Google Gemini API. Implements EmbeddingPort."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-004",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def embed(self, text: str) -> list[float]:
        url = f"{API_BASE}/models/{self._model}:embedContent?key={self._api_key}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={
                        "model": f"models/{self._model}",
                        "content": {"parts": [{"text": text}]},
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                return resp.json()["embedding"]["values"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Gemini embedding failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                "Gemini API is not reachable at generativelanguage.googleapis.com"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Gemini embedding request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected Gemini embedding response format: {e}"
            ) from e
