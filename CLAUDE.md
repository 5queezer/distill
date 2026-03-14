# Distill — Privacy-first Team Memory MCP Server

## What this is

An MCP server that gives Claude Code access to a shared team knowledge base. Raw developer input is distilled into anonymous factual knowledge by a local LLM (Ollama) before anything leaves the device.

## Core principle

**The local LLM is the privacy component, not an optional feature.** Raw text → Ollama (local) → distilled fact → team DB. The raw text never crosses a network boundary.

## Architecture (Uncle Bob / Clean Architecture)

Dependencies point inward. Business logic has no knowledge of frameworks, databases, or transport.

```
src/distill_mcp/
├── domain/              # Inner ring: pure business logic, no dependencies
│   ├── models.py        # Memory, DistilledMemory, SearchResult (dataclasses/Pydantic)
│   ├── ports.py         # Abstract interfaces (StoragePort, EmbeddingPort, DistillerPort)
│   └── services.py      # Use cases: remember, search, update, forget (depends only on ports)
│
├── adapters/            # Outer ring: implementations of ports
│   ├── storage/
│   │   ├── sqlite_store.py    # StoragePort → SQLite + FTS5 + LanceDB
│   │   └── postgres_store.py  # StoragePort → asyncpg + pgvector + tsvector
│   ├── embeddings/
│   │   ├── ollama_embed.py    # EmbeddingPort → local Ollama
│   │   └── vertex_embed.py    # EmbeddingPort → Vertex AI
│   └── distiller/
│       └── ollama_distill.py  # DistillerPort → local Ollama (always local)
│
├── server.py            # FastMCP tool definitions — thin adapter calling services
├── config.py            # pydantic-settings, env var loading
├── dedup.py             # Cosine similarity > 0.95 check
├── private_store.py     # Raw text → local JSONL (never synced)
├── cli.py               # seed, export commands
└── __main__.py          # Entry point: wires adapters, starts FastMCP
```

**Dependency rule:** `server.py` depends on `domain/services.py`. Services depend on `domain/ports.py`. Adapters implement ports. Nothing in `domain/` imports from `adapters/`.

## FastMCP patterns (PrefectHQ v2)

We use PrefectHQ's FastMCP (`pip install fastmcp`), not the official SDK's built-in FastMCP.

```python
from fastmcp import FastMCP

mcp = FastMCP("distill")

@mcp.tool
def remember(content: str, type: str, repos: list[str], tags: list[str] | None = None) -> dict:
    """Distill raw input into anonymous team knowledge and store it.

    The raw text is processed locally by Ollama and never leaves your device.
    Only the distilled factual output is stored in the team database.
    """
    # delegate to domain service
    return service.remember(content, type, repos, tags)
```

**FastMCP rules:**
- Tools are plain functions decorated with `@mcp.tool` (no parentheses unless passing args)
- Docstrings become tool descriptions — write them for the LLM, not for developers
- Type hints drive the schema. Use `str`, `int`, `list[str]`, `dict`, not complex types
- Return dicts or simple types, not Pydantic models (FastMCP serializes them)
- `mcp.run()` in `__main__.py` — handles stdio transport automatically
- Never print to stdout. FastMCP uses stdout for MCP protocol. Use structlog → stderr.
- Test tools with `fastmcp dev server.py` or `fastmcp install claude-code server.py`

## Domain models (domain/models.py)

```python
@dataclass
class Memory:
    id: str
    content: str          # distilled text only
    type: str             # decision | pattern | failure | dependency | context
    repos: list[str]
    tags: list[str]
    author: str | None    # null=anonymous, hash=pseudonym, name=named
    created_at: datetime

@dataclass
class SearchResult:
    memory: Memory
    score: float          # RRF hybrid score
```

## Ports (domain/ports.py)

```python
class StoragePort(Protocol):
    async def save(self, memory: Memory) -> str: ...
    async def get(self, id: str) -> Memory | None: ...
    async def search(self, query_text: str, query_vec: list[float], top_k: int) -> list[SearchResult]: ...
    async def delete(self, id: str) -> None: ...

class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...

class DistillerPort(Protocol):
    async def distill(self, raw_text: str) -> str: ...
```

## 6 MCP tools (server.py)

| Tool | Purpose | R/W |
|------|---------|-----|
| `remember` | Distill + store | W |
| `search_memory` | Hybrid search (FTS + vector, RRF k=60) | R |
| `get_memory` | By ID | R |
| `update_memory` | Re-distill + supersede | W |
| `list_recent` | Filter by repo/tag/type | R |
| `forget` | Soft-delete | W |

## Two backends

- `BACKEND=local` — SQLite + FTS5 + LanceDB. Ollama for everything. $0.
- `BACKEND=gcp` — Cloud SQL PostgreSQL + pgvector. Vertex AI for embeddings only. Distillation still local Ollama. ~$11/mo.

Backend is selected in `__main__.py` via config, injected into services as ports.

## Distillation rules (adapters/distiller/ollama_distill.py)

The distillation prompt must:
- Remove all first-person language (I, we, my)
- Remove all names of people
- Remove emotional language, blame, frustration
- Replace vague time refs ("yesterday") with approximate dates ("2026-03")
- Keep: technical facts, decisions, reasons, repo names, tech names, version numbers
- Output: 1-3 sentences of pure factual knowledge
- Never add information not in the input

## Privacy constraints — non-negotiable

- Raw text NEVER goes to any cloud service. Only to localhost Ollama.
- `AUTHOR_MODE` env var: `anonymous` (default) | `pseudonym` | `named`. Developer's local choice.
- `REVIEW_BEFORE_SAVE=true` by default. Developer approves distilled output before storing.
- Anthropic only sees distilled search results via Claude Code context window.

## Schema constraints

- All embeddings: 768 dimensions. Hardcoded. Do NOT change without migration.
- `tsvector` uses `'simple'` config by default. Configurable via `FTS_LANGUAGE`.
- Dedup: cosine similarity > 0.95 → reject insert, return existing memory ID.

## Code style

- Lean. Target ~1,100 lines total.
- Type hints everywhere. Pydantic for config, dataclasses for domain models.
- structlog → stderr. Never print to stdout.
- No god objects. Single responsibility per file.
- Adapters are thin. Business logic lives in `domain/services.py`.

## Build & run

```bash
pip install -e ".[dev]"          # install with dev deps
python -m distill_mcp            # run server (stdio)
pytest tests/                    # run tests
fastmcp dev src/distill_mcp/server.py  # test with MCP inspector
fastmcp install claude-code src/distill_mcp/server.py  # install in Claude Code
```

## What NOT to do

- Never send raw developer input to any cloud API
- Never print to stdout (breaks MCP stdio protocol)
- Never hardcode API keys
- Never store author names unless developer opted in via AUTHOR_MODE
- Never skip dedup check on remember
- Never import from adapters/ inside domain/ (dependency rule violation)
- Never put business logic in server.py (it's a thin adapter)
