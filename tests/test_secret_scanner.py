"""Tests for SecretScanner -- pre/post distillation secret detection."""

from __future__ import annotations

import pytest

from distill_mcp.adapters.scanner.secret_scanner import SecretScanner

pytestmark = pytest.mark.asyncio


@pytest.fixture
def scanner() -> SecretScanner:
    return SecretScanner()


def test_github_token_detected(scanner):
    text = (
        "token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # pragma: allowlist secret
    )
    assert scanner.has_secrets(text)


def test_github_token_redacted(scanner):
    text = (
        "token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # pragma: allowlist secret
    )
    clean, findings = scanner.redact(text)
    assert "ghp_" not in clean
    assert len(findings) >= 1


def test_jwt_detected(scanner):
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    assert scanner.has_secrets(jwt)


def test_normal_text_passes(scanner):
    text = "We decided to use PostgreSQL for the event store because of JSONB support and strong consistency guarantees"
    assert not scanner.has_secrets(text)


def test_redact_returns_clean_text(scanner):
    text = "Set token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx in CI"  # pragma: allowlist secret
    clean, _findings = scanner.redact(text)
    assert "ghp_" not in clean
    assert "[REDACTED" in clean


def test_scan_returns_findings(scanner):
    text = (
        "token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # pragma: allowlist secret
    )
    findings = scanner.scan(text)
    assert len(findings) >= 1
    assert findings[0].type is not None


def test_has_secrets_false_on_empty(scanner):
    assert not scanner.has_secrets("")


def test_has_secrets_false_on_prose(scanner):
    assert not scanner.has_secrets(
        "The team agreed to migrate from REST to GraphQL for the mobile API layer"
    )
