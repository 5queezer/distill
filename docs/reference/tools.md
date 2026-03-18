---
title: MCP Tools
---

# MCP Tools Reference

Distill exposes 8 tools via the MCP protocol. Claude Code calls these automatically based on conversation context.

## remember

Distill raw input into anonymous team knowledge.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | yes | Raw text to distill |
| `type` | string | yes | Memory type (e.g., `decision`, `convention`, `bug`) |
| `repos` | list[string] | no | Repository tags (auto-detected from git if omitted) |
| `tags` | list[string] | no | Free-form tags for filtering |
| `agent_id` | string | no | Agent identifier for multi-agent filtering |

**Returns:** A preview with `pending_id` (when `PREVIEW_ENABLED=true`, the default) or the saved memory directly.

**Privacy:** The raw `content` is sent to local Ollama only. The distilled output is what gets stored.

## confirm_memory

Confirm a pending preview and store it.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | The `pending_id` from `remember` |
| `override` | string | no | Replacement text (will be re-distilled) |

## search_memory

Hybrid search combining full-text (FTS5/tsvector) and vector similarity (LanceDB/pgvector), merged with Reciprocal Rank Fusion (k=60).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search query |
| `top_k` | int | no | Max results (default: 5, max: 100) |
| `repo` | string | no | Filter by repository |
| `agent_id` | string | no | Filter by agent |

**Returns:** Compact index (~30 tokens/result) with `id`, `type`, `snippet`, `score`, `est_tokens`. Use `get_memories` to fetch full content for relevant results.

## get_memories

Fetch full memory details by IDs. Batch multiple IDs in one call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ids` | list[string] | yes | Memory IDs to fetch |

## get_memory

Retrieve a single memory by ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | Memory ID |

## update_memory

Re-distill new content and supersede an existing memory. The old memory is soft-deleted.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | ID of the memory to update |
| `content` | string | yes | New raw content to distill |

## list_recent

List recent memories as compact index.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | no | Filter by repository |
| `tag` | string | no | Filter by tag |
| `type` | string | no | Filter by memory type |
| `limit` | int | no | Max results (default: 20, max: 100) |
| `agent_id` | string | no | Filter by agent |

## forget

Soft-delete a memory. It will no longer appear in search results.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | Memory ID to delete |
| `agent_id` | string | no | If provided, only deletes if the memory belongs to this agent |
