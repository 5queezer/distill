# Seed Knowledge Base from Git History

Populate the distill MCP knowledge base from the current repo's git history.
Extracts decisions, patterns, failures, and context from commits and stores
them with correct metadata.

## Prerequisites

- `distill` MCP server running with `remember` and `search_memory` tools available
- Inside a git repository

## Workflow

### 1. Survey the repo

```bash
REPO_NAME=$(basename $(git rev-parse --toplevel))
COMMIT_COUNT=$(git rev-list --count HEAD)
echo "$REPO_NAME: $COMMIT_COUNT commits"
git log --oneline --reverse | head -20
git log --oneline --reverse | tail -20
```

Report the repo name and commit count to the user. Ask if they want to seed
all commits or a date range.

### 2. Process commits in batches of 10

```bash
git log --reverse --format="%H %aI %s" [--since="YYYY-MM-DD"]
```

For each commit:

**Extract the timestamp** — use the commit's author date (`%aI`), NEVER the current time.

**Classify the commit:**

| Type | What to extract | Example |
|------|----------------|---------|
| `decision` | Chose X over Y because Z | "Replaced SQLite with asyncpg for stateless GKE deployment" |
| `pattern` | Recurring convention | "All services use structlog with JSON output to stderr" |
| `failure` | Tried X, abandoned because Y | "Tried Redis for persistence, reverted — too complex for single-node" |
| `dependency` | Service A depends on B | "Parser requires pgvector extension >= 0.5" |
| `context` | Migration/state at a point in time | "Auth middleware rewrite started, driven by compliance requirements" |

**Skip these:**
- `chore:` formatting, linting, dep bumps without rationale
- Merge commits with no original content
- `fix:` typos, whitespace, trivial CI tweaks

**Short commit messages (1-2 lines):** Read the diff — the real decision is in the code.
```bash
git show <hash> --stat
git show <hash> -- <relevant files>
```

**Long/AI-generated messages:** The message IS the knowledge. Skim code only if unclear.

### 3. Call `remember` with correct metadata

Every `remember` call MUST include:
- **content**: The distilled knowledge (what + why, not implementation details)
- **type**: One of decision/pattern/failure/dependency/context
- **repos**: Set to the current repo name

When a later commit revises an earlier decision, reference the evolution:
> "Initially chose SQLite for storage (2024-01). Switched to PostgreSQL + pgvector
(2024-03) to enable stateless deployment on GKE."

When multiple commits build toward a pattern, synthesize into one entry with
the date of the latest commit.

### 4. Spot-check after each batch

After every 10 commits processed, verify the last 3 entries:
```
list_recent(top_k=3)
get_memories(ids=[...])
```

Check that:
- `repos` is set correctly
- `type` is appropriate
- Content captures the WHY, not just the WHAT

If any check fails, fix the entry with `update_memory` before continuing.

### 5. Final verification

After all commits are processed:
```
search_memory("architecture")
search_memory("decisions")
search_memory("patterns")
list_recent(top_k=20)
```

Report to the user:
- Total entries created
- Breakdown by type (decision/pattern/failure/dependency/context)
- Any notable gaps (e.g., no failures recorded, missing early history)
- Sample 2-3 entries for the user to review

## Common mistakes to avoid

1. **Storing implementation details** — "Added postgres_store.py with asyncpg pool" is
useless. "Chose PostgreSQL over SQLite for stateless pod deployment" is valuable.
2. **Missing the WHY** — if the commit message doesn't explain why, check the PR body
or surrounding commits for context.
3. **Not connecting related commits** — a decision and its later reversal should reference
each other.
4. **Over-seeding noise** — skip formatting, linting, and trivial fixes. Quality over quantity.
