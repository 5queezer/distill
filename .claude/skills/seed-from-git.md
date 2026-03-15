# Skill: Seed Knowledge Base from Git History

## When to use

When you want to populate the distill knowledge base from an existing repo's git history. Run once per repo.

## Prerequisites

- `distill` MCP server running (`claude mcp add distill ...`)
- The `remember` tool available

## Workflow

### 1. Get the commit list

```bash
git log --oneline --reverse
```

### 2. Process each commit

For each commit, determine the type:

**Short message (human-written, 1-2 lines):**
- Read the diff: `git show <hash> --stat` first, then `git show <hash>` for relevant files
- The real decision is in the code, not the message
- Ask: what was changed, and why?

**Long message (AI-generated, detailed):**
- The message itself is the knowledge. Skim the code only if the message is unclear.
- Extract the decision, not the implementation details.

**Skip these:**
- `chore:` formatting, linting, dependency bumps without context
- Merge commits with no original content
- `fix:` typos, whitespace, CI config tweaks

### 3. Call `remember` for each relevant commit

Use the appropriate type:
- `decision` — "Chose X over Y because Z"
- `pattern` — "All services use X for Y"
- `failure` — "Tried X, abandoned because Y"
- `dependency` — "Service A depends on B's schema v3"
- `context` — "Migration from X to Y in progress as of date"

Set `repos` to the current repo name.

### 4. Connect the dots

When a later commit revises an earlier decision, reference it:
> "Initially chose SQLite for storage. Later switched to PostgreSQL + pgvector to enable stateless deployment on GKE."

When multiple commits build toward a pattern, synthesize:
> "Logging standardized across all services: structlog with JSON output, correlation IDs, stderr only."

### 5. Verify

After processing all commits:
```
search_memory("architecture decisions")
search_memory("patterns")
list_recent(top_k=20)
```

Check that the knowledge base reflects the project's evolution, not just isolated facts.

## Example

Commit: `feat: replace SQLite with asyncpg for GCP deployment`

Diff shows: removed sqlite_store.py, added postgres_store.py, updated config.py with DB_HOST env var.

→ `remember`:
- content: "Replaced SQLite with PostgreSQL + pgvector to enable stateless pod deployment on GKE. SQLite required PVC with ReadWriteOnce, limiting to single replica."
- type: "decision"
- repos: ["distill"]

## Tips

- Process 5-10 commits at a time if the repo is large
- Prioritize commits that changed architecture, added dependencies, or removed code
- Removal commits are often the most valuable — they document what didn't work
- Tag-based filtering: `git log --oneline --reverse --grep="feat\|fix\|refactor"` to skip noise
