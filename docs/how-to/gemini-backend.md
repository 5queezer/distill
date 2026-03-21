---
title: Gemini Backend Setup
---

# Gemini (Free Cloud LLM + Embeddings)

Use Google Gemini as a drop-in replacement for local Ollama. No GPU required, no Ollama process to manage. Works with the free tier.

## When to use this

- You don't have a GPU (or it's busy with other work)
- You want zero local compute overhead
- The privacy tradeoff is acceptable — raw text goes to Google for distillation

## Prerequisites

- A Google account
- A Gemini API key ([get one free at AI Studio](https://aistudio.google.com/apikey))

## Setup

```bash
EMBEDDING_PROVIDER=gemini
DISTILLER_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

Storage stays local (SQLite + LanceDB). Ollama is no longer needed.

## What changes

| Component | Ollama (default) | Gemini |
|-----------|-----------------|--------|
| Embeddings | `nomic-embed-text` (local) | `text-embedding-004` (768-dim, Google API) |
| Distillation | `gemma3:4b` (local) | `gemini-2.0-flash` (Google API) |
| Storage | unchanged | unchanged |
| Privacy | Raw text stays on device | Raw text goes to Google |
| Cost | $0 (needs Ollama running) | $0 (free tier) |

## Optional: customize models

```bash
EMBEDDING_MODEL=text-embedding-004    # default for gemini provider
LLM_MODEL=gemini-2.0-flash           # default for gemini provider
```

`EMBEDDING_MODEL` and `LLM_MODEL` are universal — they apply to whichever provider is active. Each provider has sensible defaults if you omit them.

## Mix and match

Embedding and distillation providers are independent. You can use Gemini for one and Ollama for the other:

```bash
# Gemini embeddings + local Ollama distillation (privacy-preserving)
EMBEDDING_PROVIDER=gemini
DISTILLER_PROVIDER=ollama
GEMINI_API_KEY=your-key-here
```

Or combine with PostgreSQL storage:

```bash
BACKEND=postgres
DATABASE_URL=postgresql://...
EMBEDDING_PROVIDER=gemini
DISTILLER_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

## Free tier limits

As of March 2026, the Gemini free tier provides:

- **gemini-2.0-flash**: 15 requests/minute, 1M tokens/day
- **text-embedding-004**: 1500 requests/minute

For typical team memory usage (a few `remember` + `search` calls per minute), the free tier is more than sufficient.

## Switching back to Ollama

Set providers back to `ollama` (or remove `EMBEDDING_PROVIDER` / `DISTILLER_PROVIDER` — Ollama is the default).
