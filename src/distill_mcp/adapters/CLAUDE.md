# Adapters — implementations of domain ports

## Distillation rules (distiller/ollama_distill.py, distiller/gemini_distill.py)

The distillation prompt (shared by both providers) must:
- Remove all first-person language (I, we, my)
- Remove all names of people
- Remove emotional language, blame, frustration
- Replace vague time refs ("yesterday") with approximate dates ("2026-03")
- Keep: technical facts, decisions, reasons, repo names, tech names, version numbers
- Output: 1-3 sentences of pure factual knowledge
- Never add information not in the input

## Privacy constraints

- `DISTILLER_PROVIDER=ollama` (default): raw text goes only to localhost Ollama.
- `DISTILLER_PROVIDER=gemini`: raw text goes to Google Gemini — user opt-in.
- `AUTHOR_MODE` env var: `anonymous` (default) | `pseudonym` | `named`. Developer's local choice.
- `REVIEW_BEFORE_SAVE=true` by default. Developer approves distilled output before storing.
- Anthropic only sees distilled search results via Claude Code context window.

## Schema constraints

- All embeddings: 768 dimensions. Hardcoded. Do NOT change without migration.
- `tsvector` uses `'simple'` config by default. Configurable via `FTS_LANGUAGE`.
- Dedup: cosine similarity > 0.95 → reject insert, return existing memory ID.
