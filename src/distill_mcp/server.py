"""MCP server — thin adapter exposing 8 tools + 1 prompt. No business logic here."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from distill_mcp.domain.services import MemoryService

logger = structlog.get_logger()

mcp = FastMCP(
    "distill",
    instructions="""\
## Searching Memory

Memories are captured automatically from your tool usage — you don't need to save them.

Use `search_memory` proactively before proposing architecture, creating files,
refactoring, or answering "how should we..." questions.

Also search when the user says: "we decided", "last time", "previously",
"remember when", "what's our pattern for".

Use `update_memory` to correct outdated memories and `forget` to remove stale ones.
""",
)
_service: MemoryService | None = None


def set_service(service: MemoryService) -> None:
    global _service
    _service = service


def _svc() -> MemoryService:
    if _service is None:
        raise RuntimeError("MemoryService not initialised — call set_service()")
    return _service


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def search_memory(
    query: str,
    top_k: int = 5,
    repo: str | None = None,
    agent_id: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> list[dict]:
    """Search team knowledge before proposing architecture, creating files,
    refactoring, or answering "how should we..." questions.

    Also search when the user says: "we decided", "last time", "previously",
    "remember when", "what's our pattern for".

    Returns compact index (~30 tokens/result). Use get_memories to fetch
    full content for relevant IDs only (not all results).
    Optionally filter by repo name, agent_id, and/or date range
    (after/before as ISO 8601 strings, e.g. "2025-01-01").
    """

    top_k = max(1, min(top_k, 100))
    logger.info(
        "tool_invoked", tool="search_memory", query_length=len(query), top_k=top_k
    )
    after_dt = datetime.fromisoformat(after) if after else None
    before_dt = datetime.fromisoformat(before) if before else None
    results = await _svc().search(
        query,
        top_k,
        repo=repo,
        agent_id=agent_id,
        after=after_dt,
        before=before_dt,
    )
    return [
        {
            "id": r.id,
            "type": r.type,
            "level": r.level,
            "snippet": r.snippet,
            "repos": r.repos,
            "score": round(r.score, 4),
            "created_at": r.created_at.isoformat(),
            "est_tokens": r.est_tokens,
            "agent_id": r.agent_id,
        }
        for r in results
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def get_memories(ids: list[str]) -> list[dict]:
    """Fetch full memory details by IDs. Batch multiple IDs in one call.

    Use after search_memory to get content for relevant results only.
    """
    logger.info("tool_invoked", tool="get_memories", id_count=len(ids))
    details = await _svc().get_batch(ids)
    return [
        {
            "id": d.id,
            "content": d.content,
            "type": d.type,
            "level": d.level,
            "repos": d.repos,
            "tags": d.tags,
            "score": d.score,
            "created_at": d.created_at.isoformat(),
            "author": d.author,
            "agent_id": d.agent_id,
            "est_tokens": d.est_tokens,
        }
        for d in details
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def get_memory(id: str) -> dict:
    """Retrieve a specific memory by its ID."""
    logger.info("tool_invoked", tool="get_memory", id=id)
    mem = await _svc().get(id)
    if not mem:
        return {"status": "not_found"}
    return {
        "id": mem.id,
        "content": mem.content,
        "type": mem.type,
        "repos": mem.repos,
        "tags": mem.tags,
        "author": mem.author,
        "created_at": mem.created_at.isoformat(),
        "agent_id": mem.agent_id,
    }


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=False
    ),
)
async def update_memory(id: str, content: str) -> dict:
    """Re-distill new content and supersede an existing memory.

    The old memory is soft-deleted. A new memory is created with
    the distilled version of the provided content.
    """
    logger.info(
        "tool_invoked", tool="update_memory", id=id, content_length=len(content)
    )
    return await _svc().update(id, content)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def list_recent(
    repo: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    limit: int = 20,
    agent_id: str | None = None,
) -> list[dict]:
    """List recent memories as compact index. Use get_memories for full content.

    Optionally filter by repo, tag, type, or agent_id.
    """
    limit = max(1, min(limit, 100))
    logger.info("tool_invoked", tool="list_recent", limit=limit)
    indexes = await _svc().list_recent(
        repo=repo, tag=tag, type=type, limit=limit, agent_id=agent_id
    )
    return [
        {
            "id": m.id,
            "type": m.type,
            "level": m.level,
            "snippet": m.snippet,
            "repos": m.repos,
            "created_at": m.created_at.isoformat(),
            "est_tokens": m.est_tokens,
            "agent_id": m.agent_id,
        }
        for m in indexes
    ]


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, openWorldHint=False
    ),
)
async def forget(id: str, agent_id: str | None = None) -> dict:
    """Soft-delete a memory. It will no longer appear in search results.

    If agent_id is provided, the memory is only deleted when it belongs
    to that agent. Returns 'forbidden' if the memory belongs to a
    different agent.
    """
    logger.info("tool_invoked", tool="forget", id=id)
    return await _svc().forget(id, agent_id=agent_id)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def list_stale(
    repo: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List memories that are likely stale based on age and access patterns.

    Stale memories have low Weibull survival scores and few accesses.
    Review the list and use forget() to clean up outdated knowledge.
    """
    limit = max(1, min(limit, 100))
    logger.info("tool_invoked", tool="list_stale", limit=limit)
    return await _svc().identify_stale(repo=repo, limit=limit)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def get_lineage(id: str) -> list[dict]:
    """Trace the supersedes chain for a memory in both directions.

    Returns the full history: predecessors (what this memory replaced)
    and successors (what replaced this memory), ordered oldest to newest.
    Useful for understanding how a decision evolved over time.
    """
    logger.info("tool_invoked", tool="get_lineage", id=id)
    return await _svc().get_lineage(id)


_SEED_WORKFLOW = (Path(__file__).parent / "skills" / "seed" / "SKILL.md").read_text()


@mcp.prompt(description="Populate distill knowledge base from git history")
def seed() -> str:
    """Return the seed-from-git workflow."""
    return _SEED_WORKFLOW
