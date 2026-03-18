"""Identity model and read-only degradation."""

from unittest.mock import patch

from distill_mcp.adapters.identity.git_identity import resolve_git_identity
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


def test_resolve_git_identity_returns_email_and_repo(tmp_path):
    """When git config has user.email and we're in a repo, both are resolved."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": "dev@example.com\n"})(),
            type(
                "Result",
                (),
                {"returncode": 0, "stdout": "git@github.com:team/distill.git\n"},
            )(),
        ]
        ident = resolve_git_identity()
    assert ident.email == "dev@example.com"
    assert ident.repos == ["distill"]


def test_resolve_git_identity_no_email_returns_anonymous():
    """When git config user.email fails, returns ANONYMOUS."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("Result", (), {"returncode": 1, "stdout": ""})()
        ident = resolve_git_identity()
    assert ident.is_anonymous


def test_resolve_git_identity_no_repo_returns_email_only():
    """When in a non-git directory, email is resolved but repos is empty."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            type("Result", (), {"returncode": 0, "stdout": "dev@example.com\n"})(),
            type("Result", (), {"returncode": 1, "stdout": ""})(),
        ]
        ident = resolve_git_identity()
    assert ident.email == "dev@example.com"
    assert ident.repos == []
