"""MCP server — thin adapter exposing 6 tools. No business logic here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from distill_mcp.domain.services import MemoryService

mcp = FastMCP("distill")
_service: MemoryService | None = None


def set_service(service: MemoryService) -> None:
    global _service
    _service = service


def _svc() -> MemoryService:
    assert _service is not None, "MemoryService not initialised — call set_service()"
    return _service


@mcp.tool
async def remember(
    content: str,
    type: str,
    repos: list[str],
    tags: list[str] | None = None,
) -> dict:
    """Distill raw input into anonymous team knowledge and store it.

    The raw text is processed locally by Ollama and never leaves your device.
    Only the distilled factual output is stored in the team database.
    """
    return await _svc().remember(content, type, repos, tags)


@mcp.tool
async def search_memory(query: str, top_k: int = 5) -> list[dict]:
    """Search team knowledge using hybrid keyword + semantic search.

    Returns the most relevant memories ranked by combined relevance score.
    """
    results = await _svc().search(query, top_k)
    return [
        {
            "id": r.memory.id,
            "content": r.memory.content,
            "type": r.memory.type,
            "repos": r.memory.repos,
            "tags": r.memory.tags,
            "score": round(r.score, 4),
        }
        for r in results
    ]


@mcp.tool
async def get_memory(id: str) -> dict:
    """Retrieve a specific memory by its ID."""
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
    }


@mcp.tool
async def update_memory(id: str, content: str) -> dict:
    """Re-distill new content and supersede an existing memory.

    The old memory is soft-deleted. A new memory is created with
    the distilled version of the provided content.
    """
    return await _svc().update(id, content)


@mcp.tool
async def list_recent(
    repo: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List recent memories, optionally filtered by repo, tag, or type."""
    memories = await _svc().list_recent(repo=repo, tag=tag, type=type, limit=limit)
    return [
        {
            "id": m.id,
            "content": m.content,
            "type": m.type,
            "repos": m.repos,
            "tags": m.tags,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories
    ]


@mcp.tool
async def forget(id: str) -> dict:
    """Soft-delete a memory. It will no longer appear in search results."""
    return await _svc().forget(id)
