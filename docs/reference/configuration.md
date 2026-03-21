---
title: Configuration
---

# Configuration Reference

All settings are controlled via environment variables (or a `.env` file).

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND` | `local` | Storage backend: `local` (SQLite + LanceDB) or `postgres` (PostgreSQL + pgvector) |
| `DATA_DIR` | `~/.team-memory` | Local data directory (SQLite, LanceDB, private store) |
| `DATABASE_URL` | — | PostgreSQL connection string (required when `BACKEND=postgres`) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Embedding provider

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `ollama` | Provider: `ollama`, `gemini`, `vertex`, `bedrock`, `azure` |
| `EMBEDDING_MODEL` | *(per provider)* | Embedding model name. Defaults: ollama=`nomic-embed-text`, gemini=`text-embedding-004`, vertex=`text-embedding-005`, bedrock=`amazon.titan-embed-text-v2:0`, azure=`text-embedding-3-small` |

All embeddings must produce **768-dimensional** vectors.

## Distillation provider

| Variable | Default | Description |
|----------|---------|-------------|
| `DISTILLER_PROVIDER` | `ollama` | Provider: `ollama`, `gemini` |
| `LLM_MODEL` | *(per provider)* | Distillation model name. Defaults: ollama=`gemma3:4b`, gemini=`gemini-2.0-flash` |

!!! warning "Privacy tradeoff"
    With `DISTILLER_PROVIDER=gemini`, raw text is sent to Google's API for distillation. With `ollama`, raw text stays on your device.

## Provider credentials

### Ollama (default, no credentials)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |

Ollama also reads its own environment variables for GPU control (`OLLAMA_NUM_GPU`, `CUDA_VISIBLE_DEVICES`, etc.). See the [GPU Setup guide](../how-to/gpu-setup.md).

### Gemini

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Required when `EMBEDDING_PROVIDER=gemini` or `DISTILLER_PROVIDER=gemini` |

Free tier available at [AI Studio](https://aistudio.google.com/apikey). See [Gemini Backend](../how-to/gemini-backend.md).

### Vertex AI

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT` | — | GCP project ID (required when `EMBEDDING_PROVIDER=vertex`) |
| `GCP_LOCATION` | `us-central1` | GCP region |
| `CLOUD_SQL_CONNECTION` | — | Cloud SQL instance connection name |

### Bedrock

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |

Uses the default AWS credential chain (environment variables, `~/.aws/credentials`, or instance role).

### Azure OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | — | Endpoint URL (required when `EMBEDDING_PROVIDER=azure`) |
| `AZURE_OPENAI_API_KEY` | — | API key (required when `EMBEDDING_PROVIDER=azure`) |

## Privacy & review

| Variable | Default | Description |
|----------|---------|-------------|
| `DISTILL_ENABLED` | `true` | Enable LLM distillation (disable for testing) |
| `PREVIEW_ENABLED` | `true` | Two-phase commit: show preview before storing |
| `PREVIEW_TTL_SECONDS` | `300` | How long a pending preview stays valid |
| `DEFAULT_AUTHOR` | `unknown` | Default author attribution |
| `AUTH_ENABLED` | `false` | Enable git-based identity + PostgreSQL RLS |

## Search tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `RRF_K` | `60` | Reciprocal Rank Fusion constant |
| `MAX_MEMORY_SIZE` | `8000` | Maximum memory content size in characters |
| `FTS_LANGUAGE` | `simple` | Full-text search language configuration |

## Reranking (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `RERANK_ENABLED` | `false` | Enable cross-encoder reranking |
| `JINA_API_KEY` | — | Jina Reranker API key |
| `RERANK_MODEL` | `jina-reranker-v2-base-multilingual` | Reranker model |

## Port interfaces

| Port | Adapters |
|------|----------|
| `StoragePort` | `local`: SQLite + FTS5 + LanceDB | `postgres`: PostgreSQL + pgvector + tsvector |
| `EmbeddingPort` | `ollama` `gemini` `vertex` `bedrock` `azure` — selected by `EMBEDDING_PROVIDER` |
| `DistillerPort` | `ollama` `gemini` — selected by `DISTILLER_PROVIDER` |
| `ScannerPort` | secrets + PII detection (always active) |
| `RerankerPort` | Jina Reranker API (opt-in via `RERANK_ENABLED`) |
