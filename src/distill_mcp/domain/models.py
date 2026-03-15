"""Domain models — pure data, no dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Memory:
    id: str
    content: str  # distilled text only
    type: str  # decision | pattern | failure | dependency | context
    repos: list[str]
    tags: list[str]
    author: str | None  # None=anonymous, hash=pseudonym, name=named
    created_at: datetime
    occurred_at: datetime | None = None  # when it happened (vs. when stored)


@dataclass
class SearchResult:
    memory: Memory
    score: float  # RRF hybrid score
