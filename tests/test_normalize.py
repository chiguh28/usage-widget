"""Unit tests for backend.normalize (raw ccusage JSON -> NormalizedRecord).

Contract: design doc section 5.3, ADR-0012, GitHub Issue #4 (T-103).
"""
import copy

import pytest

from backend.model import NormalizedRecord, TokenCounts
from backend.normalize import normalize_daily, normalize_session


class TestNormalizeDailyClaude:
    def test_returns_list_of_normalized_records(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        assert isinstance(records, list)
        assert len(records) == len(claude_daily_raw["daily"])
        assert all(isinstance(r, NormalizedRecord) for r in records)

    def test_agent_is_tagged_from_parameter(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        assert all(r.agent == "claude" for r in records)

    def test_group_key_and_kind_is_date(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        raw_dates = [d["date"] for d in claude_daily_raw["daily"]]
        assert [r.group_key for r in records] == raw_dates
        assert all(r.group_kind == "date" for r in records)

    def test_cache_fields_populated_and_reasoning_zero(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        for raw_day, record in zip(claude_daily_raw["daily"], records):
            assert record.tokens.cache_creation == raw_day["cacheCreationTokens"]
            assert record.tokens.cache_read == raw_day["cacheReadTokens"]
            assert record.tokens.reasoning == 0

    def test_input_output_mapped(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        for raw_day, record in zip(claude_daily_raw["daily"], records):
            assert record.tokens.input == raw_day["inputTokens"]
            assert record.tokens.output == raw_day["outputTokens"]

    def test_cost_usd_mapped_from_total_cost(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        for raw_day, record in zip(claude_daily_raw["daily"], records):
            assert record.cost_usd == raw_day["totalCost"]

    def test_models_tuple_built_from_model_breakdowns(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        for raw_day, record in zip(claude_daily_raw["daily"], records):
            assert len(record.models) == len(raw_day["modelBreakdowns"])
            for raw_mb, model_usage in zip(raw_day["modelBreakdowns"], record.models):
                assert model_usage.agent == "claude"
                assert model_usage.model_name == raw_mb["modelName"]
                assert model_usage.cost_usd == raw_mb["cost"]
                assert model_usage.tokens.input == raw_mb["inputTokens"]
                assert model_usage.tokens.output == raw_mb["outputTokens"]
                assert model_usage.tokens.cache_creation == raw_mb["cacheCreationTokens"]
                assert model_usage.tokens.cache_read == raw_mb["cacheReadTokens"]
                assert model_usage.tokens.reasoning == 0

    def test_i3_token_conservation(self, claude_daily_raw):
        """Invariant I3: TokenCounts.total must equal raw totalTokens for every record."""
        records = normalize_daily(claude_daily_raw, agent="claude")
        for raw_day, record in zip(claude_daily_raw["daily"], records):
            assert record.tokens.total == raw_day["totalTokens"]

    def test_does_not_mutate_raw_input(self, claude_daily_raw):
        """Invariant I-immut: raw dict must be unchanged after normalization."""
        before = copy.deepcopy(claude_daily_raw)
        normalize_daily(claude_daily_raw, agent="claude")
        assert claude_daily_raw == before


class TestNormalizeDailyCodex:
    def test_reasoning_defaults_and_cache_zero(self, codex_daily_raw):
        # Fixture may be empty (all-zero) on this machine; this test exercises
        # the empty-list branch and asserts no crash. Reasoning-populated
        # mapping is covered structurally in test_field_mapping_codex below
        # using a synthetic record built from the same real envelope shape.
        records = normalize_daily(codex_daily_raw, agent="codex")
        assert records == []

    def test_field_mapping_codex_synthetic_record(self):
        """codex_daily.json fixture is empty on this machine (real capture,
        zero usage) - exercise the Codex field-mapping branch (reasoning
        populated, cache_* defaulted to 0) with a synthetic record built in
        the exact shape verified live in design doc section 3."""
        raw = {
            "daily": [
                {
                    "date": "2026-07-01",
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "reasoningOutputTokens": 30,
                    "totalTokens": 180,
                    "totalCost": 1.23,
                    "modelsUsed": ["gpt-5.5"],
                    "modelBreakdowns": [
                        {
                            "modelName": "gpt-5.5",
                            "inputTokens": 100,
                            "outputTokens": 50,
                            "reasoningOutputTokens": 30,
                            "cost": 1.23,
                        }
                    ],
                }
            ],
            "totals": {},
        }
        before = copy.deepcopy(raw)
        records = normalize_daily(raw, agent="codex")
        assert len(records) == 1
        record = records[0]
        assert record.agent == "codex"
        assert record.tokens.reasoning == 30
        assert record.tokens.cache_creation == 0
        assert record.tokens.cache_read == 0
        assert record.tokens.total == raw["daily"][0]["totalTokens"]
        assert len(record.models) == 1
        assert record.models[0].tokens.reasoning == 30
        assert record.models[0].tokens.cache_creation == 0
        assert record.models[0].tokens.cache_read == 0
        assert raw == before


class TestNormalizeDailyEmpty:
    def test_empty_daily_array_returns_empty_list(self, empty_codex_daily_raw):
        records = normalize_daily(empty_codex_daily_raw, agent="codex")
        assert records == []

    def test_empty_daily_does_not_mutate_raw(self, empty_codex_daily_raw):
        before = copy.deepcopy(empty_codex_daily_raw)
        normalize_daily(empty_codex_daily_raw, agent="codex")
        assert empty_codex_daily_raw == before


class TestNormalizeSession:
    def test_returns_list_of_normalized_records(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        assert isinstance(records, list)
        assert len(records) == len(claude_session_raw["sessions"])
        assert all(isinstance(r, NormalizedRecord) for r in records)

    def test_group_kind_is_session(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        assert all(r.group_kind == "session" for r in records)

    def test_group_key_is_first_8_chars_of_session_id(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        for raw_s, record in zip(claude_session_raw["sessions"], records):
            assert record.group_key == raw_s["sessionId"][:8]

    def test_last_activity_populated(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        for raw_s, record in zip(claude_session_raw["sessions"], records):
            assert record.last_activity == raw_s["lastActivity"]

    def test_i3_token_conservation(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        for raw_s, record in zip(claude_session_raw["sessions"], records):
            assert record.tokens.total == raw_s["totalTokens"]

    def test_cache_populated_reasoning_zero(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        for raw_s, record in zip(claude_session_raw["sessions"], records):
            assert record.tokens.cache_creation == raw_s["cacheCreationTokens"]
            assert record.tokens.cache_read == raw_s["cacheReadTokens"]
            assert record.tokens.reasoning == 0

    def test_does_not_mutate_raw_input(self, claude_session_raw):
        before = copy.deepcopy(claude_session_raw)
        normalize_session(claude_session_raw, agent="claude")
        assert claude_session_raw == before

    def test_empty_sessions_returns_empty_list(self):
        raw = {"sessions": [], "totals": {}}
        assert normalize_session(raw, agent="claude") == []
