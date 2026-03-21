"""Privacy regression suite — PII detection, scanner bypass prevention, prompt hardening.

Covers issues #52, #53, #54, #55: ensures secrets and PII cannot leak through
any write path (remember, confirm_memory override, update_memory).
"""

from __future__ import annotations

from typing import Any

import pytest

from distill_mcp.adapters.scanner.secret_scanner import SecretScanner
from distill_mcp.domain.models import Memory
from distill_mcp.domain.services import MemoryService

pytestmark = pytest.mark.asyncio


# -- Fakes --


class FakeDistiller:
    def __init__(self, output: str = "Distilled fact") -> None:
        self._output = output

    async def distill(self, raw_text: str) -> str:
        return self._output


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 768


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[Memory] = []
        self._memories: dict[str, Memory] = {}

    async def check_duplicate(
        self, vec: list[float], threshold: float = 0.95
    ) -> str | None:
        return None

    async def save(self, memory: Memory, vec: list[float], **kw: Any) -> str:
        self.saved.append(memory)
        self._memories[memory.id] = memory
        return memory.id

    async def get(self, id: str) -> Memory | None:
        return self._memories.get(id)

    async def delete(self, id: str) -> None:
        self._memories.pop(id, None)

    async def search(self, *a: Any, **kw: Any) -> list:
        return []

    async def list_recent(self, **kw: Any) -> list:
        return []

    async def record_access(self, id: str) -> None:
        pass


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


def _service(
    *,
    scanner: SecretScanner | None = None,
    distiller: FakeDistiller | None = None,
    preview_enabled: bool = True,
) -> tuple[MemoryService, FakeStorage]:
    storage = FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=distiller or FakeDistiller(),
        preview_enabled=preview_enabled,
        scanner=scanner,
    )
    return svc, storage


# ============================================================
# Issue #54 — PII detection in scanner
# ============================================================


@pytest.fixture
def scanner() -> SecretScanner:
    return SecretScanner()


class TestPIIDetection:
    """Scanner must detect emails, phone numbers, URLs, IPs, SSNs, credit cards."""

    def test_email_detected(self, scanner: SecretScanner) -> None:
        assert scanner.has_secrets("Contact alice@example.com for details")

    def test_email_redacted(self, scanner: SecretScanner) -> None:
        clean, findings = scanner.redact("Send to alice@example.com please")
        assert "alice@example.com" not in clean
        assert "[REDACTED email]" in clean
        assert any(f.type == "pii_email" for f in findings)

    def test_phone_detected(self, scanner: SecretScanner) -> None:
        assert scanner.has_secrets("Call me at +1-555-867-5309")

    def test_phone_redacted(self, scanner: SecretScanner) -> None:
        clean, findings = scanner.redact("Phone: +1-555-867-5309")
        assert "555-867-5309" not in clean
        assert any(f.type == "pii_phone" for f in findings)

    def test_custom_url_detected(self, scanner: SecretScanner) -> None:
        assert scanner.has_secrets("Check https://jobs.vasudev.xyz for listings")

    def test_custom_url_redacted(self, scanner: SecretScanner) -> None:
        clean, findings = scanner.redact("Visit https://resume.vasudev.xyz")
        assert "vasudev.xyz" not in clean
        assert any(f.type == "pii_url" for f in findings)

    def test_public_url_allowed(self, scanner: SecretScanner) -> None:
        text = "See https://github.com/user/repo for the source code"
        assert not scanner.has_secrets(text)

    def test_ip_address_detected(self, scanner: SecretScanner) -> None:
        assert scanner.has_secrets("Server is at 192.168.1.42")

    def test_ssn_detected(self, scanner: SecretScanner) -> None:
        assert scanner.has_secrets("SSN is 123-45-6789")

    def test_ssn_redacted(self, scanner: SecretScanner) -> None:
        clean, _ = scanner.redact("SSN: 123-45-6789")
        assert "123-45-6789" not in clean

    def test_normal_prose_still_passes(self, scanner: SecretScanner) -> None:
        text = "PostgreSQL was chosen for its JSONB support and strong consistency guarantees"
        assert not scanner.has_secrets(text)

    def test_multiple_pii_types_redacted(self, scanner: SecretScanner) -> None:
        text = "Email alice@corp.com, call +1-555-0199, visit https://personal.site/cv"
        clean, findings = scanner.redact(text)
        assert "alice@corp.com" not in clean
        assert "555-0199" not in clean
        assert "personal.site" not in clean
        assert len(findings) >= 3


# ============================================================
# Issue #53 — confirm_memory override must be scanned
# ============================================================


class TestConfirmMemoryBypass:
    """Override text in confirm_memory must pass through scanning."""

    async def test_override_with_secret_is_blocked(self) -> None:
        svc, storage = _service(scanner=SecretScanner())
        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        assert preview["status"] == "preview"

        result = await svc.confirm_memory(
            preview["pending_id"],
            override="Use token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx in CI",  # pragma: allowlist secret
        )
        assert result["status"] == "blocked"
        assert len(storage.saved) == 0

    async def test_override_with_email_is_blocked(self) -> None:
        svc, storage = _service(scanner=SecretScanner())
        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])

        result = await svc.confirm_memory(
            preview["pending_id"],
            override="John's email is john.doe@company.com",
        )
        assert result["status"] == "blocked"
        assert len(storage.saved) == 0

    async def test_override_with_clean_text_saves(self) -> None:
        svc, storage = _service(scanner=SecretScanner())
        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])

        result = await svc.confirm_memory(
            preview["pending_id"],
            override="PostgreSQL chosen for pgvector support",
        )
        assert result["status"] == "saved"
        assert len(storage.saved) == 1

    async def test_blocked_override_preserves_pending_entry(self) -> None:
        """A blocked override should re-insert the pending entry so user can retry."""
        svc, _ = _service(scanner=SecretScanner())
        preview = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        pid = preview["pending_id"]

        result = await svc.confirm_memory(
            pid,
            override="Secret: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # pragma: allowlist secret
        )
        assert result["status"] == "blocked"
        # Entry should still be available for retry
        assert pid in svc._pending


# ============================================================
# Issue #53 — update_memory must be scanned
# ============================================================


class TestUpdateMemoryScanning:
    """update_memory must run pre- and post-distillation scanning."""

    async def test_update_with_secret_in_input_redacts(self) -> None:
        svc, storage = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        assert result["status"] == "saved"
        mem_id = result["id"]

        # Update with text containing a secret — should be redacted before distilling
        result = await svc.update(
            mem_id,
            "Changed CI token to ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # pragma: allowlist secret
        )
        # The distiller returns clean text, so this should succeed
        assert result["status"] == "updated"

    async def test_update_blocks_if_distiller_leaks_secret(self) -> None:
        """If the distiller output contains secrets, update should block."""

        class LeakyDistiller:
            call_count = 0

            async def distill(self, raw_text: str) -> str:
                self.call_count += 1
                if self.call_count == 1:
                    return "Distilled fact"
                return "Token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx is used"  # pragma: allowlist secret

        svc, storage = _service(
            scanner=SecretScanner(),
            distiller=LeakyDistiller(),
            preview_enabled=False,
        )
        result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        assert result["status"] == "saved"
        mem_id = result["id"]

        result = await svc.update(mem_id, "Some update text about CI tokens")
        assert result["status"] == "blocked"

    async def test_update_with_email_in_input_redacts(self) -> None:
        svc, storage = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(_VALID_INPUT, "decision", ["repo"])
        assert result["status"] == "saved"

        result = await svc.update(
            result["id"],
            "Contact alice@internal.corp for the deployment runbook",
        )
        # Should succeed — email redacted before distillation, distiller returns clean output
        assert result["status"] == "updated"


# ============================================================
# Issue #55 — integration tests (scanner in full pipeline)
# ============================================================


class TestPipelinePIIIntegration:
    """End-to-end: PII in remember input is redacted before distillation."""

    async def test_email_in_remember_is_redacted(self) -> None:
        svc, _ = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(
            "Alice (alice@megacorp.com) debugged the OOM in the worker pool",
            "failure",
            ["repo"],
        )
        assert result["status"] == "saved"
        assert result["redacted_count"] >= 1

    async def test_url_in_remember_is_redacted(self) -> None:
        svc, _ = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(
            "Portfolio at https://john-portfolio.dev shows the project architecture",
            "context",
            ["repo"],
        )
        assert result["status"] == "saved"
        assert result["redacted_count"] >= 1

    async def test_phone_in_remember_is_redacted(self) -> None:
        svc, _ = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(
            "Call the ops lead at +44 20 7946 0958 if the deploy breaks",
            "context",
            ["repo"],
        )
        assert result["status"] == "saved"
        assert result["redacted_count"] >= 1

    async def test_mixed_pii_all_redacted(self) -> None:
        svc, _ = _service(scanner=SecretScanner(), preview_enabled=False)
        result = await svc.remember(
            "Bob (bob@startup.io, +1-415-555-0123) deployed v2.1 from 192.168.1.50",
            "context",
            ["repo"],
        )
        assert result["status"] == "saved"
        assert result["redacted_count"] >= 3
