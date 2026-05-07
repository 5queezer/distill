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

## Step 4: Set up the auto-observe hook

Distill captures knowledge automatically from your Claude Code tool calls. Add the PostToolUse hook to your Claude Code settings:

```bash
claude hooks add PostToolUse \
  'curl -s -X POST http://127.0.0.1:21746/observe \
    -H "Content-Type: application/json" \
    -d @- <<< "$CLAUDE_HOOK_PAYLOAD" &'
```

Now every tool call (Read, Bash, Edit, etc.) is automatically captured in the background — zero latency impact on Claude.

## Step 5: Use Claude Code normally

There's nothing special to do. Work as you normally would:

```
You:    "Let's use gRPC instead of REST for inter-service communication
         because of streaming support and type safety."

Claude: [edits code, runs tests, etc.]
```

Behind the scenes, Distill's background worker distills each tool call into anonymous, factual knowledge and stores it in the team database.

## Step 6: Search your memories

```
You:    "How do our services communicate?"

Claude: [searches team memory]
        Based on your team's knowledge base, inter-service communication
        uses gRPC, chosen for streaming support and type safety.
```

## What you've learned

- How to install Distill and its Ollama dependencies
- How to register the MCP server with Claude Code
- How to set up the auto-observe hook for automatic knowledge capture
- How search retrieves stored team knowledge

## Next steps

- [Installation options](../how-to/installation.md) for alternative setups
- [GCP backend setup](../how-to/gcp-backend.md) for team-shared databases
- [Tools reference](../reference/tools.md) for all available MCP tools
