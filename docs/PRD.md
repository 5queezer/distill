# PRD v3.2 — Team Memory MCP Server

**Privacy-first shared knowledge base for teams using Claude Code across multiple repos. Raw thoughts stay on your device. Only distilled knowledge reaches the team.**

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Owner** | [Architect] |
| **Updated** | 2026-03-14 |

---

## 1. Problem

Two problems, not one.

**Problem A (context loss):** Claude Code's memory is per-repo and per-developer. Claude re-discovers patterns, re-proposes rejected approaches, and has zero awareness of cross-repo dependencies.

**Problem B (privacy fear):** Any shared knowledge base triggers the same reaction: "You want me to store my thoughts in a database everyone can read?" Developers won't contribute honest, useful knowledge — especially failed approaches — if their name is attached and their exact words are visible.

Both problems must be solved together, or the knowledge base stays empty.

## 2. Core Idea: Knowledge Distillation as Privacy

The developer writes freely. A local LLM on their Mac transforms the raw input into depersonalized, factual team knowledge *before* it leaves the device. Only the distillat reaches the team database.

```
Developer types:                     Team database receives:
─────────────────                    ────────────────────────
"I spent 3 days trying to get        "Redis pub/sub is unsuitable for
 Redis pub/sub working for the        the event-bus use case in
 event bus and it's absolute          notification-service due to
 garbage. Messages just vanish        message loss under high load.
 under load. Bob suggested            Alternative: evaluate Kafka or
 Kafka but I ignored him.             NATS. (Q1 2026)"
 Should have listened."
```

No author. No frustration. No "I". No "Bob". Just a clean, reusable fact.

### 2.1 Privacy Guarantees

| Guarantee | How |
|-----------|-----|
| Raw text never leaves the device | Distillation runs locally on Ollama (Apple Silicon Mac). No cloud call. |
| Author attribution is developer's choice | Each developer configures `AUTHOR_MODE` locally: `anonymous` (default), `pseudonym` (consistent hash like `dev-7f3a`), or `named`. No team-wide policy — no social pressure. |
| No personal language in team DB | The distillation prompt explicitly strips first-person, blame, emotion, and names of people. |
| Anthropic never sees the raw text | Claude Code only receives search *results* (already distilled). The raw input goes to local Ollama, not to Claude. |
| Developer reviews before sharing | `REVIEW_BEFORE_SAVE=true` by default. Every distilled memory is shown for approval before it enters the team DB. Nothing goes out without consent. |
| Local private memory is optional | Developers can keep their raw notes locally for personal reference. This never syncs. |

### 2.2 What the team DB stores

| Type | Example (distilled) |
|------|---------------------|
| **Decisions** | "SQLAlchemy was chosen over Django ORM for repo-X due to async requirements. (2025-11)" |
| **Failed approaches** | "Redis pub/sub evaluated for event-bus in notification-service. Rejected: message loss under load. (2026-01)" |
| **Cross-repo links** | "billing-service depends on auth-service UserSchema v3. Breaking changes require coordinated deploy." |
| **Patterns** | "All services use structured logging with correlation IDs. Reference implementation: shared-utils/logging." |
| **Context snapshots** | "REST-to-gRPC migration in progress. auth-service complete, billing-service in progress. (Sprint 14)" |

### 2.3 What it does NOT store

Source code, chat history, credentials, PII, author names, personal opinions, blame.

---

## 3. How It Works

```
┌─ Developer's Mac ─────────────────────────────────────┐
│                                                        │
│  Claude Code                                           │
│    │                                                   │
│    ├─► remember("I tried Redis pub/sub and it...")     │
│    │       │                                           │
│    │       ▼                                           │
│    │   ┌──────────────────────────┐                    │
│    │   │  MCP Server (local)      │                    │
│    │   │                          │                    │
│    │   │  1. Save raw text to     │                    │
│    │   │     local private store  │                    │
│    │   │     (~/.team-memory/     │                    │
│    │   │      private/)           │                    │
│    │   │                          │                    │
│    │   │  2. Send raw text to     │                    │
│    │   │     Ollama (localhost)   │                    │
│    │   │     for distillation     │                    │
│    │   │                          │                    │
│    │   │  3. Receive distilled    │                    │
│    │   │     knowledge back       │                    │
│    │   │                          │                    │
│    │   │  4. Embed distilled text │──── (distilled ───►│── Team DB
│    │   │     + store in team DB   │      text only)    │   (Cloud SQL)
│    │   └──────────────────────────┘                    │
│    │                                                   │
│    ├─► search_memory("Redis event bus")               │
│    │       │                                           │
│    │       ▼                                           │
│    │   Team DB returns distilled results               │
│    │   (no author, no raw text, no PII)                │
│    │       │                                           │
│    │       ▼                                           │
│    │   Claude sees: "Redis pub/sub unsuitable for      │
│    │   event-bus due to message loss under load."      │
│    │                                                   │
└────┴───────────────────────────────────────────────────┘
```

**Key flow:** Raw text → Ollama (local) → distilled knowledge → Team DB. The raw text never crosses a network boundary.

---

## 4. Distillation

### 4.1 The Distillation Prompt

```
You are a knowledge distillation engine for a software team.

Transform the developer's raw input into a clean, factual, reusable
piece of team knowledge.

Rules:
- Remove all first-person language ("I", "we", "my")
- Remove all names of people
- Remove emotional language, blame, frustration, opinions about people
- Remove temporal references like "yesterday", "last week" — use
  approximate dates like "(Q1 2026)" or "(2026-03)" instead
- Keep: technical facts, decisions, reasons, constraints, repo names,
  technology names, version numbers, performance data
- Output format: 1-3 sentences of pure factual knowledge
- If the input contains a decision, state what was chosen and why
- If the input contains a failure, state what was tried, what failed,
  and why
- If the input describes a dependency, state which repos/services are
  connected and how
- Do NOT add information that wasn't in the input
- Do NOT ask questions
- Do NOT use markdown formatting
```

### 4.2 Distillation Model

| Parameter | Value |
|-----------|-------|
| Runtime | Ollama on Apple Silicon (local, no cloud) |
| Default model | `gemma3:4b` |
| Alternatives | `phi4-mini`, `llama3.2:3b`, `qwen2.5:3b` |
| Latency | < 2s on M2/M3/M4 for typical input |
| Max input | 8,000 chars (truncated if longer) |
| Privacy | Raw text never leaves localhost |

### 4.3 Distillation Quality

The distillation prompt is the most important piece of the system. Quality criteria:

| Criterion | Test |
|-----------|------|
| No PII leaks | Input with names → output must contain zero names |
| No first-person | Input with "I"/"we" → output must be impersonal |
| Fact preservation | Key technical facts from input must appear in output |
| Conciseness | Output ≤ 3 sentences for typical input |
| No hallucination | Output must not add facts not present in input |

A test suite of 50 input/output pairs validates these criteria. Runs in CI.

### 4.4 Developer Review (Default: ON)

Before committing to the team DB, the developer reviews the distilled output:

```
Developer: remember("I tried Redis pub/sub and it's garbage...")

Claude: I've distilled this into team knowledge:

  "Redis pub/sub evaluated for event-bus in notification-service.
   Rejected: message loss under load. (2026-03)"

  Should I save this to the team knowledge base?
```

Review is **on by default** (`REVIEW_BEFORE_SAVE=true`). This solves both the quality problem (developer catches bad distillations) and the trust problem (nothing leaves without explicit consent). Can be disabled by developers who trust the distillation quality after regular use.

---

## 5. MCP Tools

Six tools. The interface is the same as v3.1; the privacy layer is internal.

| Tool | Purpose | R/W |
|------|---------|-----|
| `remember` | Distill raw input → save anonymized knowledge to team DB | W |
| `search_memory` | Hybrid search across team knowledge | R |
| `get_memory` | Retrieve by ID | R |
| `update_memory` | Amend or supersede (re-distills if raw text provided) | W |
| `list_recent` | Recent memories, filterable by repo/tag/type | R |
| `forget` | Soft-delete | W |

### 5.1 `remember` Schema

**Input:**

| Field | Type | Notes |
|-------|------|-------|
| `content` | str | Raw developer input. Max 8,000 chars. Processed locally, never stored in team DB. |
| `type` | enum | `decision` / `pattern` / `failure` / `dependency` / `context` |
| `repos` | list[str] | GitHub repos this applies to |
| `tags` | list[str] | Max 10 |

**No `author` in input.** Attribution is controlled by the local `AUTHOR_MODE` setting:

| Mode | What's stored in team DB | Config |
|------|--------------------------|--------|
| `anonymous` (default) | No author field | `AUTHOR_MODE=anonymous` |
| `pseudonym` | Consistent hash, e.g. `dev-7f3a` | `AUTHOR_MODE=pseudonym` |
| `named` | Developer's real name | `AUTHOR_MODE=named` |

Each developer chooses their own mode. No team-wide policy. The setting is local and invisible to others.

**Output:**

| Field | Type |
|-------|------|
| `memory_id` | str |
| `distilled_content` | str (what was actually saved — shown for review) |
| `needs_confirmation` | bool (true when `REVIEW_BEFORE_SAVE=true`) |
| `created_at` | datetime? (null until confirmed) |
| `duplicate_of` | str? (if near-duplicate detected) |

**Behavior:**
1. Raw text saved to local private store (if `KEEP_PRIVATE_COPY=true`).
2. Raw text sent to local Ollama for distillation.
3. **Review step** (default on): distilled text shown to developer. Claude asks for confirmation. Developer can accept, reject, or ask Claude to re-distill. If `REVIEW_BEFORE_SAVE=false`, skip to step 4.
4. Distilled text embedded via Ollama (local) or Vertex AI (GCP mode).
5. Deduplication check: cosine similarity > 0.95 → return existing memory.
6. Distilled text + embedding + metadata + author (per `AUTHOR_MODE`) saved to team DB.

### 5.2 `search_memory` Output

| Field | Type |
|-------|------|
| `memory_id` | str |
| `content` | str (distilled) |
| `type` | str |
| `repos` | list[str] |
| `tags` | list[str] |
| `score` | float |
| `author` | str? (null if anonymous, pseudonym if pseudonym, name if named) |
| `created_at` | datetime |

The `author` field is nullable. Anonymous memories return `null`. Pseudonymous memories return a consistent hash. Named memories return the real name.

---

## 6. Two Deployment Modes

```
┌─────────────────────────────────────────────────────────┐
│                    FastMCP Server                        │
│              (6 tools, same interface)                   │
│                                                         │
│    ┌───────────────────────────────────────────────┐    │
│    │         Distillation Layer (always local)      │    │
│    │         Ollama on Apple Silicon                │    │
│    │         Raw text → anonymous fact              │    │
│    └───────────────────────────────────────────────┘    │
│                          │                              │
│                   distilled text only                    │
│                          │                              │
│    ┌─────────────┐       │       ┌─────────────────┐    │
│    │ StorageLocal │       │       │ StorageGCP      │    │
│    │ SQLite FTS5  │◄──────┴──────►│ Cloud SQL       │    │
│    │ LanceDB      │              │ pgvector        │    │
│    └─────────────┘              └─────────────────┘    │
│         ▲                              ▲                │
│     BACKEND=local                  BACKEND=gcp          │
└─────────────────────────────────────────────────────────┘
```

**Critical:** Distillation always runs locally, regardless of backend. Even in GCP mode, the MCP server runs on the developer's Mac (stdio transport to Claude Code), distills locally, and only sends the distilled result to Cloud SQL.

### 6.1 Local Mode (solo dev, prototyping)

| Component | Technology |
|-----------|-----------|
| Distillation | Ollama `gemma3:4b` (local) |
| Embeddings | Ollama `nomic-embed-text` (local) |
| Team DB | SQLite + FTS5 + LanceDB (local files) |
| Transport | stdio |

```bash
pip install team-memory-mcp
ollama pull gemma3:4b
ollama pull nomic-embed-text
claude mcp add team-memory -- python -m team_memory_mcp
```

### 6.2 GCP Mode (team deployment)

| Component | Technology |
|-----------|-----------|
| Distillation | Ollama `gemma3:4b` (local on each developer's Mac) |
| Embeddings | Vertex AI `text-embedding-005` (GCP) — receives only distilled text |
| Team DB | Cloud SQL PostgreSQL 16 + pgvector (GCP) |
| Transport | stdio locally, MCP server connects to Cloud SQL via Cloud SQL Proxy |

**Architecture change from v3.1:** The MCP server is no longer a centralized deployment on GKE. It runs **locally on each developer's Mac** (because distillation must be local). It connects directly to Cloud SQL via the Cloud SQL Auth Proxy.

```
┌─ Developer's Mac ──────────────────────┐
│  Claude Code ──► MCP Server (stdio)    │
│                    │                    │
│                    ├─► Ollama (local)   │
│                    │   (distillation)   │
│                    │                    │
│                    ├─► Cloud SQL Proxy  │──► Cloud SQL (private IP)
│                    │   (distilled text) │
│                    │                    │
│                    └─► Vertex AI        │──► Embedding API
│                        (distilled text) │    (GCP-internal)
└─────────────────────────────────────────┘
```

```bash
pip install team-memory-mcp

# Authenticate to GCP
gcloud auth application-default login

# Start Cloud SQL Proxy (background)
cloud-sql-proxy PROJECT:REGION:team-memory-db &

# Add to Claude Code
claude mcp add team-memory \
  -e BACKEND=gcp \
  -e DB_HOST=127.0.0.1 \
  -e DB_NAME=team_memory \
  -e GCP_PROJECT=your-project \
  -- python -m team_memory_mcp
```

### 6.3 What happened to the GKE deployment?

Dropped. The privacy model requires distillation on the developer's device. A centralized server would need to receive raw text over the network, which defeats the purpose. The MCP server is now a local process that connects to a remote database.

GKE is still used for Cloud SQL (managed PostgreSQL). The compute moved to the developer's Mac.

---

## 7. Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `BACKEND` | `local` | `local` or `gcp` |
| `DATA_DIR` | `~/.team-memory` | Local data (private store + SQLite/LanceDB in local mode) |
| `KEEP_PRIVATE_COPY` | `true` | Save raw text locally before distillation |
| `REVIEW_BEFORE_SAVE` | `true` | Show distilled text for approval before saving. Default on for trust + quality. |
| `AUTHOR_MODE` | `anonymous` | `anonymous` (no attribution), `pseudonym` (consistent hash like `dev-7f3a`), or `named` (real name). Each developer chooses locally. |
| `AUTHOR_NAME` | `$USER` | Used when `AUTHOR_MODE=named`. |
| `DISTILL_MODEL` | `gemma3:4b` | Ollama model for distillation. Always local. |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` (local) or `vertex` (GCP) |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Must produce 768 dims |
| `FTS_LANGUAGE` | `simple` | FTS stemmer. `simple` = language-agnostic. |
| `RRF_K` | `60` | RRF smoothing constant |
| `MAX_MEMORY_SIZE` | `8000` | Max chars per raw input |
| `DB_HOST` | `127.0.0.1` | Cloud SQL Proxy address (GCP mode) |
| `DB_NAME` | `team_memory` | PostgreSQL database (GCP mode) |
| `GCP_PROJECT` | — | GCP project ID (GCP mode) |
| `GCP_LOCATION` | `us-central1` | Vertex AI region (GCP mode) |

---

## 8. Data Models

### 8.1 Team Database — SQLite (local mode)

```sql
CREATE TABLE memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,       -- distilled text only, never raw
    type        TEXT NOT NULL CHECK(type IN ('decision','pattern','failure','dependency','context')),
    repos       TEXT NOT NULL DEFAULT '[]',
    tags        TEXT DEFAULT '[]',
    author      TEXT,                -- null (anonymous), hash (pseudonym), or name. Developer's choice.
    created_at  TEXT NOT NULL,
    updated_at  TEXT,
    supersedes  TEXT,
    deleted_at  TEXT
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, tags,
    tokenize='unicode61'
);
```

`author` is nullable. Most memories will have `null` (anonymous default).

### 8.2 Team Database — PostgreSQL (GCP mode)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL,       -- distilled text only, never raw
    type        TEXT NOT NULL CHECK(type IN ('decision','pattern','failure','dependency','context')),
    repos       JSONB NOT NULL DEFAULT '[]',
    tags        JSONB DEFAULT '[]',
    author      TEXT,                -- null (anonymous), hash (pseudonym), or name
    embedding   vector(768),
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('simple', content)
                ) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    supersedes  UUID REFERENCES memories(id),
    deleted_at  TIMESTAMPTZ
);

CREATE INDEX idx_memories_embedding ON memories
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_memories_tsv ON memories USING gin (tsv);
CREATE INDEX idx_memories_repos ON memories USING gin (repos);
CREATE INDEX idx_memories_type ON memories (type);
CREATE INDEX idx_memories_created ON memories (created_at DESC);
```

`author` is nullable. No index on it — anonymous is the expected default.

### 8.3 Private Local Store

```
~/.team-memory/
├── private/
│   └── raw_memories.jsonl     # developer's raw inputs (never synced)
├── memories.db                # SQLite team DB (local mode only)
└── lancedb/                   # LanceDB vectors (local mode only)
```

The `private/` directory is the developer's personal journal. It's never read by the team tools, never synced, never backed up by the system. It exists purely so the developer can grep their own history.

### 8.4 Hybrid Search (RRF) — unchanged from v3.1

Same SQL for GCP mode. Same Python implementation for local mode. k=60. The only difference: the content being searched is already distilled, so search quality is actually *better* because the text is clean, consistent, and jargon-free.

---

## 9. Technology Stack

### 9.1 Shared (both modes)

| Component | Technology |
|-----------|-----------|
| MCP Framework | `FastMCP` (Python MCP SDK), stdio transport |
| Distillation | Ollama (always local, Apple Silicon) |
| Retry | `tenacity` |
| Logging | `structlog` → stderr |
| Config | `pydantic-settings` |

### 9.2 Local mode

| Component | Technology |
|-----------|-----------|
| Embeddings | Ollama `nomic-embed-text` |
| DB | `sqlite3` + FTS5 |
| Vector store | `lancedb` |

### 9.3 GCP mode

| Component | Technology |
|-----------|-----------|
| Embeddings | Vertex AI `text-embedding-005` (768 dims) — receives distilled text only |
| DB | Cloud SQL PostgreSQL 16 + pgvector via `asyncpg` |
| DB access | Cloud SQL Auth Proxy (runs on developer's Mac) |
| Auth (GCP) | `gcloud auth application-default login` (developer's own GCP identity) |

---

## 10. Resilience

| Failure | Behavior |
|---------|----------|
| Ollama not running | `remember` fails with clear error: "Start Ollama to enable knowledge distillation." Search still works. |
| Ollama slow (>5s) | Timeout configurable. Default 10s. Shows progress indicator. |
| Distillation produces poor output | Developer reviews and rejects (if `REVIEW_BEFORE_SAVE=true`). Or re-runs with different model. |
| Cloud SQL unreachable (GCP mode) | All tools return error. Developer switches to local mode. |
| Embedding API down (GCP mode) | Search falls back to keyword-only (FTS). |
| Dedup check fails | Insert proceeds with warning. |

---

## 11. Testing Strategy

**Distillation quality (most critical):**
- 50 input/output pairs testing: no PII leakage, no first-person, fact preservation, conciseness, no hallucination.
- Automated via LLM-as-judge (local Ollama) + regex checks for names/pronouns.
- Runs in CI against `gemma3:4b` and at least one alternative model.

**Storage + search:** RRF scoring, CRUD, dedup. Both backends.

**MCP compliance:** stdio connection, call each tool, verify protocol.

**Retrieval quality:** 100 query–memory pairs. NDCG@10 ≥ 0.75. Both backends.

---

## 12. Project Structure

```
team-memory-mcp/
├── pyproject.toml
├── sql/
│   ├── schema_local.sql
│   └── schema_gcp.sql
├── src/
│   └── team_memory_mcp/
│       ├── __main__.py              # FastMCP entry point (stdio)
│       ├── server.py                # 6 MCP tool definitions
│       ├── distill.py               # Ollama distillation (the privacy engine)
│       ├── private_store.py         # Raw text → local JSONL
│       ├── dedup.py                 # Cosine similarity check
│       ├── storage/
│       │   ├── base.py              # Abstract storage interface
│       │   ├── local.py             # SQLite + FTS5 + LanceDB
│       │   └── gcp.py              # asyncpg + pgvector
│       ├── embeddings/
│       │   ├── ollama_embed.py      # Local Ollama embeddings
│       │   └── vertex_embed.py      # Vertex AI embeddings
│       ├── config.py                # pydantic-settings
│       └── cli.py                   # seed, export commands
├── tests/
│   ├── test_distill.py              # Distillation quality suite
│   ├── test_storage_local.py
│   ├── test_storage_gcp.py
│   ├── test_search.py
│   ├── test_dedup.py
│   ├── test_tools.py
│   ├── distill_golden.json          # 50 input→expected output pairs
│   └── search_golden.json           # 100 query→memory pairs
└── README.md
```

~1,100 lines of Python. `distill.py` is ~80 lines (prompt + Ollama call + validation).

---

## 13. Fastest Path

### Phase 1: Local MVP (Week 1) — on your Mac

| Day | Deliverable |
|-----|------------|
| 1 | `config.py`, `distill.py` (Ollama distillation + prompt), `private_store.py` |
| 2 | `local.py` — SQLite CRUD + FTS5 + LanceDB + RRF in Python |
| 3 | `dedup.py`. `server.py` — all 6 tools. `__main__.py` — FastMCP stdio. |
| 4 | Wire into Claude Code. Test full flow: `remember` → distill → store → `search_memory`. |
| 5 | `test_distill.py` with 50 golden pairs. Fix prompt until all pass. Dogfood. |

**End of week 1:** Working private knowledge base on your Mac. $0 cost.

### Phase 2: GCP Backend (Week 2)

| Day | Deliverable |
|-----|------------|
| 6 | `vertex_embed.py`. `gcp.py` — asyncpg CRUD + RRF SQL. |
| 7 | Cloud SQL setup + schema. Cloud SQL Proxy instructions. |
| 8 | `cli.py` — seed + export. Migrate local memories to GCP. |
| 9 | Team onboarding: everyone installs, pulls Ollama model, connects to Cloud SQL. |
| 10 | README with privacy explanation + setup guide. |

### Phase 3: Harden (Week 3)

| Day | Deliverable |
|-----|------------|
| 11–12 | Full test suite. Both backends. Distillation quality CI. |
| 13 | Cloud SQL backup config. Seed from existing CLAUDE.md files across repos. |
| 14 | Team feedback. Tune distillation prompt. Cut v0.2. |

---

## 14. Cost Estimate

### Local mode

| Resource | Cost |
|----------|------|
| Ollama (distillation + embeddings) on Apple Silicon | Free |
| SQLite + LanceDB | Free |
| **Total** | **$0** |

### GCP mode

| Resource | Spec | Monthly |
|----------|------|---------|
| Cloud SQL | `db-f1-micro`, 10GB SSD, private IP | ~$10 |
| Vertex AI embeddings | ~10K calls/mo (distilled text only) | < $1 |
| Cloud SQL Proxy | Runs on developer's Mac | Free |
| **Total** | **~$11/mo** |

Cheaper than v3.1 because: no GKE pods (compute is on developer Macs), no Vertex AI LLM calls (distillation is local Ollama), no Ingress.

---

## 15. Privacy Summary

| Question | Answer |
|----------|--------|
| Does Anthropic see my raw thoughts? | No. Raw text goes to local Ollama. Claude only sees distilled results from search. |
| Can my team see what I wrote? | No. Team DB contains only distilled facts. Your raw words stay on your Mac. |
| Can my manager see who contributed what? | Only if you choose. `AUTHOR_MODE=anonymous` (default) stores no attribution. You can switch to `pseudonym` or `named` anytime. Your choice, not the team's. |
| Where is my raw text stored? | Only on your Mac, in `~/.team-memory/private/`. You can delete it anytime. |
| What if the distillation leaks my name? | The distillation prompt strips names. The test suite validates this. If it ever fails, the review step catches it before saving. |
| Can I review before sharing? | Yes, and it's on by default. You see exactly what will be saved and confirm every time. |
| What if I change my mind about anonymity? | Change `AUTHOR_MODE` anytime. Past memories keep their original attribution. New memories use the new mode. |

---

## 16. Competitive Landscape

### 16.1 Market Map

There is significant activity around memory MCPs in 2026, but the market splits into two camps that don't overlap: local-only single-user stores, and centralized team knowledge services that ingest raw text into a cloud backend. Almost nothing sits in the middle.

| Product | Raw input stays local | Local LLM distills before sync | Self-hostable | Local distill + team sync |
|---------|----------------------|-------------------------------|---------------|--------------------------|
| **Claude-Mem** (18k★) | Partial; raw tool output sent to Claude API for compression. `<private>` tags opt-out, not opt-in. | No; compression via Claude Agent SDK (cloud API), not local LLM | Yes; local SQLite + ChromaDB, but compression depends on cloud API | No; single-user, single-machine (`~/.claude-mem/`), no team sync |
| **Cipher** (ByteRover) | No (cloud SaaS, IDE plugin uploads snippets) | No; privacy is at infra level, not LLM layer | Limited; primarily managed cloud | No |
| **Supermemory** ($3M funded) | No (central hosted memory) | No; memory built server-side | No; positioned as hosted service | No |
| **Grov** | No (shared cloud workspace) | No; focuses on search/chat over team data | Partial self-hosting, not local-first | No |
| **OpenMemory / Mem0** | Yes if run locally | No; storage+recall layer, not distillation pipeline | Yes; can run locally or own infra | Partial: you can wire a local LLM in front, but not batteries-included |
| **Memctl** | Depends on deployment | No; shared key-value/vector store | Yes; Docker, Apache-licensed | Only if you add your own LLM pre-processor |
| **Reference "memory" MCP servers** | Yes (local JSON/SQLite file) | No; just stores/retrieves strings | Yes, trivially | No; no team sync story |
| **SuperLocalMemory / local RAG** | Yes; explicitly local-first | Yes for local summarization, but not for team sync | Yes; open-source | No; single-user only |
| **This project (v3.2)** | **Yes; raw text never leaves device** | **Yes; mandatory Ollama distillation** | **Yes; local mode + self-hosted GCP** | **Yes; this is the core product** |

### 16.2 The Gap

As of early 2026, there is not a widely known, off-the-shelf product that:

- Runs an on-device LLM as a **mandatory** privacy layer,
- Transforms/anonymizes raw input locally,
- Syncs only distilled artifacts into a shared team knowledge base,
- While integrating cleanly into Claude Code via MCP.

The closest you get today is local-only memory MCPs plus DIY scripting around Ollama, or self-hosted memory layers like Mem0/Memctl that *could* be the backend but don't include the on-device LLM privacy gateway as a built-in feature.

Many developers already use Ollama to summarize or redact content before pasting into Slack/Confluence/GitHub, but that's a *workflow*, not a product. LangChain, LlamaIndex, etc. make it easy to *build* this pipeline, but nobody ships it as a standardized, opinionated "privacy shield" product.

### 16.3 What the market is missing (and we build)

| Missing capability | Our approach |
|-------------------|-------------|
| **Privacy policy as code on the client** — configurable rules enforced before network calls | Distillation prompt strips PII, names, secrets. Configurable `DISTILL_MODEL` and prompt. |
| **Model-agnostic local distillation** — explicit Ollama/local LLM support as pre-processor | Ollama with `gemma3:4b` default, swappable to any local model. |
| **Auditable transformations** — side-by-side raw→distilled diff for security review | `KEEP_PRIVATE_COPY=true` stores raw text locally. Developer sees distilled output before confirming. Diff is reconstructable from private store + team DB. |
| **Sync as derived artifact, not ground truth** — shared team KB stores only distilled summaries, never raw context | Core architectural principle. Raw text lives only in `~/.team-memory/private/`. |
| **Multi-tool integration without surrendering raw context** — MCP server consumed by Claude Code, Cursor, etc., sharing the same distilled memory | FastMCP server, stdio transport, works with any MCP client. |

### 16.4 Differentiation Statement

> **A local-first team memory product that treats the on-device LLM as a mandatory privacy gateway, not an optional extra.**

Claude-Mem (18k stars, 1.2k forks) is the strongest comparable project. It solves the same core problem — session amnesia — with a similar tech stack (SQLite + FTS5, ChromaDB embeddings, hybrid search). However, its privacy model is fundamentally different: Claude-Mem sends raw tool output to the Claude API for compression, and relies on opt-out `<private>` tags rather than mandatory on-device distillation. It is also single-user and single-machine with no team sync. Its progressive disclosure search (index → timeline → details) and automatic capture via hooks are design ideas worth studying.

Cipher is architecturally closest (local storage, dual memory) but lacks distillation and team sync. Supermemory has team sync but no local privacy model. Mem0 is local-capable but single-user and has no distillation pipeline. We are the only product where contributing knowledge is psychologically safe because the raw input is transformed *on your device* before anything reaches the team.

### 16.6 Claude-Mem: Detailed Comparison

Claude-Mem is the most visible project in this space (18k GitHub stars). The overlap is ~70% at the feature level — both solve "persistent memory for coding sessions" with nearly identical tech stacks. The 30% difference is architecturally fundamental.

| Dimension | Claude-Mem | Distill |
|-----------|-----------|---------|
| **Privacy model** | Raw tool output → Claude API for compression. `<private>` tags are opt-out. | Raw text → local Ollama. Never leaves device. Privacy is opt-in by default. |
| **Team sync** | None. `~/.claude-mem/` is local, no shared DB. | Core feature. Shared knowledge pool via SQLite (local) or Cloud SQL (GCP). |
| **Capture model** | Passive/automatic via hooks (PostToolUse, SessionEnd). Records everything. | Intentional. `remember` is called explicitly. Preview with save/edit/abort. |
| **Compression** | Claude Agent SDK → ~500 token observations (cloud API call). | Ollama → 1-3 sentence distilled facts (local, no network). |
| **Platform** | Claude Code plugin, bound to its hook lifecycle. | MCP server — works with Claude Code, Cursor, Cline, any MCP client. |
| **Multi-agent** | No agent_id, no visibility matrix. Single-agent only. | Planned: agent_id, multi-agent writing, visibility matrix. |
| **Search** | 3-layer progressive disclosure (index → timeline → full). Token-efficient. | Flat hybrid search (FTS + vector, RRF). Simpler but returns more per call. |
| **Author attribution** | Not configurable. | `AUTHOR_MODE`: anonymous (default) / pseudonym / named. Developer's choice. |
| **Web UI** | Real-time memory viewer on localhost:37777. | Not yet (planned). |

**What we should learn from Claude-Mem:**

1. **Progressive disclosure search** — their 3-layer approach (index → timeline → details) saves tokens significantly. Distill should adopt a similar pattern for `search_memory`.
2. **Automatic capture** — an optional `AUTO_CAPTURE=true` mode that triggers `remember` on corrections and decisions (still routed through local distillation) would lower the barrier to contribution.
3. **Web viewer** — a local browse/search UI is a quick win for adoption.

**What we should NOT copy:**

- Cloud API for compression — local distillation is our core differentiator.
- Single-user-only design — team sync is our differentiator.
- Platform lock to Claude Code — MCP agnosticism is more valuable.

### 16.5 Reference Architecture

Cipher's dual-memory pattern (short-term working memory + long-term persistent memory) is worth studying. Their consolidation flow maps conceptually to our private-local → distill → team-DB pipeline, though the privacy motivation is different.

---

## 17. Open Questions

| # | Question | Owner |
|---|----------|-------|
| 1 | Which Ollama model produces the best distillation quality on Apple Silicon? Benchmark gemma3:4b vs phi4-mini vs llama3.2:3b. | Engineering |
| 2 | Should `remember` be auto-triggered by Claude, or always explicit? | Product |
| 3 | v2 auth: mTLS with Apple-style device certs for Cloud SQL access. | Platform |
| 4 | Auto-extract decisions from merged GitHub PRs via webhook + distillation? | Product (v2) |
| 5 | Add `search_code` tool wrapping Claude Context for unified code + knowledge search? | Architecture (v2) |
| 6 | Should memories have TTL/expiry? | Product |
| 7 | Can we add a confidence score to distillation (self-assessed by the local LLM) to flag low-quality extractions? | Engineering |
| 8 | Versioning: expose `supersedes` chain as browsable history? | Product (v2) |
| 9 | Async distillation: `remember` returns immediately, distillation runs in background, preview notification when done. Reduces latency to near-zero. | Engineering (v2) |
| 10 | Editable distillates: `[s]end [e]dit [a]bort` flow for power users who want to refine the output before committing. Needs MCP interaction support. | Engineering (v2) |
| 11 | Privacy policy as code: configurable regex rules (strip API keys, internal hostnames, email patterns) enforced *in addition to* LLM distillation. Belt-and-suspenders. | Security (v2) |
| 12 | Audit dashboard: side-by-side raw→distilled diff viewer (local only, for security review). Reconstructable from private store + team DB. | Engineering (v2) |
| 13 | Multi-tool support: verify that Cursor, Windsurf, and other MCP clients work with the same distilled team memory. | Engineering (v2) |
