"""StoragePort → PostgreSQL + pgvector + tsvector (fully async)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
import structlog

if TYPE_CHECKING:
    from distill_mcp.domain.models import Memory, SearchResult

log = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    type TEXT NOT NULL,
    repos JSONB NOT NULL DEFAULT '[]',
    tags JSONB NOT NULL DEFAULT '[]',
    author TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ,
    supersedes TEXT,
    deleted_at TIMESTAMPTZ,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    agent_id TEXT,
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    embedding VECTOR(768)
);

CREATE INDEX IF NOT EXISTS memories_tsv_idx ON memories USING GIN(content_tsv);
"""

# ivfflat needs rows to exist before building; created lazily
_IVFFLAT_IDX = (
    "CREATE INDEX IF NOT EXISTS memories_embedding_idx "
    "ON memories USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)"
)

_MIN_ROWS_FOR_IVFFLAT = 100


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


async def _register_vector(conn: asyncpg.Connection) -> None:
    from pgvector.asyncpg import register_vector

    await register_vector(conn)


class PostgresStore:
    """Async PostgreSQL backend using asyncpg + pgvector."""

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 5432,
        database: str = "distill",
        user: str = "distill",
        password: str = "distill",
        min_pool: int = 2,
        max_pool: int = 10,
        rrf_k: int = 60,
        fts_language: str = "simple",
        dsn: str | None = None,
    ) -> None:
        self._dsn = dsn
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._rrf_k = rrf_k
        self._fts_language = fts_language
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create pool, register pgvector codec, run migrations."""
        if self._dsn:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_pool,
                max_size=self._max_pool,
                init=_register_vector,
            )
        else:
            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                min_size=self._min_pool,
                max_size=self._max_pool,
                init=_register_vector,
            )
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
        log.info("postgres_store.initialized")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # -- StoragePort implementation --

    async def save(
        self,
        memory: Memory,
        vec: list[float],
        *,
        supersedes: str | None = None,
    ) -> str:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO memories
                   (id, content, type, repos, tags, author,
                    created_at, supersedes, agent_id, embedding)
                   VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6,
                           $7, $8, $9, $10)""",
                memory.id,
                memory.content,
                memory.type,
                json.dumps(memory.repos),
                json.dumps(memory.tags),
                memory.author,
                memory.created_at,
                supersedes,
                memory.agent_id,
                vec,
            )
        await self._maybe_create_ivfflat()
        return memory.id

    async def get(self, id: str) -> Memory | None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM memories WHERE id = $1 AND deleted_at IS NULL", id
            )
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
        agent_id: str | None = None,
    ) -> list[SearchResult]:
        from distill_mcp.domain.models import SearchResult

        assert self._pool is not None
        fetch_limit = top_k * 2

        async with self._pool.acquire() as conn:
            fts_ids = await self._fts_search(conn, query_text, fetch_limit)
            vec_ids = await self._vec_search(conn, query_vec, fetch_limit)

        merged = rrf_merge(fts_ids, vec_ids, self._rrf_k)

        out: list[SearchResult] = []
        for mid, score in merged:
            if len(out) >= top_k:
                break
            mem = await self.get(mid)
            if mem is None:
                continue
            if repo is not None and repo not in mem.repos:
                continue
            if agent_id is not None and mem.agent_id != agent_id:
                continue
            out.append(SearchResult(memory=mem, score=score))
        return out

    async def delete(self, id: str) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE memories SET deleted_at = $1 WHERE id = $2",
                datetime.now(UTC),
                id,
            )

    async def record_access(self, id: str) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE memories SET access_count = access_count + 1, "
                "last_accessed_at = $1 WHERE id = $2 AND deleted_at IS NULL",
                datetime.now(UTC),
                id,
            )

    async def list_recent(
        self,
        *,
        repo: str | None = None,
        tag: str | None = None,
        type: str | None = None,
        limit: int = 20,
        agent_id: str | None = None,
    ) -> list[Memory]:
        assert self._pool is not None
        query = "SELECT * FROM memories WHERE deleted_at IS NULL"
        params: list[str | int] = []
        idx = 1

        if repo:
            query += f" AND repos @> ${idx}::jsonb"
            params.append(json.dumps([repo]))
            idx += 1
        if tag:
            query += f" AND tags @> ${idx}::jsonb"
            params.append(json.dumps([tag]))
            idx += 1
        if type:
            query += f" AND type = ${idx}"
            params.append(type)
            idx += 1
        if agent_id:
            query += f" AND agent_id = ${idx}"
            params.append(agent_id)
            idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_memory(r) for r in rows]

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, 1 - (embedding <=> $1::vector) AS similarity "
                "FROM memories WHERE deleted_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector LIMIT 1",
                vec,
            )
        if row and row["similarity"] >= threshold:
            return row["id"]
        return None

    # -- Internal helpers --

    async def _fts_search(
        self, conn: asyncpg.Connection, query_text: str, limit: int
    ) -> list[str]:
        if not query_text.strip():
            return []
        rows = await conn.fetch(
            "SELECT id, ts_rank(content_tsv, plainto_tsquery($1, $2)) AS rank "
            "FROM memories WHERE deleted_at IS NULL "
            "AND content_tsv @@ plainto_tsquery($1, $2) "
            "ORDER BY rank DESC LIMIT $3",
            self._fts_language,
            query_text,
            limit,
        )
        return [r["id"] for r in rows]

    @staticmethod
    async def _vec_search(
        conn: asyncpg.Connection, query_vec: list[float], limit: int
    ) -> list[str]:
        rows = await conn.fetch(
            "SELECT id FROM memories "
            "WHERE deleted_at IS NULL AND embedding IS NOT NULL "
            "ORDER BY embedding <=> $1::vector LIMIT $2",
            query_vec,
            limit,
        )
        return [r["id"] for r in rows]

    async def _maybe_create_ivfflat(self) -> None:
        """Create ivfflat index once we have enough rows for it to be useful."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE embedding IS NOT NULL"
            )
            if count >= _MIN_ROWS_FOR_IVFFLAT:
                idx_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_indexes "
                    "WHERE indexname = 'memories_embedding_idx')"
                )
                if not idx_exists:
                    await conn.execute(_IVFFLAT_IDX)
                    log.info("postgres_store.ivfflat_index_created", rows=count)

    @staticmethod
    def _row_to_memory(row: asyncpg.Record) -> Memory:
        from distill_mcp.domain.models import Memory

        repos = row["repos"] if isinstance(row["repos"], list) else json.loads(row["repos"])
        tags = row["tags"] if isinstance(row["tags"], list) else json.loads(row["tags"])

        return Memory(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            repos=repos,
            tags=tags,
            author=row["author"],
            created_at=row["created_at"],
            access_count=row["access_count"],
            last_accessed_at=row["last_accessed_at"],
            agent_id=row["agent_id"],
        )
