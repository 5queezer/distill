"""Deterministic secret scanner wrapping detect-secrets (Yelp, MIT)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    type: str
    display: str


class SecretScanner:
    """Thin wrapper around detect-secrets for pre/post distillation scanning."""

    def __init__(self) -> None:
        # Import lazily so the module is importable even without detect-secrets
        # installed (callers can check availability first).
        from detect_secrets import SecretsCollection  # noqa: F401
        from detect_secrets.settings import default_settings  # noqa: F401

    def _scan_via_file(self, text: str):
        """Scan text by writing to a temp file (SecretsCollection API)."""
        from detect_secrets import SecretsCollection
        from detect_secrets.settings import default_settings

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            fname = f.name

        try:
            secrets = SecretsCollection()
            with default_settings():
                secrets.scan_file(fname)
            return list(secrets)
        finally:
            import os

            os.unlink(fname)

    def scan(self, text: str) -> list[Finding]:
        """Return all secrets found in *text*."""
        results = self._scan_via_file(text)
        seen: set[str] = set()
        findings: list[Finding] = []
        for _, secret in results:
            key = f"{secret.type}:{secret.secret_hash}"
            if key not in seen:
                seen.add(key)
                display = secret.secret_value or secret.secret_hash[:8]
                findings.append(Finding(type=secret.type, display=display))
        return findings

    def redact(self, text: str) -> tuple[str, list[Finding]]:
        """Redact secrets in *text*. Returns (clean_text, findings)."""
        results = self._scan_via_file(text)

        findings: list[Finding] = []
        seen: set[str] = set()
        # Collect all secret values to redact, longest first to avoid
        # partial replacements.
        replacements: list[tuple[str, str]] = []
        for _, secret in results:
            key = f"{secret.type}:{secret.secret_hash}"
            if key not in seen:
                seen.add(key)
                display = secret.secret_value or secret.secret_hash[:8]
                findings.append(Finding(type=secret.type, display=display))
                if secret.secret_value:
                    replacements.append(
                        (secret.secret_value, f"[REDACTED {secret.type}]")
                    )

        # Sort by length descending so longer secrets are replaced first.
        replacements.sort(key=lambda r: len(r[0]), reverse=True)
        redacted = text
        for old, new in replacements:
            redacted = redacted.replace(old, new)
        return redacted, findings

    def has_secrets(self, text: str) -> bool:
        """Return True if any secret is detected in *text*."""
        return len(self._scan_via_file(text)) > 0
