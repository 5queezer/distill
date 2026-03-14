"""DistillerPort implementation — local Ollama, never crosses the network."""

from __future__ import annotations

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
7. NEVER add information not present in the input.
8. If the input contains no actionable technical content, output exactly: \
NO_FACTUAL_CONTENT"""

DISTILL_USER = """\
Today's date: {today}

Raw input:
{raw_text}

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
        async with httpx.AsyncClient() as client:
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
        return result
