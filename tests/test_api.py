"""Unit tests for app.api.Api (pywebview JS bridge) and app.config.

All tests inject a fake client -- no live npx call, no GUI/pywebview window
is ever started (design doc section 5.6/5.7, task T-106 acceptance).
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from app import config as config_module
from app.api import Api
from backend.errors import (
    CcusageFailedError,
    CcusageParseError,
    CcusageTimeoutError,
    NodeMissingError,
)
from backend.errors import NodeStatus


# ---------------------------------------------------------------------------
# Module-level config isolation -- EVERY test in this module that can reach
# app.config.load_config()/save_config() must be isolated from the real
# %APPDATA%/usage-widget/config.json (review Major-2). Class-scoped fixtures
# alone missed TestGetStatus, which leaked a real file onto this machine.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "_config_dir", lambda: tmp_path / "usage-widget")


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakeClient:
    """Stub matching backend.ccusage_client's public function signatures."""

    def __init__(self, daily=None, session=None, node_status=NodeStatus.OK, raise_exc=None):
        # daily/session: dict keyed by agent -> raw ccusage JSON dict
        self.daily = daily or {}
        self.session = session or {}
        self.node_status = node_status
        self.raise_exc = raise_exc
        self.calls = []

    def check_node_available(self):
        return self.node_status

    def run_ccusage(self, agent, subcommand, since=None, until=None, timezone=None, timeout_s=60.0):
        self.calls.append(
            {
                "agent": agent,
                "subcommand": subcommand,
                "since": since,
                "until": until,
                "timezone": timezone,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        if subcommand == "daily":
            return self.daily.get(agent, {"daily": []})
        if subcommand == "session":
            return self.session.get(agent, {"sessions": []})
        raise ValueError(f"unexpected subcommand: {subcommand}")


def _claude_day(date, tokens=100, model="claude-sonnet-4-6"):
    return {
        "date": date,
        "inputTokens": tokens,
        "outputTokens": 0,
        "cacheCreationTokens": 0,
        "cacheReadTokens": 0,
        "totalTokens": tokens,
        "totalCost": 1.0,
        "modelsUsed": [model],
        "modelBreakdowns": [
            {
                "modelName": model,
                "inputTokens": tokens,
                "outputTokens": 0,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 0,
                "cost": 1.0,
            }
        ],
    }


def _codex_day(date, tokens=50, model="gpt-5-codex"):
    return {
        "date": date,
        "inputTokens": tokens,
        "outputTokens": 0,
        "reasoningOutputTokens": 0,
        "totalTokens": tokens,
        "costUSD": 0.5,
        "modelsUsed": [model],
        "modelBreakdowns": [
            {
                "modelName": model,
                "inputTokens": tokens,
                "outputTokens": 0,
                "reasoningOutputTokens": 0,
                "cost": 0.5,
            }
        ],
    }


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_node_ok(self):
        client = FakeClient(node_status=NodeStatus.OK)
        api = Api(client=client)

        status = api.get_status()

        assert status["node"] == "ok"
        assert status["poll_interval_s"] == 60

    def test_node_missing(self):
        client = FakeClient(node_status=NodeStatus.MISSING)
        api = Api(client=client)

        status = api.get_status()

        assert status["node"] == "missing"

    def test_corrupt_config_degrades_gracefully(self, monkeypatch):
        """A corrupt/unreadable config.json must not raise across the bridge
        (design section 5.6) -- get_status should degrade to defaults."""
        import app.api as api_module

        def _broken_load_config():
            raise json.JSONDecodeError("bad json", "doc", 0)

        monkeypatch.setattr(api_module.config_module, "load_config", _broken_load_config)
        client = FakeClient(node_status=NodeStatus.OK)
        api = Api(client=client)

        status = api.get_status()

        assert status["node"] == "ok"
        assert status["poll_interval_s"] == config_module.DEFAULT_CONFIG["poll_interval_s"]

    def test_config_io_error_degrades_gracefully(self, monkeypatch):
        import app.api as api_module

        def _broken_load_config():
            raise OSError("disk error")

        monkeypatch.setattr(api_module.config_module, "load_config", _broken_load_config)
        client = FakeClient(node_status=NodeStatus.OK)
        api = Api(client=client)

        status = api.get_status()

        assert status["node"] == "ok"
        assert status["poll_interval_s"] == config_module.DEFAULT_CONFIG["poll_interval_s"]


# ---------------------------------------------------------------------------
# period -> since/until mapping
# ---------------------------------------------------------------------------


class TestPeriodMapping:
    def test_7d_since_until(self):
        client = FakeClient(daily={"claude": {"daily": [_claude_day("2026-07-01")]}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        api.get_breakdown("7d", "model", "claude")

        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["since"] == "20260629"
        assert call["until"] == "20260705"

    def test_30d_since_until(self):
        client = FakeClient(daily={"claude": {"daily": []}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        api.get_breakdown("30d", "model", "claude")

        call = client.calls[0]
        assert call["since"] == "20260606"
        assert call["until"] == "20260705"

    def test_24h_since_until(self):
        client = FakeClient(daily={"claude": {"daily": []}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        api.get_breakdown("24h", "model", "claude")

        call = client.calls[0]
        assert call["since"] == "20260704"
        assert call["until"] == "20260705"


# ---------------------------------------------------------------------------
# get_breakdown
# ---------------------------------------------------------------------------


class TestGetBreakdown:
    def test_claude_only_shape(self):
        client = FakeClient(
            daily={"claude": {"daily": [_claude_day("2026-07-01", tokens=100)]}}
        )
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        vm = api.get_breakdown("7d", "model", "claude")

        assert vm["dimension"] == "model"
        assert vm["grand_total_tokens"] == 100
        assert vm["slices"][0]["label"] == "claude-sonnet-4-6"
        assert vm["table"][0]["total"] == 100

    def test_session_dimension_calls_session_subcommand(self):
        client = FakeClient(
            session={
                "claude": {
                    "sessions": [
                        {
                            "sessionId": "abcdef1234567890",
                            "lastActivity": "2026-07-01T00:00:00Z",
                            "inputTokens": 10,
                            "outputTokens": 0,
                            "cacheCreationTokens": 0,
                            "cacheReadTokens": 0,
                            "totalTokens": 10,
                            "totalCost": 0.1,
                            "modelsUsed": ["claude-sonnet-4-6"],
                            "modelBreakdowns": [
                                {
                                    "modelName": "claude-sonnet-4-6",
                                    "inputTokens": 10,
                                    "outputTokens": 0,
                                    "cacheCreationTokens": 0,
                                    "cacheReadTokens": 0,
                                    "cost": 0.1,
                                }
                            ],
                        }
                    ]
                }
            }
        )
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        vm = api.get_breakdown("7d", "session", "claude")

        assert client.calls[0]["subcommand"] == "session"
        assert vm["dimension"] == "session"
        assert vm["grand_total_tokens"] == 10

    def test_model_dimension_calls_daily_subcommand(self):
        client = FakeClient(daily={"claude": {"daily": [_claude_day("2026-07-01")]}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        api.get_breakdown("7d", "model", "claude")

        assert client.calls[0]["subcommand"] == "daily"

    def test_token_type_dimension_calls_daily_subcommand(self):
        client = FakeClient(daily={"claude": {"daily": [_claude_day("2026-07-01")]}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        api.get_breakdown("7d", "token_type", "claude")

        assert client.calls[0]["subcommand"] == "daily"

    def test_agent_all_merges_claude_and_codex(self):
        client = FakeClient(
            daily={
                "claude": {"daily": [_claude_day("2026-07-01", tokens=100)]},
                "codex": {"daily": [_codex_day("2026-07-01", tokens=50)]},
            }
        )
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        vm = api.get_breakdown("7d", "model", "all")

        # both claude + codex calls should have happened
        agents_called = {c["agent"] for c in client.calls}
        assert agents_called == {"claude", "codex"}
        assert vm["grand_total_tokens"] == 150

    def test_empty_period_returns_empty_vm_not_error(self):
        client = FakeClient(daily={"claude": {"daily": []}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        vm = api.get_breakdown("7d", "model", "claude")

        assert "error" not in vm
        assert vm["grand_total_tokens"] == 0
        assert vm["slices"] == []


# ---------------------------------------------------------------------------
# error contract - never raises across the bridge
# ---------------------------------------------------------------------------


class TestErrorContract:
    @pytest.mark.parametrize(
        "exc, code",
        [
            (NodeMissingError("node missing"), "node_missing"),
            (CcusageFailedError("boom"), "ccusage_failed"),
            (CcusageTimeoutError("timed out"), "ccusage_timeout"),
            (CcusageParseError("bad json"), "ccusage_parse"),
        ],
    )
    def test_get_breakdown_catches_backend_errors(self, exc, code):
        client = FakeClient(raise_exc=exc)
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.get_breakdown("7d", "model", "claude")

        assert result == {"error": code, "message": str(exc)}

    def test_get_comparison_catches_backend_errors(self):
        client = FakeClient(raise_exc=CcusageFailedError("boom"))
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.get_comparison("7d")

        assert result == {"error": "ccusage_failed", "message": "boom"}

    def test_copy_json_catches_backend_errors(self, monkeypatch):
        import app.api as api_module

        monkeypatch.setattr(api_module.pyperclip, "copy", lambda s: None)
        client = FakeClient(raise_exc=CcusageTimeoutError("slow"))
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.copy_json("7d", "model", "claude")

        assert result == {"error": "ccusage_timeout", "message": "slow"}

    def test_copy_markdown_catches_backend_errors(self, monkeypatch):
        import app.api as api_module

        monkeypatch.setattr(api_module.pyperclip, "copy", lambda s: None)
        client = FakeClient(raise_exc=CcusageParseError("bad"))
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.copy_markdown("7d")

        assert result == {"error": "ccusage_parse", "message": "bad"}

    def test_get_breakdown_unknown_period_returns_bad_request(self):
        client = FakeClient(daily={"claude": {"daily": []}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.get_breakdown("bogus-period", "model", "claude")

        assert result["error"] == "bad_request"
        assert "bogus-period" in result["message"]

    def test_get_breakdown_unknown_dimension_returns_bad_request(self):
        client = FakeClient(daily={"claude": {"daily": [_claude_day("2026-07-01")]}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.get_breakdown("7d", "bogus-dimension", "claude")

        assert result["error"] == "bad_request"
        assert "bogus-dimension" in result["message"]

    def test_get_comparison_unknown_period_returns_bad_request(self):
        client = FakeClient(daily={"claude": {"daily": []}, "codex": {"daily": []}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.get_comparison("bogus-period")

        assert result["error"] == "bad_request"
        assert "bogus-period" in result["message"]


# ---------------------------------------------------------------------------
# get_comparison
# ---------------------------------------------------------------------------


class TestGetComparison:
    def test_builds_comparison_from_both_agents(self):
        client = FakeClient(
            daily={
                "claude": {"daily": [_claude_day("2026-07-01", tokens=100)]},
                "codex": {"daily": [_codex_day("2026-07-01", tokens=50)]},
            }
        )
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        vm = api.get_comparison("7d")

        assert vm["totals"]["claude"] == 100
        assert vm["totals"]["codex"] == 50
        agents_called = {c["agent"] for c in client.calls}
        assert agents_called == {"claude", "codex"}


# ---------------------------------------------------------------------------
# copy_json / copy_markdown
# ---------------------------------------------------------------------------


class TestCopyJson:
    def test_copies_serialized_vm_and_returns_ok(self, monkeypatch):
        import app.api as api_module

        copied = {}

        def fake_copy(s):
            copied["text"] = s

        monkeypatch.setattr(api_module.pyperclip, "copy", fake_copy)

        client = FakeClient(daily={"claude": {"daily": [_claude_day("2026-07-01", tokens=100)]}})
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.copy_json("7d", "model", "claude")

        assert result == {"ok": True}
        parsed = json.loads(copied["text"])
        assert parsed["grand_total_tokens"] == 100


class TestCopyMarkdown:
    def test_copies_markdown_and_returns_ok(self, monkeypatch):
        import app.api as api_module

        copied = {}

        def fake_copy(s):
            copied["text"] = s

        monkeypatch.setattr(api_module.pyperclip, "copy", fake_copy)

        client = FakeClient(
            daily={
                "claude": {"daily": [_claude_day("2026-07-01", tokens=100)]},
                "codex": {"daily": [_codex_day("2026-07-01", tokens=50)]},
            }
        )
        api = Api(client=client, clock=lambda: dt.date(2026, 7, 5))

        result = api.copy_markdown("7d")

        assert result == {"ok": True}
        assert "使用量サマリー" in copied["text"]
        assert "Claude Code" in copied["text"]
        assert "Codex" in copied["text"]


# ---------------------------------------------------------------------------
# config get/set (round-trip via app.api.Api, isolated from real APPDATA)
# ---------------------------------------------------------------------------


class TestConfigViaApi:
    def test_get_config_returns_defaults_when_missing(self):
        client = FakeClient()
        api = Api(client=client)

        cfg = api.get_config()

        assert cfg == {"poll_interval_s": 60, "default_period": "7d", "timezone": None}

    def test_set_config_roundtrips(self):
        client = FakeClient()
        api = Api(client=client)

        result = api.set_config({"poll_interval_s": 120})

        assert result["poll_interval_s"] == 120
        assert api.get_config()["poll_interval_s"] == 120


# ---------------------------------------------------------------------------
# app.config module directly (isolated from real APPDATA)
# ---------------------------------------------------------------------------


class TestConfigModule:
    def test_load_config_creates_defaults_when_missing(self, tmp_path):
        cfg = config_module.load_config()

        assert cfg == {"poll_interval_s": 60, "default_period": "7d", "timezone": None}
        config_path = tmp_path / "usage-widget" / "config.json"
        assert config_path.exists()

    def test_save_config_merges_and_persists(self):
        config_module.load_config()

        result = config_module.save_config({"default_period": "30d"})

        assert result == {"poll_interval_s": 60, "default_period": "30d", "timezone": None}
        reloaded = config_module.load_config()
        assert reloaded["default_period"] == "30d"

    def test_save_config_partial_patch_preserves_other_keys(self):
        config_module.save_config({"poll_interval_s": 30})
        result = config_module.save_config({"timezone": "Asia/Tokyo"})

        assert result == {
            "poll_interval_s": 30,
            "default_period": "7d",
            "timezone": "Asia/Tokyo",
        }

    def test_load_config_falls_back_to_defaults_on_corrupt_json(self, tmp_path):
        config_dir = tmp_path / "usage-widget"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("{ not valid json ]", encoding="utf-8")

        cfg = config_module.load_config()

        assert cfg == config_module.DEFAULT_CONFIG
