"""StoragePort → SQLite + FTS5 + LanceDB."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import lancedb

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, SearchResult


def rrf_merge(
    fts_ids: list[str], vec_ids: list[str], k: int = 60
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion — merge two ranked ID lists into one."""
    scores: dict[str, float] = {}
    for rank, mid in enumerate(fts_ids, start=1):
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank)
    for rank, mid in enumerate(vec_ids, start=1):
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class SqliteStore:
    """Local storage backend using SQLite (metadata + FTS5) and LanceDB (vectors)."""

    def __init__(self, data_dir: str, rrf_k: int = 60) -> None:
        self._dir = Path(data_dir).expanduser()
        self._db_path = self._dir / "memories.db"
        self._lance_uri = str(self._dir / "lance")
        self._conn: sqlite3.Connection | None = None
        self._lance: lancedb.DBConnection | None = None
        self._rrf_k = rrf_k

    def initialize(self) -> None:
        """Create tables. Must be called before any other method."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._lance = lancedb.connect(self._lance_uri)

    def _create_tables(self) -> None:
        assert self._conn is not None
        c = self._conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                type TEXT NOT NULL,
                repos TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                author TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                supersedes TEXT,
                deleted_at TEXT,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed_at TEXT
            )
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(id UNINDEXED, content, tags, tokenize='unicode61')
        """)
        c.commit()
        self._migrate(c)

    def _migrate(self, c: sqlite3.Connection) -> None:
        """Add columns that may be missing from older databases."""
        existing = {row[1] for row in c.execute("PRAGMA table_info(memories)")}
        migrations = [
            ("access_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_accessed_at", "TEXT"),
        ]
        for col, typedef in migrations:
            if col not in existing:
                c.execute(f"ALTER TABLE memories ADD COLUMN {col} {typedef}")
        c.commit()

    # -- StoragePort implementation --

    async def save(
        self,
        memory: Memory,
        vec: list[float],
        *,
        supersedes: str | None = None,
    ) -> str:
        assert self._conn is not None and self._lance is not None
        c = self._conn
        c.execute(
            """INSERT INTO memories (id, content, type, repos, tags, author,
                                    created_at, supersedes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.type,
                json.dumps(memory.repos),
                json.dumps(memory.tags),
                memory.author,
                memory.created_at.isoformat(),
                supersedes,
            ),
        )
        tag_str = " ".join(memory.tags)
        c.execute(
            "INSERT INTO memories_fts (id, content, tags) VALUES (?, ?, ?)",
            (memory.id, memory.content, tag_str),
        )
        c.commit()

        data = [{"id": memory.id, "vector": vec}]
        if self._has_vec_table():
            self._lance.open_table("vectors").add(data)
        else:
            self._lance.create_table("vectors", data)

        return memory.id

    async def get(self, id: str) -> Memory | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL", (id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    async def search(
        self,
        query_text: str,
        query_vec: list[float],
        top_k: int,
        *,
        repo: str | None = None,
    ) -> list[SearchResult]:
        from distill_mcp.domain.models import SearchResult

        fts_ids = self._fts_search(query_text, top_k * 2)
        vec_ids = self._vec_search(query_vec, top_k * 2)
        merged = rrf_merge(fts_ids, vec_ids, self._rrf_k)

        out: list[SearchResult] = []
        for mid, score in merged:
            if len(out) >= top_k:
                break
            mem = await self.get(mid)
            if mem and (repo is None or repo in mem.repos):
                out.append(SearchResult(memory=mem, score=score))
        return out

    async def delete(self, id: str) -> None:
        assert self._conn is not None
        self._conn.execute(
            "UPDATE memories SET deleted_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), id),
        )
        self._conn.commit()

    async def record_access(self, id: str) -> None:
        assert self._conn is not None
        self._conn.execute(
            "UPDATE memories SET access_count = access_count + 1, "
            "last_accessed_at = ? WHERE id = ? AND deleted_at IS NULL",
            (datetime.now(UTC).isoformat(), id),
        )
        self._conn.commit()

    async def list_recent(
        self,
        *,
        repo: str | None = None,
        tag: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        assert self._conn is not None
        query = "SELECT * FROM memories WHERE deleted_at IS NULL"
        params: list[str | int] = []
        if repo:
            query += " AND EXISTS (SELECT 1 FROM json_each(repos) WHERE value = ?)"
            params.append(repo)
        if tag:
            query += " AND EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)"
            params.append(tag)
        if type:
            query += " AND type = ?"
            params.append(type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_memory(r) for r in rows]

    async def export_all(
        self,
        *,
        repos: list[str] | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> list[Memory]:
        assert self._conn is not None
        query = "SELECT * FROM memories WHERE deleted_at IS NULL"
        params: list[str] = []
        if repos:
            placeholders = ",".join("?" for _ in repos)
            query += (
                " AND EXISTS "
                f"(SELECT 1 FROM json_each(repos) WHERE value IN ({placeholders}))"
            )
            params.extend(repos)
        if after:
            query += " AND created_at >= ?"
            params.append(after)
        if before:
            query += " AND created_at < ?"
            params.append(before)
        query += " ORDER BY created_at ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_memory(r) for r in rows]

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        assert self._lance is not None and self._conn is not None
        if not self._has_vec_table():
            return None
        table = self._lance.open_table("vectors")
        results = table.search(vec).metric("cosine").limit(5).to_list()
        for r in results:
            distance = r["_distance"]
            if distance >= (1.0 - threshold):
                break
            row = self._conn.execute(
                "SELECT id FROM memories WHERE id = ? AND deleted_at IS NULL",
                (r["id"],),
            ).fetchone()
            if row:
                return r["id"]
        return None

    def _has_vec_table(self) -> bool:
        assert self._lance is not None
        return "vectors" in self._lance.list_tables().tables

    # -- Internal helpers --

    def _fts_search(self, query_text: str, limit: int) -> list[str]:
        assert self._conn is not None
        sanitized = self._sanitize_fts(query_text)
        if not sanitized:
            return []
        rows = self._conn.execute(
            "SELECT id FROM memories_fts WHERE memories_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (sanitized, limit),
        ).fetchall()
        return [r["id"] for r in rows]

    def _vec_search(self, query_vec: list[float], limit: int) -> list[str]:
        assert self._lance is not None
        if not self._has_vec_table():
            return []
        table = self._lance.open_table("vectors")
        results = table.search(query_vec).metric("cosine").limit(limit).to_list()
        return [r["id"] for r in results]

    @staticmethod
    def _sanitize_fts(query: str) -> str:
        words = re.findall(r"\w+", query)
        return " OR ".join(f'"{w}"' for w in words) if words else ""

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        from distill_mcp.domain.models import Memory

        last_accessed = row["last_accessed_at"]
        return Memory(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            repos=json.loads(row["repos"]),
            tags=json.loads(row["tags"]),
            author=row["author"],
            created_at=datetime.fromisoformat(row["created_at"]),
            supersedes=row["supersedes"],
            access_count=row["access_count"],
            last_accessed_at=datetime.fromisoformat(last_accessed)
            if last_accessed
            else None,
        )
