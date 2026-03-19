# Seed from Git History

Populate your distill knowledge base from an existing repository's git history. This extracts decisions, patterns, failures, and context from commits.

## Prerequisites

- distill MCP server running
- Inside a git repository with commits

## Quick start

### Option 1: CLI (recommended)

```bash
distill seed
```

This prints the seeding workflow for your AI assistant to follow. Pipe it into your agent or copy-paste it into a conversation.

### Option 2: Claude Code skill

If you have the distill skills installed in Claude Code, use the `/seed` command directly in your conversation.

## How it works

The seed workflow:

1. **Surveys** your repo — counts commits, shows first and last 20
2. **Processes** commits in batches of 10
3. **Classifies** each commit as decision, pattern, failure, dependency, or context
4. **Stores** distilled knowledge via the `remember` tool
5. **Verifies** entries after each batch

## What gets extracted

| Type | What to extract | Example |
|------|----------------|---------|
| `decision` | Chose X over Y because Z | "Replaced SQLite with asyncpg for stateless GKE deployment" |
| `pattern` | Recurring convention | "All services use structlog with JSON output to stderr" |
| `failure` | Tried X, abandoned because Y | "Tried Redis for persistence, reverted — too complex for single-node" |
| `dependency` | Service A depends on B | "Parser requires pgvector extension >= 0.5" |
| `context` | Migration/state at a point in time | "Auth middleware rewrite started, driven by compliance requirements" |

## What gets skipped

- `chore:` formatting, linting, dep bumps without rationale
- Merge commits with no original content
- `fix:` typos, whitespace, trivial CI tweaks

## Tips

- **Quality over quantity** — skip noise, capture reasoning
- **Capture the WHY** — "added postgres_store.py" is useless; "chose PostgreSQL for stateless deployment" is valuable
- **Connect related commits** — a decision and its later reversal should reference each other
- **Use date ranges** — for large repos, seed in chunks with `--since`
