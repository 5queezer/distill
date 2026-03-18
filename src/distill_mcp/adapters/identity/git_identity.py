"""Resolve user identity from local git config."""

from __future__ import annotations

import subprocess

from distill_mcp.domain.identity import ANONYMOUS, Identity


def resolve_git_identity() -> Identity:
    """Read user.email and current repo from git. Returns ANONYMOUS on failure."""
    email = _git_config_email()
    if email is None:
        return ANONYMOUS
    repos = _detect_repos()
    return Identity(email=email, repos=repos)


def _git_config_email() -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        email = result.stdout.strip()
        return email if email else None
    except Exception:
        return None


def _detect_repos() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return []
        repo_name = result.stdout.strip().split("/")[-1].removesuffix(".git")
        return [repo_name] if repo_name else []
    except Exception:
        return []
