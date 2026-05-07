---
title: CLI Commands
---

# CLI Commands

Distill provides CLI commands for administration tasks. All commands are run via the `distill_mcp` module:

```bash
python -m distill_mcp <command> [options]
```

Running without a command starts the MCP server (the default mode).

## check-hardware

Detect GPU and hardware capabilities for Ollama performance tuning.

```bash
python -m distill_mcp check-hardware
```

Outputs a report of detected GPUs, VRAM, CPU cores, and RAM. Useful for verifying that Ollama will use GPU acceleration.

## reembed

Rebuild all vector embeddings when switching embedding models. Backs up the existing LanceDB vectors before rebuilding.

```bash
python -m distill_mcp reembed
```

Use this when:

- You've changed `EMBEDDING_PROVIDER` or `EMBEDDING_MODEL`
- The server fails to start with an "Embedding dimension mismatch" error
- You want to upgrade to a better embedding model

The command:

1. Backs up `~/.team-memory/lance/` to `lance.bak.<dim>/`
2. Drops the existing vectors table
3. Re-embeds every memory with the current embedding model
4. Updates the stored embedding metadata

## seed

Populate the knowledge base from git history. Requires the distill MCP server to be running (it POSTs to the ingest endpoint).

```bash
python -m distill_mcp seed [--since <date>] [--port <port>]
```

| Option | Description |
|--------|-------------|
| `--since <date>` | Only process commits after this date (passed to `git log --since`) |
| `--port <port>` | Ingest endpoint port (default: from `INGEST_PORT` setting, usually `21746`) |

The command reads `git log`, filters out trivial commits (chore, style, ci, merge, fixup, squash), and POSTs each remaining commit to the `/observe` endpoint for distillation by the background worker.

Must be run inside a git repository. The repository name is derived from the `origin` remote URL.

See the [Seed from Git](../how-to/seed-from-git.md) how-to guide for a walkthrough.

## export

Export memories to JSON or CSV.

```bash
python -m distill_mcp export [--format json|csv] [--output <file>] [--repo <name>] [--type <type>] [--after <date>]
```

| Option | Description |
|--------|-------------|
| `--format json\|csv` | Output format (default: `json`) |
| `--output <file>` | Write to file instead of stdout |
| `--repo <name>` | Filter by repository name |
| `--type <type>` | Filter by memory type (`decision`, `context`, `failure`, `pattern`, `dependency`) |
| `--after <date>` | Only export memories created after this ISO 8601 date |

Examples:

```bash
# Export all memories as JSON to stdout
python -m distill_mcp export

# Export decisions from a specific repo to a file
python -m distill_mcp export --format csv --repo myapp --type decision --output decisions.csv

# Export everything since March 2026
python -m distill_mcp export --after 2026-03-01 --output recent.json
```
