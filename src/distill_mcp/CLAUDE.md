# FastMCP patterns (PrefectHQ v2)

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

## 8 MCP tools (server.py)

| Tool | Purpose | R/W |
|------|---------|-----|
| `remember` | Distill + store (returns preview for approval) | W |
| `confirm_memory` | Confirm pending preview, store it | W |
| `search_memory` | Hybrid search (FTS + vector, RRF k=60) | R |
| `get_memories` | Fetch full content by IDs (batch) | R |
| `get_memory` | By ID | R |
| `update_memory` | Re-distill + supersede | W |
| `list_recent` | Filter by repo/tag/type | R |
| `forget` | Soft-delete | W |

## Three independent axes

- `BACKEND` — storage: `local` (SQLite + LanceDB) or `postgres` (PostgreSQL + pgvector)
- `EMBEDDING_PROVIDER` — embeddings: `ollama` | `gemini` | `vertex` | `bedrock` | `azure`
- `DISTILLER_PROVIDER` — distillation: `ollama` | `gemini`

All three are selected in `__main__.py` via config, injected into services as ports.

## Code style

- Lean. Target ~1,100 lines total.
- Type hints everywhere. Pydantic for config, dataclasses for domain models.
- structlog → stderr. Never print to stdout.
- No god objects. Single responsibility per file.
- Adapters are thin. Business logic lives in `domain/services.py`.
