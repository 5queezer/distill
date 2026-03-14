# Distill — Privacy-first Team Memory MCP Server

## What this is

An MCP server that gives Claude Code access to a shared team knowledge base. Raw developer input is distilled into anonymous factual knowledge by a local LLM (Ollama) before anything leaves the device. Only the distilled output is stored in the team database.

## Core principle

**The local LLM is the privacy component, not an optional feature.** Raw text → Ollama (local) → distilled fact → team DB. The raw text never crosses a network boundary.

## Architecture

```
Developer types raw thought
  → MCP server (local, stdio)
    → saves raw to ~/.distill/private/ (optional)
    → sends to Ollama localhost for distillation
    → receives clean factual text back
    → shows developer for review (default: on)
    → embeds distilled text
    → stores in team DB (SQLite local or Cloud SQL)
```

## Two backends, same interface

- `BACKEND=local` — SQLite + FTS5 + LanceDB. Ollama for everything. $0. For solo dev.
- `BACKEND=gcp` — Cloud SQL PostgreSQL + pgvector. Vertex AI for embeddings only. Distillation still local Ollama. ~$11/mo. For team.

## 6 MCP tools

All tools are in `server.py`. Backend-agnostic via abstract interface in `storage/base.py`.

| Tool | Purpose | R/W |
|------|---------|-----|
| `remember` | Distill + store | W |
| `search_memory` | Hybrid search (FTS + vector, RRF k=60) | R |
| `get_memory` | By ID | R |
| `update_memory` | Re-distill + supersede | W |
| `list_recent` | Filter by repo/tag/type | R |
| `forget` | Soft-delete | W |

## Key files

| File | Purpose |
|------|---------|
| `__main__.py` | FastMCP entry point, backend selection |
| `server.py` | 6 tool definitions, backend-agnostic |
| `distill.py` | **The most important file.** Ollama distillation prompt + call + validation. |
| `private_store.py` | Raw text → local JSONL |
| `dedup.py` | Cosine similarity > 0.95 check before insert |
| `storage/base.py` | Abstract storage interface |
| `storage/local.py` | SQLite + FTS5 + LanceDB |
| `storage/gcp.py` | asyncpg + pgvector + tsvector |
| `embeddings/ollama_embed.py` | Local Ollama embeddings |
| `embeddings/vertex_embed.py` | Vertex AI embeddings |
| `config.py` | pydantic-settings, all env vars |
| `cli.py` | seed, export commands |

## Tech stack

- **MCP:** FastMCP (Python MCP SDK), stdio transport
- **Distillation:** Ollama `gemma3:4b` on Apple Silicon (always local)
- **Embeddings (local):** Ollama `nomic-embed-text` (768 dims)
- **Embeddings (GCP):** Vertex AI `text-embedding-005` (768 dims)
- **DB (local):** sqlite3 + FTS5, LanceDB
- **DB (GCP):** asyncpg, Cloud SQL PostgreSQL 16 + pgvector
- **Retry:** tenacity
- **Logging:** structlog → stderr (MCP stdio requirement: never print to stdout)
- **Config:** pydantic-settings

## Distillation prompt rules

The prompt in `distill.py` must:
- Remove all first-person language (I, we, my)
- Remove all names of people
- Remove emotional language, blame, frustration
- Replace vague time refs ("yesterday") with approximate dates ("2026-03")
- Keep: technical facts, decisions, reasons, repo names, tech names, version numbers
- Output: 1-3 sentences of pure factual knowledge
- Never add information not in the input
- Never hallucinate

## Privacy constraints

- Raw text NEVER goes to any cloud service. Only to localhost Ollama.
- Author field is nullable. Controlled by `AUTHOR_MODE` env var (anonymous/pseudonym/named). Default: anonymous.
- `REVIEW_BEFORE_SAVE=true` by default. Developer sees and approves distilled output before it's stored.
- Anthropic only sees distilled search results (via Claude Code context window). Never raw input.

## Schema constraints

- All embeddings are 768 dimensions. Hardcoded in schema. Do NOT use models with different dims without a migration.
- `tsvector` uses `'simple'` config by default (language-agnostic). Configurable via `FTS_LANGUAGE`.
- Deduplication: cosine similarity > 0.95 → reject insert, return existing memory ID.

## Code style

- Keep it lean. ~1,100 lines total target.
- No unnecessary abstractions. Direct, readable code.
- Type hints everywhere. Pydantic models for config.
- structlog for logging, always to stderr.
- Tests in `tests/`. Distillation quality tests are the most critical.

## Build commands

```bash
# Install dev
pip install -e ".[dev]"

# Run locally
python -m distill_mcp

# Run tests
pytest tests/

# Add to Claude Code
claude mcp add distill -- python -m distill_mcp
```

## What NOT to do

- Never send raw developer input to any cloud API
- Never print to stdout (breaks MCP stdio)
- Never hardcode API keys
- Never store author names unless the developer explicitly opted in
- Never skip the dedup check on remember
