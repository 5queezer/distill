# Design: Automatic Observation Pipeline

**Status:** Accepted
**Date:** 2026-03-21

## Problem

Distill relies on Claude explicitly calling the `remember` MCP tool to save memories. This has two issues:

1. **Unreliable** — Claude deprioritizes saving under cognitive load, so knowledge is lost
2. **Slow** — each save blocks for 1-8 seconds (distillation + embedding + storage)

## Solution

Replace explicit `remember` calls with automatic background observation capture via Claude Code hooks.

### Data Flow

```
Claude Code session
  |
  +-- Claude calls a tool (Read, Bash, Edit, etc.)
  |
  +-- PostToolUse hook fires
  |     +-- curl POST -> 127.0.0.1:<port>/observe (fire & forget)
  |
  +-- Claude continues immediately (0ms impact)

Distill process (running as MCP server)
  |
  +-- /observe handler
  |     +-- Append JSON line to private_store JSONL
  |     +-- Signal asyncio.Event
  |     +-- Return 202 (< 5ms)
  |
  +-- Background worker (wakes on event)
  |     +-- Read next unprocessed JSONL entry
  |     +-- Noise filter (existing regex)
  |     +-- Secret scanner redact
  |     +-- Distill via DistillerPort (smollm2, ~500ms-2s)
  |     +-- Secret scanner post-check
  |     +-- Embed via EmbeddingPort (~200ms-1s)
  |     +-- Dedup check (cosine 0.95)
  |     +-- Save via StoragePort
  |     +-- Advance cursor
  |     +-- Loop if more entries, else wait on event
  |
  +-- MCP stdio loop (unchanged)
        +-- search_memory
        +-- get_memory / get_memories
        +-- update_memory
        +-- forget
        +-- list_recent / list_stale
```

## Components

### 1. HTTP Ingest Endpoint

- aiohttp server bound to `127.0.0.1:<DISTILL_INGEST_PORT>` (default: 21746)
- Single route: `POST /observe`
- Accepts: `{"tool_name": "...", "input": "...", "output": "..."}`
- Appends to private_store JSONL, signals worker, returns `202 Accepted`
- No auth — localhost only, same trust model as MCP stdio pipe
- Started alongside MCP stdio loop in `__main__.py`

### 2. Background Distillation Worker

- asyncio task started at boot, lives for process lifetime
- Waits on `asyncio.Event` (signaled by `/observe` handler)
- Processes entries sequentially (smollm2 handles one at a time)
- Reuses existing pipeline: distill -> embed -> dedup -> save
- Tracks last-processed line via cursor (`.cursor` file next to JSONL)
- Failed entries retried up to 3 times, then skipped
- Entries that arrive faster than processing queue in JSONL naturally

### 3. Hook Integration

Claude Code `PostToolUse` hook, implemented as a shell command:

```sh
curl -s -X POST http://127.0.0.1:${DISTILL_INGEST_PORT}/observe \
  -H 'Content-Type: application/json' \
  -d @- <<< "$CLAUDE_HOOK_PAYLOAD" &
```

Registered in `.claude/settings.json` under `hooks.PostToolUse`.

Captures: tool name, input, output (tool calls only, not Claude's text responses).

### 4. Removed Components

- `remember` MCP tool
- `confirm_memory` MCP tool
- `MemoryService.remember()` method
- `MemoryService.confirm_memory()` method
- `_pending` dict and preview TTL logic
- Proactive save instructions from MCP `instructions` field

### 5. New Files

- `ingest.py` — HTTP server + `/observe` endpoint
- `worker.py` — background distillation consumer

### 6. Modified Files

- `__main__.py` — starts HTTP server + worker alongside MCP stdio loop
- `settings.py` — `DISTILL_INGEST_PORT` env var
- `server.py` — remove `remember`/`confirm_memory` tools, update instructions

## Privacy

The privacy guarantee is unchanged:

- Hook captures raw tool I/O -> written to local JSONL (never synced)
- Background worker sends raw text to local Ollama only (unless `DISTILLER_PROVIDER=gemini`)
- Scanner runs pre- and post-distillation
- Only distilled, scanned output reaches the team DB
- Raw JSONL entries are local-only, same as existing private_store behavior

There is a new timing consideration: raw text exists in the JSONL queue until the worker processes it. This is identical to the existing private_store behavior during the preview flow.

## Testing Strategy

**Unit tests:**
- Worker processes JSONL entries correctly (mock distiller/embedder/storage)
- Worker handles poison entries (retry 3x, then skip)
- Worker cursor tracking — resumes after restart
- Noise filter rejects junk observations
- Ingest endpoint returns 202 and appends to JSONL

**Integration tests:**
- Full pipeline: POST to `/observe` -> JSONL -> worker -> memory appears in `search_memory`
- Backpressure: burst 20 observations, verify all eventually saved
- Dedup: same observation posted twice, only one memory stored
- Crash recovery: kill process mid-queue, restart, remaining entries processed

**Not tested in CI** (requires Ollama):
- Real distillation throughput
- smollm2-specific edge cases

## Decision Log

| # | Decision | Alternatives | Why |
|---|----------|-------------|-----|
| 1 | Hybrid (hooks + async distill) | Hook-only (no distillation), prompt-only (unreliable) | Privacy-preserving + reliable + no double token cost |
| 2 | Reuse private_store JSONL as queue | In-memory queue, separate SQLite WAL | Already exists, survives crashes |
| 3 | Event-driven worker | Batch on session end, poll on interval | Memories available within same session |
| 4 | Remove `remember` tool entirely | Keep for explicit saves, keep as priority hint | Single path, avoids Claude invoking its own memory system |
| 5 | Capture tool calls only | + Claude responses, everything | Half the volume, decisions visible in tool output |
| 6 | HTTP on localhost | Unix socket, named pipe | Portable, dashboard-extensible, simple curl from hooks |
| 7 | aiohttp on shared event loop | Separate thread, separate process | Simplest, no IPC needed, worker shares MemoryService |

## Assumptions

1. Claude Code hooks can execute shell commands that POST to a local HTTP socket
2. The distill MCP server process is long-lived enough to run a background worker
3. smollm2 on GPU/Silicon handles typical session burst throughput
4. Removing `remember` won't break other MCP clients using distill
5. PostToolUse hook payload includes tool name, input, and output
