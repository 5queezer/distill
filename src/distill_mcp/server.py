"""MCP server — thin adapter exposing tools. No business logic here."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from distill_mcp.domain.services import MemoryService

mcp = FastMCP(
    "distill",
    instructions="""\
## Memory Protocol

### Storing — after every correction or decision
When the user corrects your approach, or when a decision is made after
discussion, call `remember` to save the learning. Don't ask — just do it.

What to remember:
- User corrects your approach → remember the correct way
- Something was tried and failed → remember failure + reason
- A convention is established → remember the convention
- You went back and forth → remember the final decision

### Preview flow — CRITICAL
When `remember` returns `status: pending`, you MUST:
1. Show the distilled preview to the user
2. Wait for explicit approval
3. Only THEN call `confirm_memory(id=<pending_id>)`

NEVER call `confirm_memory` automatically after `remember`.
Always show the preview and wait for explicit user approval.

### Retrieval — MANDATORY before these actions
ALWAYS call `search_memory` BEFORE:
- Proposing an architecture or technology choice
- Creating a new file or module
- Refactoring existing code
- Answering "how should we..." or "what's the best way to..."
- Starting work on a new task or issue

### Retrieval — ALWAYS when user says
Trigger words that REQUIRE a `search_memory` call:
- "we decided", "we agreed", "last time", "previously"
- "remember when", "what was the reason", "why did we"
- "how do we", "what's our pattern for", "don't we already have"

### Detect loops
Before suggesting an approach, search memory first.
If a memory says "tried X, didn't work because Y", don't suggest X again.

### When search returns partial results
If search_memory finds related context but not the exact answer:

1. Tell the user what you DID find
2. Offer TWO follow-up actions:
   a) "I can check the git history for the reasoning"
      → run git log --all --oneline --grep="<keyword>"
      → distill what you find → remember it
   b) "If you remember, tell me and I'll save it"
      → when user answers → remember immediately

Never leave a knowledge gap unfilled. Every question you ask
is an opportunity to capture knowledge that's missing.

### Progressive Disclosure (Token Efficiency)
search_memory returns a compact index (~30 tokens/result), NOT full content.
Workflow:
1. Call search_memory to get index with IDs, types, snippets, scores, est_tokens
2. Review the index. Decide which results are relevant.
3. Call get_memories(ids=[...]) with ONLY the relevant IDs to fetch full content.
NEVER call get_memories for all results — that defeats the purpose.
Budget: if est_tokens < 50, it's cheap to fetch. If > 200, think twice.

### After answering from memory
If you used search_memory to answer a question, and the user
adds context or corrects you, remember the correction immediately.
Don't wait. Don't ask. Just save.
""",
)
_service: MemoryService | None = None


def set_service(service: MemoryService) -> None:
    global _service
    _service = service


def _svc() -> MemoryService:
    assert _service is not None, "MemoryService not initialised — call set_service()"
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


@mcp.tool
async def remember(
    content: str,
    type: str,
    repos: list[str] | None = None,
    tags: list[str] | None = None,
    agent_id: str | None = None,
) -> dict:
    """Distill raw input into anonymous team knowledge.

    When preview mode is enabled (default), returns a pending preview.
    Show the preview to the user and call confirm_memory() after approval.

    The raw text is processed locally by Ollama and never leaves your device.
    Only the distilled factual output is stored in the team database.

    If repos is not provided, the current git repository is auto-detected.
    If agent_id is provided, the memory is tagged with that agent identifier
    for multi-agent filtering.
    """
    if repos is None:
        detected = detect_repo()
        repos = [detected] if detected else []
    return await _svc().remember(content, type, repos, tags, agent_id=agent_id)


@mcp.tool
async def confirm_memory(id: str, override: str | None = None) -> dict:
    """Confirm a pending memory preview and store it.

    Call after remember() returns status='pending'.
    Optionally provide override text to store a corrected version instead.

    Args:
        id: The pending_id returned by remember().
        override: Optional replacement text — will be re-distilled and stored.
    """
    return await _svc().confirm_memory(id, override)


@mcp.tool
async def search_memory(
    query: str,
    top_k: int = 5,
    repo: str | None = None,
    agent_id: str | None = None,
) -> list[dict]:
    """Search team knowledge. Returns compact index (~30 tokens/result).

    Use get_memories to fetch full content for relevant IDs.
    Optionally filter by repo name and/or agent_id.
    """
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


@mcp.tool
async def get_memories(ids: list[str]) -> list[dict]:
    """Fetch full memory details by IDs. Batch multiple IDs in one call.

    Use after search_memory to get content for relevant results only.
    """
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
        "agent_id": mem.agent_id,
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
    agent_id: str | None = None,
) -> list[dict]:
    """List recent memories as compact index. Use get_memories for full content.

    Optionally filter by repo, tag, type, or agent_id.
    """
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


@mcp.tool
async def forget(id: str, agent_id: str | None = None) -> dict:
    """Soft-delete a memory. It will no longer appear in search results.

    If agent_id is provided, the memory is only deleted when it belongs
    to that agent. Returns 'forbidden' if the memory belongs to a
    different agent.
    """
    return await _svc().forget(id, agent_id=agent_id)
