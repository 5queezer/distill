"""EmbeddingPort implementation — local Ollama embeddings."""

from __future__ import annotations

import httpx


class OllamaEmbedder:
    """Embeds text via a local Ollama model. Implements EmbeddingPort."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ) -> None:
        self._host = host
        self._model = model

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._host}/api/embed",
                json={"model": self._model, "input": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"][0]
