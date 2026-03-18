"""EmbeddingPort implementation — Google Vertex AI text embeddings."""

from __future__ import annotations

import google.auth
import google.auth.transport.requests
import httpx


class VertexEmbedder:
    """Embeds text via Vertex AI text-embedding-005. Implements EmbeddingPort."""

    def __init__(
        self,
        project: str,
        location: str = "us-central1",
        model: str = "text-embedding-005",
    ) -> None:
        self._project = project
        self._location = location
        self._model = model

    async def embed(self, text: str) -> list[float]:
        try:
            credentials, _ = google.auth.default()
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
        except google.auth.exceptions.DefaultCredentialsError as e:
            raise RuntimeError(
                "GCP credentials not found — run `gcloud auth application-default login`"
            ) from e
        except google.auth.exceptions.RefreshError as e:
            raise RuntimeError(f"GCP credential refresh failed: {e}") from e

        url = (
            f"https://{self._location}-aiplatform.googleapis.com/v1/"
            f"projects/{self._project}/locations/{self._location}/"
            f"publishers/google/models/{self._model}:predict"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {credentials.token}"},
                    json={"instances": [{"content": text}]},
                    timeout=30.0,
                )
                resp.raise_for_status()
                return resp.json()["predictions"][0]["embeddings"]["values"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Vertex AI embedding failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                f"Vertex AI is not reachable at {self._location}-aiplatform.googleapis.com"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Vertex AI embedding request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected Vertex AI embedding response format: {e}"
            ) from e
