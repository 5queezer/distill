---
title: MCP Tools
---

# MCP Tools Reference

Distill exposes 8 tools via the MCP protocol. Claude Code calls these automatically based on conversation context.

Memories are captured automatically via the [auto-observe pipeline](../explanation/how-memory-works.md) — there is no explicit "remember" tool. The tools below are for **reading, searching, and managing** existing memories.

## search_memory

Hybrid search combining full-text (FTS5/tsvector) and vector similarity (LanceDB/pgvector), merged with Reciprocal Rank Fusion (k=60).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search query |
| `top_k` | int | no | Max results (default: 5, max: 100) |
| `repo` | string | no | Filter by repository |
| `agent_id` | string | no | Filter by agent |
| `after` | string | no | Only return memories created after this date (ISO 8601, e.g. `"2025-01-01"`) |
| `before` | string | no | Only return memories created before this date (ISO 8601, e.g. `"2025-06-01"`) |

**Returns:** Compact index (~30 tokens/result) with `id`, `type`, `level`, `snippet`, `repos`, `score`, `created_at`, `est_tokens`, `agent_id`. Use `get_memories` to fetch full content for relevant results.

## get_memories

Fetch full memory details by IDs. Batch multiple IDs in one call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ids` | list[string] | yes | Memory IDs to fetch |

**Returns:** Full memory objects including `level` field (`short-term`, `long-term`, or `shared`).

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

**Returns:** Compact index including `level` field (`short-term`, `long-term`, or `shared`).

## list_stale

List memories likely stale based on age and access patterns.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | no | Filter by repository |
| `limit` | int | no | Max results (default: 20) |

**Returns:** List of stale memory dicts with `id`, `type`, `snippet`, `age_days`, `access_count`, `survival_score`.

## forget

Soft-delete a memory. It will no longer appear in search results.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | Memory ID to delete |
| `agent_id` | string | no | If provided, only deletes if the memory belongs to this agent |

## get_lineage

Trace the supersedes chain for a memory in both directions. Returns the full history: predecessors (what this memory replaced) and successors (what replaced this memory), ordered oldest to newest. Useful for understanding how a decision evolved over time.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | yes | Memory ID to trace |

**Returns:** List of memory dicts in the supersedes chain, ordered oldest to newest.
