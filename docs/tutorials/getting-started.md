---
title: Getting Started
---

# Getting Started

This tutorial walks you through installing Distill, connecting it to Claude Code, and storing your first team memory.

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) installed and running
- Claude Code CLI

## Step 1: Install Distill

```bash
pip install distill-mcp
```

Or from source:

```bash
git clone https://github.com/5queezer/distill.git
cd distill
uv sync
```

## Step 2: Pull the required Ollama models

Distill needs two models — one for distillation (turning your raw text into anonymous facts) and one for embeddings (enabling semantic search):

```bash
ollama pull gemma3:4b          # distillation
ollama pull nomic-embed-text   # embeddings (768-dim vectors)
```

## Step 3: Register with Claude Code

```bash
claude mcp add distill -- python -m distill_mcp
```

Or if running from source:

```bash
claude mcp add distill -- uv run python -m distill_mcp
```

## Step 4: Store your first memory

Open Claude Code and say:

```
You:    "Remember that we chose gRPC over REST for inter-service
         communication because of streaming support and type safety."
```

Claude will:

1. Send the raw text to your **local** Ollama for distillation
2. Show you the distilled preview (e.g., *"gRPC was chosen over REST for inter-service communication due to streaming support and type safety."*)
3. Wait for your approval
4. Store the approved fact in the team database

## Step 5: Search your memories

```
You:    "How do our services communicate?"

Claude: [searches team memory]
        Based on your team's knowledge base, inter-service communication
        uses gRPC, chosen for streaming support and type safety.
```

## What you've learned

- How to install Distill and its Ollama dependencies
- How to register the MCP server with Claude Code
- The two-phase remember flow: distill → preview → confirm
- How search retrieves stored team knowledge

## Next steps

- [Installation options](../how-to/installation.md) for alternative setups
- [GCP backend setup](../how-to/gcp-backend.md) for team-shared databases
- [Tools reference](../reference/tools.md) for all available MCP tools
