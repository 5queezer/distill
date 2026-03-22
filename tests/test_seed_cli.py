"""Tests for `distill seed` CLI command."""

from __future__ import annotations

import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import ClassVar
from unittest.mock import patch

import pytest

from distill_mcp.__main__ import _run_seed


class _IngestHandler(BaseHTTPRequestHandler):
    """Minimal handler that collects POSTed observations."""

    received: ClassVar[list[dict]] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _IngestHandler.received.append(body)
        self.send_response(202)
        self.end_headers()
        self.wfile.write(b"Accepted")

    def log_message(self, *_args):
        pass  # suppress stderr noise


@pytest.fixture()
def ingest_server():
    """Start a throwaway HTTP server that mimics the /observe endpoint."""
    _IngestHandler.received = []
    server = HTTPServer(("127.0.0.1", 0), _IngestHandler)
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield port, _IngestHandler.received
    server.shutdown()


GIT_LOG = (
    "aaa0000000\x002024-06-01T10:00:00+00:00\x00feat: add search endpoint\n"
    "bbb1111111\x002024-06-02T11:00:00+00:00\x00chore: fix lint\n"
    "ccc2222222\x002024-06-03T12:00:00+00:00\x00fix: handle empty query\n"
)


def _make_git_mock(
    *,
    toplevel="/home/user/my-repo",
    origin="git@github.com:user/my-repo.git",
    log=GIT_LOG,
    stat=" file.py | 1 +\n",
):
    """Return a fake subprocess.check_output that handles git subcommands."""

    def fake(cmd, *, text=False, stderr=None):
        sub = cmd[1]
        if sub == "rev-parse":
            return f"{toplevel}\n"
        if sub == "remote":
            if origin is None:
                raise subprocess.CalledProcessError(1, cmd)
            return f"{origin}\n"
        if sub == "log":
            return log
        if sub == "show":
            return stat
        raise ValueError(f"unexpected git command: {cmd}")

    return fake


def test_seed_posts_non_trivial_commits(ingest_server):
    port, received = ingest_server
    mock = _make_git_mock(log=GIT_LOG, stat=" server.py | 10 +++++++---\n")

    with patch("subprocess.check_output", side_effect=mock):
        _run_seed(port=port)

    # "chore: fix lint" should be skipped; the other two should be posted
    assert len(received) == 2
    assert received[0]["tool_name"] == "seed"
    assert "my-repo@aaa0000000" in received[0]["input"]
    assert "add search endpoint" in received[0]["output"]
    assert received[1]["input"].startswith("my-repo@ccc2222222")


def test_seed_skips_merge_commits(ingest_server):
    port, received = ingest_server
    log = "ddd3333333\x002024-07-01T10:00:00+00:00\x00Merge pull request #42\n"
    mock = _make_git_mock(log=log)

    with patch("subprocess.check_output", side_effect=mock):
        _run_seed(port=port)

    assert len(received) == 0


def test_seed_exits_when_server_unreachable():
    mock = _make_git_mock(
        log="aaa\x002024-01-01T00:00:00+00:00\x00feat: something\n", stat=""
    )

    with (
        patch("subprocess.check_output", side_effect=mock),
        pytest.raises(SystemExit) as exc_info,
    ):
        _run_seed(port=1)  # port 1 is unreachable

    assert exc_info.value.code == 1


def test_seed_since_flag(ingest_server):
    port, received = ingest_server
    captured_cmds: list[list[str]] = []

    base_mock = _make_git_mock(log="")

    def capturing_mock(cmd, *, text=False, stderr=None):
        captured_cmds.append(list(cmd))
        return base_mock(cmd, text=text, stderr=stderr)

    with patch("subprocess.check_output", side_effect=capturing_mock):
        _run_seed(since="2024-06-01", port=port)

    log_cmd = next(c for c in captured_cmds if c[1] == "log")
    assert "--since=2024-06-01" in log_cmd


def test_seed_uses_origin_for_repo_name(ingest_server):
    port, received = ingest_server
    log = "eee\x002024-08-01T00:00:00+00:00\x00feat: init\n"
    mock = _make_git_mock(
        toplevel="/tmp/some-worktree",
        origin="git@github.com:org/actual-repo.git",
        log=log,
        stat="",
    )

    with patch("subprocess.check_output", side_effect=mock):
        _run_seed(port=port)

    assert len(received) == 1
    assert "actual-repo@" in received[0]["input"]


def test_seed_falls_back_to_toplevel_without_remote(ingest_server):
    port, received = ingest_server
    log = "fff\x002024-09-01T00:00:00+00:00\x00feat: local only\n"
    mock = _make_git_mock(
        toplevel="/home/user/local-project",
        origin=None,
        log=log,
        stat="",
    )

    with patch("subprocess.check_output", side_effect=mock):
        _run_seed(port=port)

    assert len(received) == 1
    assert "local-project@" in received[0]["input"]
