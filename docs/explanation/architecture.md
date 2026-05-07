---
title: Architecture
---

# Architecture

Distill follows Clean Architecture (Uncle Bob). Dependencies point inward. Business logic has no knowledge of frameworks, databases, or transport.

## Layer diagram

```mermaid
graph TB
    subgraph "Claude Code"
        CC[Claude Code] -->|MCP protocol| SRV
        HOOK["PostToolUse hook"] -->|"curl POST /observe"| ING
    end

    subgraph "Server Layer"
        SRV["server.py — 8 MCP tools"]
        ING["ingest.py — HTTP /observe endpoint"]
        WRK["worker.py — background distillation"]
        MAIN["__main__.py — wiring & startup"]
    end

    subgraph "Domain Layer (inner ring)"
        SVC["services.py — use cases"]
        MDL["models.py — Memory, SearchResult"]
        PRT["ports.py — StoragePort, EmbeddingPort, DistillerPort, ScannerPort, RerankerPort"]
    end

    subgraph "Adapters (outer ring)"
        SQL["sqlite_store.py / postgres_store.py"]
        EMB["ollama_embed.py / vertex_embed.py / gemini_embed.py"]
        DST["ollama_distill.py / gemini_distill.py"]
        SCN["secret_scanner.py (secrets + PII)"]
        RRK["jina_rerank.py (opt-in)"]
    end

    subgraph "Infrastructure"
        OLLAMA["Ollama (localhost)"]
        DB[(SQLite or PostgreSQL)]
        VEC[(LanceDB or pgvector)]
    end

    MAIN -->|wires adapters| SRV
    MAIN -->|starts| ING
    MAIN -->|starts| WRK
    ING -->|"append JSONL + signal"| WRK
    WRK -->|"distill/embed/save"| SVC
    SRV -->|delegates to| SVC
    SVC -->|depends on| PRT
    SQL -.->|implements| PRT
    EMB -.->|implements| PRT
    DST -.->|implements| PRT
    SCN -.->|implements| PRT
    RRK -.->|implements| PRT
    DST --> OLLAMA
    DST -.->|or| GEMINI["Gemini API (cloud)"]
    EMB --> OLLAMA
    EMB -.->|or| GEMINI
    SQL --> DB
    SQL --> VEC
```

## Directory structure

```
src/distill_mcp/
├── domain/              # Inner ring: pure business logic, no dependencies
│   ├── models.py        # Memory, DistilledMemory, SearchResult (dataclasses/Pydantic)
│   ├── ports.py         # Abstract interfaces (StoragePort, EmbeddingPort, DistillerPort)
│   └── services.py      # Use cases: search, update, forget
│
├── adapters/            # Outer ring: implementations of ports
│   ├── storage/
│   │   ├── sqlite_store.py    # StoragePort → SQLite + FTS5 + LanceDB
│   │   └── postgres_store.py  # StoragePort → asyncpg + pgvector + tsvector
│   ├── embeddings/
│   │   ├── ollama_embed.py    # EmbeddingPort → local Ollama
│   │   ├── vertex_embed.py    # EmbeddingPort → Vertex AI
│   │   ├── gemini_embed.py    # EmbeddingPort → Gemini API
│   │   ├── bedrock_embed.py   # EmbeddingPort → AWS Bedrock
│   │   └── azure_embed.py     # EmbeddingPort → Azure OpenAI
│   ├── distiller/
│   │   ├── ollama_distill.py  # DistillerPort → local Ollama
│   │   └── gemini_distill.py  # DistillerPort → Gemini API
│   ├── identity/
│   │   └── git_identity.py    # Git-based identity resolution (AUTH_ENABLED)
│   ├── scanner/
│   │   └── secret_scanner.py  # ScannerPort → secrets + PII redaction
│   └── reranker/
│       └── jina_rerank.py     # RerankerPort → Jina Reranker API (opt-in)
│
├── server.py            # FastMCP tool definitions — thin adapter
├── ingest.py            # HTTP /observe endpoint (localhost)
├── worker.py            # Background distillation consumer
├── dedup.py             # Cosine similarity > 0.95 check
├── hardware.py          # GPU/hardware detection for check-hardware CLI
├── settings.py          # pydantic-settings, env var loading
└── __main__.py          # Entry point: wires adapters, starts FastMCP + ingest + worker
```

## The dependency rule

`server.py` depends on `domain/services.py`. Services depend on `domain/ports.py`. Adapters implement ports. **Nothing in `domain/` imports from `adapters/`.**

This means you can swap SQLite for PostgreSQL, or Ollama embeddings for Vertex AI, without touching any business logic.

## Configuration axes

Storage, embeddings, and distillation are configured independently:

| Setting | Options |
|---------|---------|
| `BACKEND` | `local` (SQLite + LanceDB) or `postgres` (PostgreSQL + pgvector) |
| `EMBEDDING_PROVIDER` | `ollama`, `gemini`, `vertex`, `bedrock`, `azure` |
| `DISTILLER_PROVIDER` | `ollama`, `gemini` |

### Example configurations

| Use case | Storage | Embeddings | Distillation | Cost |
|----------|---------|------------|--------------|------|
| Local-only | `local` | `ollama` | `ollama` | $0 |
| Cloud-free (no GPU) | `local` | `gemini` | `gemini` | $0 (free tier) |
| Team (GCP) | `postgres` | `vertex` | `ollama` | ~$11/mo |
| Team (GCP, no GPU) | `postgres` | `vertex` | `gemini` | ~$11/mo |
| Team (AWS) | `postgres` | `bedrock` | `ollama` | ~$15/mo |
| Team (Azure) | `postgres` | `azure` | `ollama` | ~$14/mo |

## Key execution flows

### Auto-observe (background pipeline)

1. Claude calls any tool (Read, Bash, Edit, etc.)
2. Claude Code `PostToolUse` hook fires and POSTs tool I/O to `http://127.0.0.1:<port>/observe`
3. Ingest endpoint appends a JSON line to the private_store JSONL and signals the worker
4. Background worker reads the entry, runs the distillation pipeline:
   - Noise filter rejects trivial entries
   - Scanner redacts secrets and PII from raw text
   - Distiller (local Ollama) strips personal language, keeps facts
   - Scanner re-checks distilled output
   - Embedder generates 768-dim vector
   - Dedup check rejects if cosine similarity > 0.95 with existing memory
   - Save to storage backend
5. Claude continues immediately — zero latency impact

### Search (hybrid with RRF)

1. Query is embedded via `EmbeddingPort` (768-dim vector)
2. Full-text search runs in parallel with vector similarity search
3. Results are merged using Reciprocal Rank Fusion (k=60)
4. Optional cross-encoder reranking via `RerankerPort` (Jina API, GCP-only)
5. Level-aware boost — multipliers based on memory level: short-term ×0.8, long-term ×1.0, shared ×1.2
6. Weibull time-decay boost — type-aware recency scoring (decisions decay fast, patterns persist)
7. Access-frequency boost — frequently accessed memories rank higher
8. Returns compact index (~30 tokens/result) for progressive disclosure
9. Client fetches full content with `get_memories` for relevant results only

### Weibull time-decay

Instead of a simple inverse decay, memories decay at rates appropriate to their type:

| Type | Scale (λ) | Shape (k) | Behavior |
|------|-----------|-----------|----------|
| `context` | 7 days | 2.0 | Fastest decay — ephemeral |
| `decision` | 14 days | 1.5 | Fast — decisions get superseded |
| `failure` | 45 days | 1.2 | Medium — failures become less relevant |
| `pattern` | 90 days | 0.8 | Slow — patterns are durable |
| `dependency` | 180 days | 0.7 | Slowest — dependency choices are long-lived |

The Weibull survival function `S(t) = exp(-(t/λ)^k)` starts at 1.0 and decays toward 0. The shape parameter `k` controls the decay curve: `k < 1` gives a long tail (useful for durable knowledge), `k > 1` gives accelerating decay (useful for ephemeral context).
