"""Tests for hardware detection module."""

from unittest.mock import patch

from distill_mcp.hardware import _build_recommendations, detect_hardware, format_report


def test_detect_hardware_returns_expected_keys():
    info = detect_hardware()
    assert "platform" in info
    assert "arch" in info
    assert "accelerator" in info
    assert "ollama_installed" in info
    assert "ollama_running" in info
    assert "recommendations" in info
    assert info["accelerator"] in ("cuda", "metal", "cpu")


def test_recommendations_cpu_fallback():
    info = {
        "accelerator": "cpu",
        "ollama_installed": True,
        "ollama_running": True,
    }
    recs = _build_recommendations(info)
    assert any("CPU" in r for r in recs)
    assert any("OLLAMA_NUM_PARALLEL" in r for r in recs)


def test_recommendations_cuda():
    info = {
        "accelerator": "cuda",
        "ollama_installed": True,
        "ollama_running": True,
    }
    recs = _build_recommendations(info)
    assert any("NVIDIA" in r for r in recs)
    assert any("OLLAMA_NUM_GPU" in r for r in recs)


def test_recommendations_metal():
    info = {
        "accelerator": "metal",
        "ollama_installed": True,
        "ollama_running": True,
    }
    recs = _build_recommendations(info)
    assert any("Apple Silicon" in r for r in recs)


def test_recommendations_ollama_not_installed():
    info = {
        "accelerator": "cpu",
        "ollama_installed": False,
        "ollama_running": False,
    }
    recs = _build_recommendations(info)
    assert any("Install Ollama" in r for r in recs)


def test_recommendations_ollama_not_running():
    info = {
        "accelerator": "cpu",
        "ollama_installed": True,
        "ollama_running": False,
    }
    recs = _build_recommendations(info)
    assert any("ollama serve" in r for r in recs)


def test_format_report_includes_key_info():
    info = {
        "platform": "Linux",
        "arch": "x86_64",
        "accelerator": "cuda",
        "gpu_name": "NVIDIA RTX 3090, 24576 MiB",
        "ollama_installed": True,
        "ollama_running": True,
        "ollama_version": "0.6.2",
        "recommendations": ["NVIDIA GPU detected"],
    }
    report = format_report(info)
    assert "Linux" in report
    assert "CUDA" in report
    assert "RTX 3090" in report
    assert "running" in report


def test_format_report_no_gpu():
    info = {
        "platform": "Linux",
        "arch": "x86_64",
        "accelerator": "cpu",
        "gpu_name": None,
        "ollama_installed": False,
        "ollama_running": False,
        "recommendations": ["Install Ollama"],
    }
    report = format_report(info)
    assert "CPU" in report
    assert "not found" in report


@patch("distill_mcp.hardware.shutil.which", return_value=None)
def test_detect_hardware_no_tools(mock_which):
    """When neither nvidia-smi nor ollama are found, falls back to CPU."""
    info = detect_hardware()
    assert info["accelerator"] in ("cpu", "metal")  # metal on macOS ARM
    assert not info["ollama_installed"]
