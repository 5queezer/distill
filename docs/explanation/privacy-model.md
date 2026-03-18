---
title: Privacy Model
---

# Privacy Model

## The core guarantee

**Your raw text never crosses a network boundary.** The local LLM is not optional — it's the privacy component.

```
Developer input (raw text)
        │
        ▼
   ┌─────────────┐
   │ private_store│ ← JSONL, never synced, local only
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   Ollama     │ ← localhost, never crosses network
   │  (distill)   │
   └──────┬──────┘
          │ distilled fact (no names, no emotion, no PII)
          ▼
   ┌─────────────┐
   │   Scanner    │ ← redacts any leaked secrets
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  Team DB     │ ← team-safe knowledge
   └─────────────┘
```

## What makes this different

Every "memory MCP" stores your raw text in a database. Distill doesn't. The local LLM is a mandatory privacy gateway that transforms personal thoughts into impersonal team knowledge. Contributing knowledge is psychologically safe because your exact words never leave your machine.

## FAQ

| Question | Answer |
|----------|--------|
| Does Anthropic see my raw input? | No. It goes to local Ollama only. |
| Can my team read what I typed? | No. Only the distilled fact is stored. |
| Can my manager see who wrote what? | Only if you opt in (`AUTH_ENABLED=true`). Anonymous by default. |
| Where is my raw text? | `~/.distill/private/` on your machine. Delete anytime. |
| What if distillation leaks a name? | You review every output before it's saved. The scanner also checks for secrets. |

## Author modes

| Mode | Behavior |
|------|----------|
| `anonymous` (default) | No author attribution stored |
| `AUTH_ENABLED=true` | Git identity (`user.email`) used for ownership and RLS enforcement |

When authentication is enabled, PostgreSQL Row-Level Security policies enforce that only the author can modify or delete their memories. Anonymous users retain read-only search access.
