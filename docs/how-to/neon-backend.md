---
title: Neon Backend Setup
---

# Neon Backend Setup

[Neon](https://neon.tech) is a serverless PostgreSQL provider with a generous free tier. It supports pgvector natively, making it a zero-cost alternative to Cloud SQL for the PostgreSQL backend.

## Prerequisites

- A Neon account (free tier works)
- Ollama running locally (distillation always stays local)

## Step 1: Create a Neon project

1. Go to [console.neon.tech](https://console.neon.tech) and create a new project
2. Choose a region close to you
3. Copy the connection string

## Step 2: Enable pgvector

In the Neon SQL Editor, run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Step 3: Configure environment

```bash
export BACKEND=gcp
export DATABASE_URL="postgresql://user:pass@ep-xyz.us-east-2.aws.neon.tech/distill?sslmode=require"
```

`BACKEND=gcp` selects the PostgreSQL adapter — it works with any PostgreSQL provider, not just GCP.

## Step 4: Start Distill

```bash
python -m distill_mcp
```

The PostgreSQL store will automatically create the `memories` table, full-text search indexes, and RLS policies.

## Connection pooling caveat

Neon offers two connection endpoints:

| Endpoint | Example | Session variables |
|----------|---------|-------------------|
| **Direct** | `ep-xyz.us-east-2.aws.neon.tech` | Work correctly |
| **Pooled** | `ep-xyz-pooler.us-east-2.aws.neon.tech` | Lost between transactions |

If you use `AUTH_ENABLED=true`, you **must** use the direct endpoint. The RLS implementation relies on session-level `SET` commands (`app.repos`, `app.user_email`) that PgBouncer's transaction mode discards.

With auth disabled (default), either endpoint works.

## Cost

**Free.** Neon's free tier includes 0.5 GB storage and 190 compute hours/month — more than sufficient for team memory.
