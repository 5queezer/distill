---
title: GPU Setup
---

# GPU Setup

Distill uses Ollama for local LLM inference (distillation and embeddings). Ollama automatically detects your hardware, but you may want to tune it for your specific GPU.

## Check your hardware

Run the built-in hardware detection:

```bash
distill check-hardware
```

Or from source:

```bash
uv run python -m distill_mcp check-hardware
```

This reports your detected accelerator, Ollama status, and recommended configuration.

## NVIDIA GPUs (CUDA)

Ollama detects NVIDIA GPUs automatically when CUDA drivers are installed.

### Prerequisites

1. NVIDIA driver 525+ installed
2. [Ollama](https://ollama.com/download) installed via the official installer (includes CUDA support)

### Verify GPU detection

```bash
# Check driver
nvidia-smi

# Ollama should show GPU in logs
ollama serve
# Look for: "using CUDA"
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_GPU` | auto | Number of GPU layers. `999` = all layers on GPU, `0` = CPU only |
| `CUDA_VISIBLE_DEVICES` | all | Restrict to specific GPUs (e.g., `0` for first GPU) |

```bash
# Force all layers on GPU (maximum speed)
export OLLAMA_NUM_GPU=999

# Use only first GPU on multi-GPU systems
export CUDA_VISIBLE_DEVICES=0
```

### Recommended models

| Model | Use | VRAM required |
|-------|-----|---------------|
| `gemma3:4b` | Distillation | ~3 GB |
| `nomic-embed-text` | Embeddings | ~300 MB |
| `gemma3:1b` | Distillation (low VRAM) | ~1 GB |

GPUs with 6+ GB VRAM (RTX 3060+) handle the default models comfortably.

## Apple Silicon (Metal)

Ollama uses Metal acceleration automatically on Apple Silicon Macs.

### Prerequisites

1. macOS 13+ (Ventura or later)
2. [Ollama](https://ollama.com/download/mac) installed

### Verify Metal acceleration

```bash
ollama serve
# Look for: "using Metal"
```

No additional configuration needed. Metal uses unified memory, so available VRAM equals your system RAM.

### Recommended models

| Mac | RAM | Recommended distiller |
|-----|-----|----------------------|
| M1/M2 (8 GB) | 8 GB | `gemma3:1b` |
| M1/M2/M3 (16 GB) | 16 GB | `gemma3:4b` (default) |
| M3/M4 Pro/Max (32+ GB) | 32+ GB | `gemma3:4b` (default) |

## CPU only

Ollama works without a GPU, using CPU inference. This is slower but fully functional.

### Performance expectations

| Operation | GPU (RTX 3060) | Apple M2 | CPU (8-core) |
|-----------|---------------|----------|--------------|
| Distillation | ~2s | ~3s | ~15s |
| Embedding | <1s | <1s | ~2s |

### Tuning for CPU

```bash
# Reduce parallel requests to lower memory pressure
export OLLAMA_NUM_PARALLEL=1

# Use smaller models for faster inference
export LLM_MODEL=gemma3:1b
export EMBEDDING_MODEL=all-minilm
```

!!! warning "Embedding dimension compatibility"
    If you change `EMBEDDING_MODEL`, the new model must produce the same vector dimensions as `nomic-embed-text` (768). Using `all-minilm` (384-dim) requires a fresh database — existing embeddings won't be compatible. Stick with `nomic-embed-text` unless you're starting fresh.

## Ollama environment variables

These are Ollama's own variables, not Distill settings. Set them before starting Ollama.

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_GPU` | auto | GPU layers to offload (`999` = all, `0` = none) |
| `OLLAMA_NUM_PARALLEL` | auto | Concurrent request slots |
| `OLLAMA_MAX_LOADED_MODELS` | auto | Models kept in memory simultaneously |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Listen address (also used by Distill) |
| `CUDA_VISIBLE_DEVICES` | all | Restrict NVIDIA GPU visibility |

## Troubleshooting

**Ollama doesn't detect my GPU**

- NVIDIA: ensure `nvidia-smi` works. If not, install/update drivers.
- Apple Silicon: ensure you're on macOS 13+. Check `uname -m` shows `arm64`.
- Docker: pass `--gpus all` flag when running Ollama in a container.

**Out of memory errors**

- Reduce `OLLAMA_NUM_GPU` to offload fewer layers to GPU.
- Use a smaller model (`gemma3:1b` instead of `gemma3:4b`).
- Set `OLLAMA_NUM_PARALLEL=1` to prevent concurrent model loading.

**Slow inference on CPU**

- Expected. CPU inference is 5-10x slower than GPU.
- Use `gemma3:1b` for distillation — quality is acceptable for fact extraction.
- Embedding speed is less affected since `nomic-embed-text` is a small model.
