---
title: Configuration
---

# Configuration Reference

All settings are controlled via environment variables (or a `.env` file). Defaults are shown below.

## Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND` | `local` | Backend type: `local`, `gcp`, `postgres`, `aws`, `azure` |
| `DATA_DIR` | `~/.team-memory` | Local data directory (SQLite, LanceDB, private store) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Ollama settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `LLM_MODEL` | `gemma3:4b` | Model for distillation |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for embeddings (must produce 768-dim vectors) |

Ollama also reads its own environment variables for GPU control (`OLLAMA_NUM_GPU`, `CUDA_VISIBLE_DEVICES`, etc.). See the [GPU Setup guide](../how-to/gpu-setup.md) for hardware-specific configuration.

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

## Reranking (optional, GCP-only)

Cross-encoder reranking improves search relevance by re-scoring results after hybrid search.

| Variable | Default | Description |
|----------|---------|-------------|
| `RERANK_ENABLED` | `false` | Enable cross-encoder reranking |
| `JINA_API_KEY` | — | Jina Reranker API key |
| `RERANK_MODEL` | `jina-reranker-v2-base-multilingual` | Reranker model |

Reranking adds latency (~200ms) and requires an external API call. Only recommended for GCP backend where search quality is critical. The privacy constraint is preserved — only distilled content (never raw input) is sent to the reranker.

## PostgreSQL settings

Used when `BACKEND=gcp`. Works with any PostgreSQL provider that supports pgvector (Cloud SQL, [Neon](../how-to/neon-backend.md), Supabase, self-hosted).

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `GCP_PROJECT` | — | GCP project ID (Cloud SQL / Vertex AI only) |
| `GCP_LOCATION` | `us-central1` | GCP region for Vertex AI |
| `CLOUD_SQL_CONNECTION` | — | Cloud SQL instance connection name |

## AWS settings

Used when `BACKEND=aws`. Uses Amazon Bedrock for embeddings.

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock |
| `AWS_BEDROCK_MODEL` | `amazon.titan-embed-text-v2:0` | Bedrock embedding model |

## Azure settings

Used when `BACKEND=azure`. Uses Azure OpenAI for embeddings.

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI endpoint URL (required when `BACKEND=azure`) |
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI API key (required when `BACKEND=azure`) |
| `AZURE_OPENAI_DEPLOYMENT` | `text-embedding-3-small` | Azure OpenAI deployment name |

## Port interfaces

Distill uses Clean Architecture ports. Each setting selects an adapter:

| Port | `local` adapter | `gcp` adapter | `aws` adapter | `azure` adapter |
|------|----------------|---------------|---------------|-----------------|
| `StoragePort` | SQLite + FTS5 + LanceDB | Cloud SQL + pgvector + tsvector | Cloud SQL + pgvector + tsvector | Cloud SQL + pgvector + tsvector |
| `EmbeddingPort` | Ollama (`nomic-embed-text`) | Vertex AI (`text-embedding-005`) | Bedrock (`amazon.titan-embed-text-v2:0`) | Azure OpenAI (`text-embedding-3-small`) |
| `DistillerPort` | Ollama (`gemma3:4b`) | Ollama (`gemma3:4b`) — always local | Ollama (`gemma3:4b`) — always local | Ollama (`gemma3:4b`) — always local |
| `ScannerPort` | gitleaks-based secret detection | gitleaks-based secret detection | gitleaks-based secret detection | gitleaks-based secret detection |
| `RerankerPort` | — (not used) | Jina Reranker API (opt-in) | — (not used) | — (not used) |
