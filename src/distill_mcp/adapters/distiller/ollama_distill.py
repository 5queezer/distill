"""DistillerPort implementation — local Ollama, never crosses the network."""

from __future__ import annotations

import os
from datetime import date

import httpx

DISTILL_SYSTEM = """\
You are a privacy-preserving knowledge distiller. Transform raw developer \
input into anonymous, factual team knowledge.

Rules — follow ALL strictly:
1. Remove ALL first-person language (I, we, my, our, me, us). \
Use passive voice or impersonal constructions.
2. Remove ALL people's names. Never include who did something.
3. Remove ALL emotional language — no frustration, blame, excitement, opinions.
4. Replace vague time references with approximate dates based on today's date:
   - "yesterday" → the calendar date before today
   - "last week" → approximate ISO week
   - "last month" → the previous month in YYYY-MM format
   - "recently" → approximate month in YYYY-MM format
5. KEEP: technical facts, decisions with reasons, repo/project names, \
technology names, version numbers, error messages, configuration details.
6. Output exactly 1-3 concise factual sentences. No bullet points, no headers.
7. NEVER add information not present in the input. Do not invent version \
numbers, dates, or details that the input does not mention.
8. Only SOFTWARE ENGINEERING content counts as factual: code changes, \
architecture decisions, bugs, deployments, dependencies, configurations. \
Personal feelings, energy levels, or moods are NOT technical content. \
If the input contains no software engineering content, output ONLY the \
single token: NO_F*[REDACTED]
9. When input is prefixed with [Agent: <id>], you are distilling output \
from that specific agent. Extract only factual knowledge. Strip internal \
reasoning chains. KEEP technology names exactly as written."""

DISTILL_USER = """\
Today's date: {today}

Raw input:
<raw_input>
{raw_text}
</raw_input>

Distilled output:"""


class OllamaDistiller:
    """Distills raw text via a local Ollama model. Implements DistillerPort."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "gemma3:4b",
    ) -> None:
        self._host = host
        self._model = model

    async def distill(self, raw_text: str) -> str:
        prompt = DISTILL_USER.format(
            today=date.today().isoformat(),
            raw_text=raw_text,
        )
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        try:
            async with httpx.AsyncClient(proxy=proxy) as client:
                resp = await client.post(
                    f"{self._host}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": DISTILL_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    },
                    timeout=60.0,
                )
                resp.raise_for_status()
                result = resp.json()["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama distillation failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError:
            raise RuntimeError(
                f"Ollama is not reachable — is it running on {self._host}?"
            ) from None
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise RuntimeError(f"Ollama distillation request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Ollama response format: {e}") from e
        return result
