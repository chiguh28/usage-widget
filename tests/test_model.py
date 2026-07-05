"""Unit tests for backend.model normalized dataclasses (ADR-0012)."""
import dataclasses

import pytest

from backend.model import ModelUsage, NormalizedRecord, TokenCounts


class TestTokenCounts:
    def test_defaults_are_all_zero(self):
        tc = TokenCounts()
        assert tc.input == 0
        assert tc.output == 0
        assert tc.cache_creation == 0
        assert tc.cache_read == 0
        assert tc.reasoning == 0
        assert tc.total == 0

    def test_total_sums_all_five_fields(self):
        tc = TokenCounts(input=1, output=2, cache_creation=3, cache_read=4, reasoning=5)
        assert tc.total == 15

    def test_total_with_only_claude_fields_populated(self):
        # Claude-only: cache_* populated, reasoning always 0.
        tc = TokenCounts(input=10, output=20, cache_creation=30, cache_read=40, reasoning=0)
        assert tc.total == 100

    def test_total_with_only_codex_fields_populated(self):
        # Codex-only: reasoning populated, cache_* always 0.
        tc = TokenCounts(input=10, output=20, cache_creation=0, cache_read=0, reasoning=5)
        assert tc.total == 35

    def test_is_frozen(self):
        tc = TokenCounts()
        with pytest.raises(dataclasses.FrozenInstanceError):
            tc.input = 99


class TestModelUsage:
    def test_construction(self):
        tokens = TokenCounts(input=1, output=2)
        mu = ModelUsage(agent="claude", model_name="claude-opus-4", tokens=tokens, cost_usd=1.23)
        assert mu.agent == "claude"
        assert mu.model_name == "claude-opus-4"
        assert mu.tokens is tokens
        assert mu.cost_usd == 1.23

    def test_is_frozen(self):
        mu = ModelUsage(agent="claude", model_name="x", tokens=TokenCounts(), cost_usd=0.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            mu.cost_usd = 5.0


class TestNormalizedRecord:
    def test_construction_daily(self):
        tokens = TokenCounts(input=1, output=2, cache_creation=3, cache_read=4)
        models = (ModelUsage(agent="claude", model_name="claude-opus-4", tokens=tokens, cost_usd=0.5),)
        rec = NormalizedRecord(
            agent="claude",
            group_key="2026-07-01",
            group_kind="date",
            tokens=tokens,
            cost_usd=0.5,
            models=models,
        )
        assert rec.agent == "claude"
        assert rec.group_key == "2026-07-01"
        assert rec.group_kind == "date"
        assert rec.tokens is tokens
        assert rec.cost_usd == 0.5
        assert rec.models == models
        assert rec.last_activity is None

    def test_construction_session_with_last_activity(self):
        tokens = TokenCounts(input=1, output=2)
        models = (ModelUsage(agent="codex", model_name="gpt-5.5", tokens=tokens, cost_usd=0.1),)
        rec = NormalizedRecord(
            agent="codex",
            group_key="abcd1234",
            group_kind="session",
            tokens=tokens,
            cost_usd=0.1,
            models=models,
            last_activity="2026-07-01T00:00:00Z",
        )
        assert rec.group_kind == "session"
        assert rec.last_activity == "2026-07-01T00:00:00Z"

    def test_is_frozen(self):
        tokens = TokenCounts()
        rec = NormalizedRecord(
            agent="claude",
            group_key="k",
            group_kind="date",
            tokens=tokens,
            cost_usd=0.0,
            models=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rec.agent = "codex"
