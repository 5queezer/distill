---
title: Azure Backend Setup
---

# Azure Backend (PostgreSQL + OpenAI)

The Azure setup uses Azure Database for PostgreSQL Flexible Server with pgvector for storage and Azure OpenAI for embeddings.

## Prerequisites

- An Azure subscription
- Azure CLI configured (`az login`)
- An Azure Database for PostgreSQL Flexible Server instance
- An Azure OpenAI resource with a `text-embedding-3-small` deployment

## Step 1: Create a PostgreSQL Flexible Server

```bash
az postgres flexible-server create \
  --name distill-db \
  --resource-group distill-rg \
  --location eastus \
  --sku-name Standard_B1ms \
  --storage-size 32 \
  --admin-user distill \
  --admin-password <your-password>
```

## Step 2: Enable pgvector

Connect to the instance and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

On Flexible Server, `vector` is in the allowlist by default — no server parameter changes required.

## Step 3: Deploy Azure OpenAI embedding model

```bash
az cognitiveservices account deployment create \
  --name distill-openai \
  --resource-group distill-rg \
  --deployment-name text-embedding-3-small \
  --model-name text-embedding-3-small \
  --model-version 1 \
  --model-format OpenAI
```

## Step 4: Configure environment

```bash
export BACKEND=postgres
export DATABASE_URL="postgresql://distill:<your-password>@distill-db.postgres.database.azure.com:5432/distill?sslmode=require"
export EMBEDDING_PROVIDER=azure
export AZURE_OPENAI_ENDPOINT="https://distill-openai.openai.azure.com/"
export AZURE_OPENAI_API_KEY="<your-api-key>"
```

## Step 5: Start Distill

```bash
python -m distill_mcp
```

The PostgreSQL store will automatically create the `memories` table, pgvector extension, full-text search indexes, and RLS policies.

## Cost

Varies by tier. A `Standard_B1ms` Flexible Server costs approximately **$13/month**. Azure OpenAI embedding costs are per 1K tokens and negligible at typical usage volumes.
