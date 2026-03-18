"""Hardware detection for Ollama GPU setup guidance."""

from __future__ import annotations

import platform
import shutil
import subprocess


def detect_hardware() -> dict:
    """Detect available hardware accelerators and Ollama status."""
    result: dict = {
        "platform": platform.system(),
        "arch": platform.machine(),
        "accelerator": "cpu",
        "gpu_name": None,
        "ollama_installed": shutil.which("ollama") is not None,
        "ollama_running": False,
        "recommendations": [],
    }

    # Check NVIDIA GPU
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                result["accelerator"] = "cuda"
                result["gpu_name"] = out.stdout.strip().split("\n")[0]
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Check Apple Silicon
    if result["platform"] == "Darwin" and result["arch"] == "arm64":
        result["accelerator"] = "metal"
        result["gpu_name"] = _get_apple_chip_name()

    # Check Ollama running
    if result["ollama_installed"]:
        try:
            import httpx

            resp = httpx.get("http://localhost:11434/api/version", timeout=2)
            if resp.status_code == 200:
                result["ollama_running"] = True
                result["ollama_version"] = resp.json().get("version", "unknown")
        except Exception:
            pass

    result["recommendations"] = _build_recommendations(result)
    return result


def _get_apple_chip_name() -> str | None:
    """Get Apple Silicon chip name via sysctl."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return "Apple Silicon"


def _build_recommendations(info: dict) -> list[str]:
    recs = []

    if not info["ollama_installed"]:
        recs.append("Install Ollama: https://ollama.com/download")
    elif not info["ollama_running"]:
        recs.append("Start Ollama: ollama serve")

    if info["accelerator"] == "cuda":
        recs.append("NVIDIA GPU detected — Ollama will use CUDA automatically")
        recs.append(
            "To limit GPU layers: export OLLAMA_NUM_GPU=999 (all) or 0 (CPU only)"
        )
        recs.append("Recommended models: gemma3:4b (distill), nomic-embed-text (embed)")
    elif info["accelerator"] == "metal":
        recs.append(
            "Apple Silicon detected — Ollama uses Metal acceleration by default"
        )
        recs.append("Recommended models: gemma3:4b (distill), nomic-embed-text (embed)")
    else:
        recs.append("No GPU detected — Ollama will run on CPU (slower but functional)")
        recs.append(
            "Consider smaller models for faster inference: gemma3:1b, all-minilm"
        )
        recs.append("Set OLLAMA_NUM_PARALLEL=1 to reduce memory pressure")

    return recs


def format_report(info: dict) -> str:
    """Format hardware detection results as a human-readable report."""
    lines = [
        "Hardware Detection Report",
        "=" * 40,
        f"Platform:     {info['platform']} ({info['arch']})",
        f"Accelerator:  {info['accelerator'].upper()}",
    ]
    if info["gpu_name"]:
        lines.append(f"GPU:          {info['gpu_name']}")

    lines.append(
        f"Ollama:       {'installed' if info['ollama_installed'] else 'not found'}"
    )
    if info["ollama_running"]:
        lines.append(f"              running (v{info.get('ollama_version', '?')})")
    elif info["ollama_installed"]:
        lines.append("              not running")

    if info["recommendations"]:
        lines.append("")
        lines.append("Recommendations:")
        for rec in info["recommendations"]:
            lines.append(f"  - {rec}")

    return "\n".join(lines)
