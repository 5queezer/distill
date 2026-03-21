---
title: GCP Backend Setup
---

# GCP Backend Setup

The GCP setup uses Cloud SQL (PostgreSQL + pgvector) for storage and Vertex AI for embeddings.

## Prerequisites

- A GCP project with billing enabled
- `gcloud` CLI authenticated
- Cloud SQL Admin API enabled
- Vertex AI API enabled

## Step 1: Create a Cloud SQL instance

```bash
gcloud sql instances create distill-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1
```

## Step 2: Create the database

```bash
gcloud sql databases create distill --instance=distill-db
```

## Step 3: Set up Cloud SQL Proxy

```bash
# Download the proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.15.2/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy

# Start the proxy (runs in background)
./cloud-sql-proxy your-project:us-central1:distill-db &
```

## Step 4: Configure environment

```bash
export BACKEND=postgres
export DATABASE_URL="postgresql://postgres:password@127.0.0.1:5432/distill"
export EMBEDDING_PROVIDER=vertex
export GCP_PROJECT=your-project
export GCP_LOCATION=us-central1
```

## Step 5: Start Distill

```bash
python -m distill_mcp
```

The PostgreSQL store will automatically:

- Create the `memories` table with pgvector extension
- Set up full-text search indexes
- Initialize RLS policies (if `AUTH_ENABLED=true`)

## Cost

Approximately **$11/month** for a `db-f1-micro` instance. Vertex AI embedding costs are negligible at typical usage volumes.

## Authentication (optional)

Enable git-based identity with Row-Level Security:

```bash
export AUTH_ENABLED=true
```

This uses your git identity (`user.email`) to tag memories and enforce ownership via PostgreSQL RLS policies. Anonymous users get read-only access.
