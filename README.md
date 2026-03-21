# 🧪 Distill

[![CI](https://github.com/5queezer/distill/actions/workflows/ci.yml/badge.svg)](https://github.com/5queezer/distill/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An MCP server that gives Claude Code a shared team knowledge base — a local LLM transforms your raw input into anonymous, factual knowledge *before* anything leaves your device.

No author. No frustration. No names. Just a clean, reusable fact.

![Distill demo — raw thought to clean team fact](https://raw.githubusercontent.com/5queezer/distill/main/docs/demo.gif)

![Raw input → local Ollama → review → team DB or discard](https://raw.githubusercontent.com/5queezer/distill/main/docs/flow.svg)

## Quick Start

```bash
pip install distill-mcp
ollama pull gemma3:4b && ollama pull nomic-embed-text
claude mcp add distill -- python -m distill_mcp
```

Then in Claude Code:

```
You:    "No, we don't use REST here. We switched to gRPC last month."

Claude: [saves to distill]
        Got it. I've noted that the team uses gRPC, not REST.

        ... next session, different repo ...

You:    "Set up the API for this new service."

Claude: [searches distill → finds gRPC decision]
        Based on your team's knowledge, I'll set up a gRPC
        service since the team switched from REST last month.
```

Distill saves when you correct a mistake or make a decision, and searches before proposing architecture — no prompting needed.

## What makes this different

Every "memory MCP" stores your raw text in a database. Distill doesn't. The local LLM is a mandatory privacy gateway that transforms personal thoughts into impersonal team knowledge.

|  | Raw stays local | LLM distills | Team sync | Platform agnostic |
|--|----------------|-------------|-----------|-------------------|
| Claude-Mem | Partial (`<private>` opt-out) | Cloud API compresses | Single-user | Claude Code only |
| Cipher | No | No | Yes | No |
| Supermemory | No | No | Yes | No |
| Mem0 | Yes | No | No | Yes |
| Memctl | Yes | No | Yes | Yes |
| **Distill** | **Yes** | **Yes** | **Yes** | **Yes** |

Based on public documentation as of March 2026.

## When to use Distill vs. Skills vs. CLAUDE.md

Claude Code has three persistence mechanisms. They serve different purposes and have different half-lives.

| Mechanism | What it stores | Half-life | Example |
|-----------|---------------|-----------|---------|
| **CLAUDE.md** | Conventions, guardrails, project rules | Months–years | "We use gRPC, not REST" / "Never skip pre-commit hooks" |
| **Skills** | Repeatable processes, recipes | Weeks–months | "How to deploy to Cloud Run with an oauth2-proxy sidecar" |
| **Distill** | Decision context, failure postmortems, team knowledge | Days–weeks | "We chose X over Y because Z failed under load" |

**Use CLAUDE.md** when the knowledge is deterministic and should apply to every session — coding standards, architectural constraints, tooling preferences. Every conversation reads it automatically.

**Use a Skill** when the knowledge is procedural and reusable — a step-by-step process that you'd otherwise explain from scratch each time. Skills are invoked on demand, not loaded automatically.

**Use Distill** when the knowledge is contextual and emerged from work — why a decision was made, what was tried and failed, what surprised you. Distill captures the *reasoning* that code and commit messages don't preserve, strips PII and secrets automatically, and makes it searchable across sessions and team members.

The three complement each other. A debugging session might produce all three: a CLAUDE.md rule ("always check X before Y"), a skill (the debugging procedure itself), and a distill memory (what caused the specific incident and why the obvious fix didn't work).

## Documentation

- [Getting Started](https://5queezer.github.io/distill/tutorials/getting-started/) — full tutorial
- [Installation](https://5queezer.github.io/distill/how-to/installation/) — all setup options
- [GCP Backend](https://5queezer.github.io/distill/how-to/gcp-backend/) — team-shared database
- [MCP Tools](https://5queezer.github.io/distill/reference/tools/) — all 8 tools
- [Configuration](https://5queezer.github.io/distill/reference/configuration/) — environment variables
- [Architecture](https://5queezer.github.io/distill/explanation/architecture/) — Clean Architecture design
- [Privacy Model](https://5queezer.github.io/distill/explanation/privacy-model/) — how your data stays private

## Development

```bash
git clone https://github.com/5queezer/distill.git
cd distill
uv sync
uv run pytest tests/ -x -v
```

## License

[MIT](LICENSE)
