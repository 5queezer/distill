"""DistillerPort implementation — Google Gemini API (cloud)."""

from __future__ import annotations

from datetime import date

import httpx

from distill_mcp.adapters.distiller.ollama_distill import DISTILL_SYSTEM, DISTILL_USER

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiDistiller:
    """Distills raw text via Google Gemini API. Implements DistillerPort."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def distill(self, raw_text: str) -> str:
        prompt = DISTILL_USER.format(
            today=date.today().isoformat(),
            raw_text=raw_text,
        )
        url = f"{API_BASE}/models/{self._model}:generateContent?key={self._api_key}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={
                        "systemInstruction": {
                            "parts": [{"text": DISTILL_SYSTEM}],
                        },
                        "contents": [
                            {"role": "user", "parts": [{"text": prompt}]},
                        ],
                    },
                    timeout=60.0,
                )
                resp.raise_for_status()
                result = resp.json()["candidates"][0]["content"]["parts"][0][
                    "text"
                ].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Gemini distillation failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                "Gemini API is not reachable at generativelanguage.googleapis.com"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Gemini distillation request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini response format: {e}") from e
        return result
