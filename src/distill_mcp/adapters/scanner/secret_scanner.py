"""Deterministic secret + PII scanner wrapping detect-secrets (Yelp, MIT)."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    type: str
    display: str


# PII regex patterns — deterministic, no LLM required
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")),
    ("phone", re.compile(r"\+?\d[\d\s\-()]{7,}\d")),
    (
        "url",
        re.compile(
            r"https?://[^\s<>\"']+|(?<!\w)[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s<>\"']*)?",
        ),
    ),
    ("ip_address", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
]

# Tech terms that look like URLs but are safe to keep
_URL_ALLOWLIST = frozenset(
    {
        "github.com",
        "gitlab.com",
        "pypi.org",
        "npmjs.com",
        "crates.io",
        "docs.python.org",
        "developer.mozilla.org",
        "stackoverflow.com",
        "en.wikipedia.org",
    }
)


def _is_allowed_url(match: str) -> bool:
    """Return True if the URL is a well-known public documentation/package site."""
    lower = match.lower()
    return any(domain in lower for domain in _URL_ALLOWLIST)


class SecretScanner:
    """Thin wrapper around detect-secrets + PII regex for pre/post distillation scanning."""

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

    @staticmethod
    def _scan_pii(text: str) -> list[tuple[str, str]]:
        """Return list of (pii_type, matched_value) for PII patterns found in text."""
        hits: list[tuple[str, str]] = []
        for pii_type, pattern in _PII_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group().strip()
                if pii_type == "url" and _is_allowed_url(value):
                    continue
                hits.append((pii_type, value))
        return hits

    def scan(self, text: str) -> list[Finding]:
        """Return all secrets and PII found in *text*."""
        results = self._scan_via_file(text)
        seen: set[str] = set()
        findings: list[Finding] = []
        for _, secret in results:
            key = f"{secret.type}:{secret.secret_hash}"
            if key not in seen:
                seen.add(key)
                display = secret.secret_value or secret.secret_hash[:8]
                findings.append(Finding(type=secret.type, display=display))

        # PII scan
        for pii_type, value in self._scan_pii(text):
            key = f"pii_{pii_type}:{value}"
            if key not in seen:
                seen.add(key)
                findings.append(Finding(type=f"pii_{pii_type}", display=value))
        return findings

    def redact(self, text: str) -> tuple[str, list[Finding]]:
        """Redact secrets and PII in *text*. Returns (clean_text, findings)."""
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

        # PII redaction
        for pii_type, value in self._scan_pii(text):
            key = f"pii_{pii_type}:{value}"
            if key not in seen:
                seen.add(key)
                findings.append(Finding(type=f"pii_{pii_type}", display=value))
                replacements.append((value, f"[REDACTED {pii_type}]"))

        # Sort by length descending so longer matches are replaced first.
        replacements.sort(key=lambda r: len(r[0]), reverse=True)
        redacted = text
        for old, new in replacements:
            redacted = redacted.replace(old, new)
        return redacted, findings

    def has_secrets(self, text: str) -> bool:
        """Return True if any secret or PII is detected in *text*."""
        if len(self._scan_via_file(text)) > 0:
            return True
        return len(self._scan_pii(text)) > 0
