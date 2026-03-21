# Distill — Privacy-first Team Memory MCP Server

## What this is

An MCP server that gives Claude Code access to a shared team knowledge base. Raw developer input is distilled into anonymous factual knowledge by an LLM before being stored.

## Core principle

**By default, the local LLM is the privacy component.** Raw text → Ollama (local) → distilled fact → team DB. Three independent axes: `BACKEND` (storage), `EMBEDDING_PROVIDER`, `DISTILLER_PROVIDER`. Setting `DISTILLER_PROVIDER=gemini` sends raw text to Google instead of keeping it local.

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
│   │   ├── vertex_embed.py    # EmbeddingPort → Vertex AI
│   │   └── gemini_embed.py    # EmbeddingPort → Gemini API
│   └── distiller/
│       ├── ollama_distill.py  # DistillerPort → local Ollama
│       └── gemini_distill.py  # DistillerPort → Gemini API
│
├── server.py            # FastMCP tool definitions — thin adapter calling services
├── config.py            # pydantic-settings, env var loading
├── dedup.py             # Cosine similarity > 0.95 check
├── private_store.py     # Raw text → local JSONL (never synced)
├── cli.py               # seed, export commands
└── __main__.py          # Entry point: wires adapters, starts FastMCP
```

**Dependency rule:** `server.py` depends on `domain/services.py`. Services depend on `domain/ports.py`. Adapters implement ports. Nothing in `domain/` imports from `adapters/`.

## Build & run

```bash
uv sync                          # install all deps
python -m distill_mcp            # run server (stdio)
uv run pytest tests/             # run tests (Ollama tests auto-skip if not running)
fastmcp dev inspector src/distill_mcp/server.py  # test with MCP inspector
fastmcp install claude-code src/distill_mcp/server.py  # install in Claude Code
```

## Development workflow

Every code change follows this sequence. Do not skip steps.

1. **Branch** — Create a feature branch from `main`: `git checkout -b feat/<name> main` or `git checkout -b fix/<name> main`.
2. **Code** — Make changes. Keep commits small and focused.
3. **Commit** — `git commit`. Pre-commit hooks run automatically:
   - trailing-whitespace, end-of-file-fixer, check-yaml, check-toml
   - no-commit-to-branch (blocks direct commits to `main`)
   - validate-pyproject
   - ruff (lint + auto-fix) and ruff-format
   - ty (type check via `uvx ty check src/`)
   - gitleaks (secret scanning)
   If any hook fails: fix the issue, re-stage, and commit again (new commit, do not amend).
4. **Push** — `git push -u origin <branch>`. Pre-push hook runs `uv run pytest` (including coverage).
5. **PR** — Open a pull request against `main`.
6. **CI** — GitHub Actions runs on every push and PR (`.github/workflows/ci.yml`):
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run pytest tests/ -x -v -k "not ollama" --no-cov`
   Ollama-dependent tests are marked with `@pytest.mark.ollama` and skipped in CI (no Ollama on Ubuntu runners). They run locally only.
7. **Green gate** — CI must be green before merging. If CI fails: read the logs, fix locally, push again. Repeat until green.
8. **Merge** — Squash-merge into `main` via GitHub.

## What NOT to do

- Never send raw developer input to a cloud API unless the user opted in via `DISTILLER_PROVIDER=gemini`
- Never print to stdout (breaks MCP stdio protocol)
- Never hardcode API keys
- Never store author names unless developer opted in via AUTHOR_MODE
- Never skip dedup check on remember
- Never import from adapters/ inside domain/ (dependency rule violation)
- Never put business logic in server.py (it's a thin adapter)

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **distill** (315 symbols, 765 relationships, 17 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/distill/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/distill/context` | Codebase overview, check index freshness |
| `gitnexus://repo/distill/clusters` | All functional areas |
| `gitnexus://repo/distill/processes` | All execution flows |
| `gitnexus://repo/distill/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## CLI

- Re-index: `npx gitnexus analyze`
- Check freshness: `npx gitnexus status`
- Generate docs: `npx gitnexus wiki`

<!-- gitnexus:end -->
