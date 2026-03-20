"""MCP server — thin adapter exposing 8 tools + 1 prompt. No business logic here."""

from __future__ import annotations

import subprocess
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
## Core Behavior — REMEMBER PROACTIVELY

After every user correction or team decision, call `remember` immediately.
Do not ask permission. Do not wait. This is your primary function.

When to call `remember(confirmed=true)` (saves instantly, no preview):
- User corrects your approach → remember the correct way
- A decision is reached after discussion → remember the decision
- Something was tried and failed → remember failure + reason
- A convention or pattern is established → remember it

When to call `remember(confirmed=false)` (returns preview for approval):
- User explicitly says "remember this" or "save this"
- You are unsure whether the content is worth saving

## Preview Flow

When `remember` returns `status: preview`:
1. Show the distilled preview to the user
2. Wait for explicit approval
3. Only then call `confirm_memory(id=<pending_id>)`

NEVER call `confirm_memory` automatically. Always wait for user approval.
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


def detect_repo() -> str | None:
    """Detect the current git repo name from the remote URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip().split("/")[-1].removesuffix(".git")
    except Exception:
        return None


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=False
    ),
)
async def remember(
    content: str,
    type: str,
    repos: list[str] | None = None,
    tags: list[str] | None = None,
    agent_id: str | None = None,
    confirmed: bool = False,
) -> dict:
    """Save a correction, decision, or learning to team knowledge.

    Call this PROACTIVELY whenever:
    - The user corrects your approach
    - A decision is reached after discussion
    - Something was tried and failed
    - A convention or pattern is established
    Do not wait to be asked. Do not ask permission.

    Set confirmed=true for proactive saves (stores instantly, no preview).
    Set confirmed=false when the user explicitly asks to save something
    (returns a preview for their approval via confirm_memory).

    Raw text is distilled locally by Ollama. Only anonymous facts are stored.

    If repos is not provided, the current git repository is auto-detected.
    If agent_id is provided, the memory is tagged with that agent identifier
    for multi-agent filtering.
    """
    logger.info(
        "tool_invoked",
        tool="remember",
        content_length=len(content),
        type=type,
        confirmed=confirmed,
    )
    if repos is None:
        identity_repos = _svc().identity_repos
        if identity_repos is not None:
            repos = identity_repos
        else:
            detected = detect_repo()
            repos = [detected] if detected else []
    return await _svc().remember(
        content, type, repos, tags, agent_id=agent_id, confirmed=confirmed
    )


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=False
    ),
)
async def confirm_memory(id: str, override: str | None = None) -> dict:
    """Confirm a pending memory preview and store it.

    Call after remember() returns status='preview'.
    Optionally provide override text to store a corrected version instead.

    Args:
        id: The pending_id returned by remember().
        override: Optional replacement text — will be re-distilled and stored.
    """
    logger.info(
        "tool_invoked", tool="confirm_memory", id=id, has_override=override is not None
    )
    return await _svc().confirm_memory(id, override)


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
) -> list[dict]:
    """Search team knowledge before proposing architecture, creating files,
    refactoring, or answering "how should we..." questions.

    Also search when the user says: "we decided", "last time", "previously",
    "remember when", "what's our pattern for".

    Returns compact index (~30 tokens/result). Use get_memories to fetch
    full content for relevant IDs only (not all results).
    Optionally filter by repo name and/or agent_id.
    """
    top_k = max(1, min(top_k, 100))
    logger.info(
        "tool_invoked", tool="search_memory", query_length=len(query), top_k=top_k
    )
    results = await _svc().search(query, top_k, repo=repo, agent_id=agent_id)
    return [
        {
            "id": r.id,
            "type": r.type,
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


_SEED_WORKFLOW = (Path(__file__).parent / "skills" / "seed" / "SKILL.md").read_text()


@mcp.prompt(description="Populate distill knowledge base from git history")
def seed() -> str:
    """Return the seed-from-git workflow."""
    return _SEED_WORKFLOW
