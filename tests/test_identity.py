"""Identity model and read-only degradation."""

from distill_mcp.domain.identity import ANONYMOUS, Identity


def test_identity_has_email_and_repos():
    ident = Identity(email="dev@example.com", repos=["distill"])
    assert ident.email == "dev@example.com"
    assert ident.repos == ["distill"]


def test_identity_is_anonymous_when_no_email():
    assert ANONYMOUS.is_anonymous
    assert ANONYMOUS.email is None
    assert ANONYMOUS.repos == []


def test_identity_is_not_anonymous_when_email_set():
    ident = Identity(email="dev@example.com", repos=["distill"])
    assert not ident.is_anonymous
