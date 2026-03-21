---
title: Privacy Model
---

# Privacy Model

## The core guarantee

**With `DISTILLER_PROVIDER=ollama` (default), your raw text never crosses a network boundary.**

```text
Developer input (raw text)
        │
        ▼
   ┌─────────────┐
   │ private_store│ ← JSONL, never synced, local only
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │  Distiller   │ ← ollama: localhost / gemini: Google API
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

Every "memory MCP" stores your raw text in a database. Distill doesn't. The LLM is a mandatory privacy gateway that transforms personal thoughts into impersonal team knowledge. With `DISTILLER_PROVIDER=ollama`, your exact words never leave your machine.

## FAQ

| Question | Answer |
|----------|--------|
| Does Anthropic see my raw input? | No. It goes to the distiller: Ollama (local) or Gemini (Google). |
| Can my team read what I typed? | No. Only the distilled fact is stored. |
| Can my manager see who wrote what? | Only if you opt in (`AUTH_ENABLED=true`). Anonymous by default. |
| Where is my raw text? | `~/.distill/private/` on your machine. Delete anytime. |
| What if distillation leaks a name? | You review every output before it's saved. The scanner also checks for secrets. |

## The scanner: secrets and PII

The scanner runs at two points in the pipeline: **before** distillation (to protect the local LLM input) and **after** distillation (to catch anything the model reproduced). It detects two categories of sensitive content:

### Secrets

API keys, tokens, passwords, connection strings — anything that looks like a credential. These are redacted with `[REDACTED]` markers before the text proceeds.

### PII

In addition to secrets, the scanner detects personally identifiable information:

| PII type | Examples | Handling |
|----------|----------|----------|
| Email addresses | `user@company.com` | Redacted |
| Phone numbers | `+1-555-0123`, `(555) 867-5309` | Redacted |
| URLs and domains | `internal.corp.net`, `192.168.1.1/admin` | Redacted (with allowlist) |
| IP addresses | `10.0.0.5`, `2001:db8::1` | Redacted |
| SSNs | `123-45-6789` | Redacted |
| Credit card numbers | `4111-1111-1111-1111` | Redacted |

**URL allowlist:** Public sites like `github.com`, `pypi.org`, and `stackoverflow.com` are not redacted — these appear frequently in technical knowledge and aren't personally identifying.

### Scanner coverage

The scanner runs on all paths that write to the team database:

- `remember()` — scans raw input before distillation, scans distilled output after
- `confirm_memory()` with `override` — scans the user-provided override text
- `update_memory()` — scans the new input through the full pipeline

Previously, `confirm_memory` overrides and `update_memory` bypassed the scanner. This has been fixed — all write paths now pass through PII and secret scanning.

## Author modes

| Mode | Behavior |
|------|----------|
| `anonymous` (default) | No author attribution stored |
| `AUTH_ENABLED=true` | Git identity (`user.email`) used for ownership and RLS enforcement |

When authentication is enabled, PostgreSQL Row-Level Security policies enforce that only the author can modify or delete their memories. Anonymous users retain read-only search access.

## Cloud distillation (`DISTILLER_PROVIDER=gemini`)

Setting `DISTILLER_PROVIDER=gemini` sends raw text to Google's Gemini API for distillation. This means **raw text leaves your device**.

Use this when:

- Local compute resources are limited (no GPU, low RAM)
- The privacy tradeoff is acceptable for your team
- You want $0 cost without running Ollama

The same distillation prompt runs on Gemini — names, emotions, and PII are still stripped. The scanner still checks output for leaked secrets. The difference is the distillation happens in Google's cloud, not on your machine.
