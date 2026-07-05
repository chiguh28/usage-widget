"""Unit tests for backend.ccusage_client (the sole subprocess boundary).

All tests monkeypatch subprocess.run -- no live npx invocation, must run
fast and fully offline (design doc section 5.2 / 7).
"""
import subprocess

import pytest

from backend.ccusage_client import check_node_available, run_ccusage
from backend.errors import (
    CcusageFailedError,
    CcusageParseError,
    CcusageTimeoutError,
    NodeMissingError,
    NodeStatus,
)


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRunCcusageArgList:
    def test_builds_minimal_arg_list_when_since_until_tz_omitted(self, monkeypatch):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _FakeCompletedProcess(returncode=0, stdout='{"daily": []}', stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = run_ccusage("claude", "daily")

        assert captured["args"] == [
            "npx",
            "ccusage@latest",
            "claude",
            "daily",
            "--json",
        ]
        assert result == {"daily": []}

    def test_builds_full_arg_list_when_since_until_tz_given(self, monkeypatch):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _FakeCompletedProcess(returncode=0, stdout='{"daily": []}', stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        run_ccusage(
            "codex",
            "session",
            since="20260101",
            until="20260131",
            timezone="Asia/Tokyo",
            timeout_s=30.0,
        )

        assert captured["args"] == [
            "npx",
            "ccusage@latest",
            "codex",
            "session",
            "--json",
            "--since",
            "20260101",
            "--until",
            "20260131",
            "-z",
            "Asia/Tokyo",
        ]

    def test_uses_shell_false_and_timeout_and_utf8_encoding(self, monkeypatch):
        captured = {}

        def fake_run(args, **kwargs):
            captured["kwargs"] = kwargs
            return _FakeCompletedProcess(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        run_ccusage("claude", "daily", timeout_s=42.0)

        assert captured["kwargs"]["shell"] is False
        assert captured["kwargs"]["timeout"] == 42.0
        assert captured["kwargs"]["encoding"] == "utf-8"

    def test_only_since_given_omits_until_and_tz(self, monkeypatch):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            return _FakeCompletedProcess(returncode=0, stdout="{}", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        run_ccusage("claude", "daily", since="20260101")

        assert captured["args"] == [
            "npx",
            "ccusage@latest",
            "claude",
            "daily",
            "--json",
            "--since",
            "20260101",
        ]


class TestRunCcusageErrorMapping:
    def test_file_not_found_raises_node_missing_error(self, monkeypatch):
        def fake_run(args, **kwargs):
            raise FileNotFoundError("node not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(NodeMissingError):
            run_ccusage("claude", "daily")

    def test_timeout_expired_raises_ccusage_timeout_error(self, monkeypatch):
        def fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 60.0))

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(CcusageTimeoutError):
            run_ccusage("claude", "daily", timeout_s=5.0)

    def test_nonzero_exit_raises_ccusage_failed_error_with_stderr(self, monkeypatch):
        def fake_run(args, **kwargs):
            return _FakeCompletedProcess(
                returncode=1, stdout="", stderr="some ccusage failure detail"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(CcusageFailedError) as exc_info:
            run_ccusage("claude", "daily")

        assert "some ccusage failure detail" in str(exc_info.value)

    def test_malformed_json_stdout_raises_ccusage_parse_error(self, monkeypatch):
        def fake_run(args, **kwargs):
            return _FakeCompletedProcess(returncode=0, stdout="{not valid json", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(CcusageParseError):
            run_ccusage("claude", "daily")


class TestCheckNodeAvailable:
    def test_returns_ok_when_node_and_npx_both_succeed(self, monkeypatch):
        def fake_run(args, **kwargs):
            return _FakeCompletedProcess(returncode=0, stdout="v20.0.0", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert check_node_available() == NodeStatus.OK

    def test_returns_missing_when_node_not_found(self, monkeypatch):
        def fake_run(args, **kwargs):
            if args[0] == "node":
                raise FileNotFoundError("node not found")
            return _FakeCompletedProcess(returncode=0, stdout="v10.0.0", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert check_node_available() == NodeStatus.MISSING

    def test_returns_missing_when_npx_not_found(self, monkeypatch):
        def fake_run(args, **kwargs):
            if args[0] == "npx":
                raise FileNotFoundError("npx not found")
            return _FakeCompletedProcess(returncode=0, stdout="v20.0.0", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert check_node_available() == NodeStatus.MISSING

    def test_returns_missing_when_node_exits_nonzero(self, monkeypatch):
        def fake_run(args, **kwargs):
            if args[0] == "node":
                return _FakeCompletedProcess(returncode=1, stdout="", stderr="error")
            return _FakeCompletedProcess(returncode=0, stdout="v10.0.0", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert check_node_available() == NodeStatus.MISSING
