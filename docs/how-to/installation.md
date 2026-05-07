---
title: Installation
---

# Installation

## From PyPI

```bash
pip install distill-mcp
```

For GCP backend support:

```bash
pip install distill-mcp[gcp]
```

## From source

```bash
git clone https://github.com/5queezer/distill.git
cd distill
uv sync
```

## Ollama models

Distill requires two Ollama models:

```bash
ollama pull gemma3:4b          # distillation (raw text → anonymous fact)
ollama pull nomic-embed-text   # embeddings (768-dim vectors for search)
```

You can override these with environment variables:

```bash
export LLM_MODEL=gemma3:4b              # any Ollama model
export EMBEDDING_MODEL=nomic-embed-text # must produce 768-dim vectors
```

## Register with Claude Code

```bash
# From PyPI install
claude mcp add distill -- python -m distill_mcp

# From source
claude mcp add distill -- uv run python -m distill_mcp
```

## Verify

Run the MCP Inspector to test tools interactively:

```bash
fastmcp dev src/distill_mcp/server.py
```

## Configuration

All settings are controlled via environment variables. See the [Configuration reference](../reference/configuration.md) for the full list.
