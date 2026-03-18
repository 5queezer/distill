"""RerankerPort implementation — Jina Reranker API."""

from __future__ import annotations

import httpx


class JinaReranker:
    """Reranks via Jina Reranker API. Implements RerankerPort."""

    def __init__(
        self,
        api_key: str,
        model: str = "jina-reranker-v2-base-multilingual",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.jina.ai/v1/rerank",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "query": query,
                        "documents": documents,
                        "top_n": top_n,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                results = resp.json()["results"]
                return [(r["index"], r["relevance_score"]) for r in results]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Jina reranking failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                "Jina Reranker API is not reachable at https://api.jina.ai"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Jina reranking request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Jina reranking response format: {e}") from e
