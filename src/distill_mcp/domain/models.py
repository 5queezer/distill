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
    access_count: int = 0
    last_accessed_at: datetime | None = None
    agent_id: str | None = None  # which agent wrote this (None = human)


@dataclass
class SearchResult:
    memory: Memory
    score: float  # RRF hybrid score


@dataclass
class MemoryIndex:
    """Compact search result for progressive disclosure (Layer 1)."""

    id: str
    type: str
    snippet: str  # first 80 chars of content
    repos: list[str]
    score: float
    created_at: datetime
    est_tokens: int  # len(content) // 4
    agent_id: str | None = None


@dataclass
class MemoryDetail:
    """Full memory detail for progressive disclosure (Layer 2)."""

    id: str
    content: str
    type: str
    repos: list[str]
    tags: list[str]
    score: float | None
    created_at: datetime
    author: str | None
    agent_id: str | None = None
    est_tokens: int = 0
