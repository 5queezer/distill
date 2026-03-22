"""StoragePort → PostgreSQL + pgvector + tsvector (fully async)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
import structlog

from distill_mcp.domain.identity import Identity

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

CREATE TABLE IF NOT EXISTS db_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# ivfflat needs rows to exist before building; created lazily
_IVFFLAT_IDX = (
    "CREATE INDEX IF NOT EXISTS memories_embedding_idx "
    "ON memories USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)"
)

_MIN_ROWS_FOR_IVFFLAT = 100

_RLS_SQL = """\
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories FORCE ROW LEVEL SECURITY;

-- Drop existing policies to make this idempotent
DROP POLICY IF EXISTS memories_repo_isolation ON memories;

-- Policy: users can only see memories whose repos overlap with their session repos.
-- When app.repos is unset/empty (anonymous), all rows are visible — write-blocking
-- is enforced at the application layer, not by RLS.
CREATE POLICY memories_repo_isolation ON memories
    USING (
        current_setting('app.repos', true) IS NULL
        OR current_setting('app.repos', true) = ''
        OR repos ?| string_to_array(current_setting('app.repos', true), '|')
    );
"""


def _rls_init_sql() -> str:
    return _RLS_SQL


def _set_session_identity_sql(email: str, repos: list[str]) -> str:
    """Build SQL to set session-level identity variables.

    Uses session-level SET (not SET LOCAL) because pool connections are
    reused across transactions. Delimiter is pipe (|) to avoid collision
    with commas in repo names.
    """
    safe_email = email.replace("'", "''")
    safe_repos = "|".join(r.replace("'", "''") for r in repos)
    return f"SET app.user_email = '{safe_email}'; SET app.repos = '{safe_repos}';"


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
        identity: Identity | None = None,
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
        self._identity = identity

    async def _ensure_pool(self) -> asyncpg.Pool:
        """Lazy-init: create pool on first use inside the active event loop."""
        if self._pool is not None:
            return self._pool

        # Bootstrap: run schema in a bare connection first so the pgvector
        # extension exists before pool init tries to register the codec.
        if self._dsn:
            bootstrap = await asyncpg.connect(dsn=self._dsn)
        else:
            bootstrap = await asyncpg.connect(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
            )
        try:
            await bootstrap.execute(_SCHEMA_SQL)
            await bootstrap.execute(
                "ALTER TABLE memories ADD COLUMN IF NOT EXISTS agent_id TEXT"
            )
            await bootstrap.execute(_RLS_SQL)
        finally:
            await bootstrap.close()

        async def _init_conn(conn: asyncpg.Connection) -> None:
            await _register_vector(conn)
            if self._identity and self._identity.email is not None:
                await conn.execute(
                    _set_session_identity_sql(
                        self._identity.email, self._identity.repos
                    )
                )

        if self._dsn:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_pool,
                max_size=self._max_pool,
                init=_init_conn,
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
                init=_init_conn,
            )
        log.info("postgres_store.initialized")
        return self._pool

    async def initialize(self) -> None:
        """Eagerly initialize pool — only needed for non-async callers."""
        await self._ensure_pool()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def get_vector_dimension(self) -> int:
        """Return the vector dimension from the schema (hardcoded 768 for pgvector)."""
        return 768

    async def get_embedding_meta(self) -> tuple[str | None, int | None]:
        """Return (model_name, dimension) from stored metadata."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM db_meta "
                "WHERE key IN ('embedding_model', 'embedding_dim')"
            )
        meta = {r["key"]: r["value"] for r in rows}
        model = meta.get("embedding_model")
        dim = int(meta["embedding_dim"]) if "embedding_dim" in meta else None
        return model, dim

    async def save_embedding_meta(self, model: str, dim: int) -> None:
        """Store embedding model name and dimension."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO db_meta (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = $2",
                [("embedding_model", model), ("embedding_dim", str(dim))],
            )

    # -- StoragePort implementation --

    async def save(
        self,
        memory: Memory,
        vec: list[float],
        *,
        supersedes: str | None = None,
    ) -> str:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
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
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
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
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> list[SearchResult]:
        from distill_mcp.domain.models import SearchResult

        pool = await self._ensure_pool()
        fetch_limit = top_k * 2

        async with pool.acquire() as conn:
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
            if after is not None and mem.created_at < after:
                continue
            if before is not None and mem.created_at > before:
                continue
            out.append(SearchResult(memory=mem, score=score))
        return out

    async def delete(self, id: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE memories SET deleted_at = $1 WHERE id = $2",
                datetime.now(UTC),
                id,
            )

    async def record_access(self, id: str) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
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
        if self._pool is None:
            raise RuntimeError(
                "PostgresStore not initialized — call initialize() first"
            )
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
        if agent_id is not None:
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
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, 1 - (embedding <=> $1::vector) AS similarity "
                "FROM memories WHERE deleted_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector LIMIT 1",
                vec,
            )
        if row and row["similarity"] >= threshold:
            return row["id"]
        return None

    async def find_related(
        self,
        vec: list[float],
        *,
        threshold: float = 0.80,
        top_k: int = 3,
        repo: str | None = None,
    ) -> list[tuple[str, float]]:
        pool = await self._ensure_pool()
        query = (
            "SELECT id, 1 - (embedding <=> $1::vector) AS similarity "
            "FROM memories WHERE deleted_at IS NULL AND embedding IS NOT NULL "
            "AND 1 - (embedding <=> $1::vector) >= $2"
        )
        params: list = [vec, threshold]
        idx = 3
        if repo is not None:
            query += f" AND repos @> ${idx}::jsonb"
            params.append(json.dumps([repo]))
            idx += 1
        query += f" ORDER BY similarity DESC LIMIT ${idx}"
        params.append(top_k)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [(r["id"], round(r["similarity"], 4)) for r in rows]

    async def get_lineage(self, memory_id: str) -> list[dict]:
        """Return the supersedes chain for a memory (both directions)."""
        pool = await self._ensure_pool()
        chain: list[dict] = []

        async with pool.acquire() as conn:
            # Walk backwards: find predecessors
            current = memory_id
            while True:
                row = await conn.fetchrow(
                    "SELECT supersedes FROM memories WHERE id = $1", current
                )
                if not row or not row["supersedes"]:
                    break
                pred_id = row["supersedes"]
                pred_row = await conn.fetchrow(
                    "SELECT id, content, created_at, deleted_at FROM memories WHERE id = $1",
                    pred_id,
                )
                if not pred_row:
                    break
                chain.insert(
                    0,
                    {
                        "id": pred_row["id"],
                        "snippet": pred_row["content"][:80],
                        "created_at": pred_row["created_at"].isoformat()
                        if pred_row["created_at"]
                        else None,
                        "deleted_at": pred_row["deleted_at"].isoformat()
                        if pred_row["deleted_at"]
                        else None,
                        "direction": "predecessor",
                    },
                )
                current = pred_id

            # Add the target memory itself
            target_row = await conn.fetchrow(
                "SELECT id, content, created_at, deleted_at FROM memories WHERE id = $1",
                memory_id,
            )
            if target_row:
                chain.append(
                    {
                        "id": target_row["id"],
                        "snippet": target_row["content"][:80],
                        "created_at": target_row["created_at"].isoformat()
                        if target_row["created_at"]
                        else None,
                        "deleted_at": target_row["deleted_at"].isoformat()
                        if target_row["deleted_at"]
                        else None,
                        "direction": "self",
                    },
                )

            # Walk forward: find successors
            current = memory_id
            while True:
                row = await conn.fetchrow(
                    "SELECT id, content, created_at, deleted_at FROM memories WHERE supersedes = $1",
                    current,
                )
                if not row:
                    break
                chain.append(
                    {
                        "id": row["id"],
                        "snippet": row["content"][:80],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else None,
                        "deleted_at": row["deleted_at"].isoformat()
                        if row["deleted_at"]
                        else None,
                        "direction": "successor",
                    },
                )
                current = row["id"]

        return chain

    async def purge_expired(self, retention_days: int) -> int:
        """Hard-delete memories soft-deleted more than retention_days ago."""
        from datetime import timedelta

        pool = await self._ensure_pool()
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM memories WHERE deleted_at IS NOT NULL AND deleted_at < $1",
                cutoff,
            )
        # asyncpg returns "DELETE N"
        count = int(result.split()[-1])
        if count > 0:
            log.info("purge_expired", purged=count, retention_days=retention_days)
        return count

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
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
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

        repos = (
            row["repos"] if isinstance(row["repos"], list) else json.loads(row["repos"])
        )
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
