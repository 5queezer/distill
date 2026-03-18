---
title: Configuration
---

# Configuration Reference

All settings are controlled via environment variables (or a `.env` file). Defaults are shown below.

## Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND` | `local` | Backend type: `local` or `gcp` |
| `DATA_DIR` | `~/.team-memory` | Local data directory (SQLite, LanceDB, private store) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Ollama settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `LLM_MODEL` | `gemma3:4b` | Model for distillation |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for embeddings (must produce 768-dim vectors) |

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

## GCP settings

Only used when `BACKEND=gcp`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `GCP_PROJECT` | — | GCP project ID |
| `GCP_LOCATION` | `us-central1` | GCP region for Vertex AI |
| `CLOUD_SQL_CONNECTION` | — | Cloud SQL instance connection name |

## Port interfaces

Distill uses Clean Architecture ports. Each setting selects an adapter:

| Port | `local` adapter | `gcp` adapter |
|------|----------------|---------------|
| `StoragePort` | SQLite + FTS5 + LanceDB | Cloud SQL + pgvector + tsvector |
| `EmbeddingPort` | Ollama (`nomic-embed-text`) | Vertex AI (`text-embedding-005`) |
| `DistillerPort` | Ollama (`gemma3:4b`) | Ollama (`gemma3:4b`) — always local |
| `ScannerPort` | gitleaks-based secret detection | gitleaks-based secret detection |
