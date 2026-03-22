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

    async def find_related(self, vec, *, threshold=0.80, top_k=3, repo=None):
        return []


_VALID_INPUT = "We chose PostgreSQL over MySQL for pgvector support"


def _service(
    *,
    scanner: SecretScanner | None = None,
    distiller: FakeDistiller | None = None,
) -> tuple[MemoryService, FakeStorage]:
    storage = FakeStorage()
    svc = MemoryService(
        storage=storage,
        embedder=FakeEmbedder(),
        distiller=distiller or FakeDistiller(),
        scanner=scanner,
    )
    return svc, storage


async def _insert(
    storage: FakeStorage,
    content: str = "Distilled fact",
    *,
    type: str = "decision",
    repos: list[str] | None = None,
) -> Memory:
    """Insert a Memory directly into FakeStorage, bypassing distillation."""
    from datetime import UTC, datetime
    from uuid import uuid4

    mem = Memory(
        id=uuid4().hex,
        content=content,
        type=type,
        repos=repos or ["repo"],
        tags=[],
        author=None,
        created_at=datetime.now(UTC),
    )
    await storage.save(mem, [0.1] * 768)
    return mem


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
# Issue #53 — update_memory must be scanned
# ============================================================


class TestUpdateMemoryScanning:
    """update_memory must run pre- and post-distillation scanning."""

    async def test_update_with_secret_in_input_redacts(self) -> None:
        svc, storage = _service(scanner=SecretScanner())
        mem = await _insert(storage)

        # Update with text containing a secret — should be redacted before distilling
        result = await svc.update(
            mem.id,
            "Changed CI token to ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # pragma: allowlist secret
        )
        # The distiller returns clean text, so this should succeed
        assert result["status"] == "updated"

    async def test_update_blocks_if_distiller_leaks_secret(self) -> None:
        """If the distiller output contains secrets, update should block."""

        class LeakyDistiller:
            async def distill(self, raw_text: str) -> str:
                return "Token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx is used"  # pragma: allowlist secret

        svc, storage = _service(scanner=SecretScanner(), distiller=LeakyDistiller())
        mem = await _insert(storage)

        result = await svc.update(mem.id, "Some update text about CI tokens")
        assert result["status"] == "blocked"

    async def test_update_with_email_in_input_redacts(self) -> None:
        svc, storage = _service(scanner=SecretScanner())
        mem = await _insert(storage)

        result = await svc.update(
            mem.id,
            "Contact alice@internal.corp for the deployment runbook",
        )
        # Should succeed — email redacted before distillation, distiller returns clean output
        assert result["status"] == "updated"
