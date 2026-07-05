"""Unit tests for backend.aggregate (NormalizedRecord[] -> view-models).

Contract: design doc section 5.4, GitHub Issue #5 (T-104).
"""
from __future__ import annotations

import pytest

from backend.aggregate import build_breakdown, build_comparison
from backend.model import ModelUsage, NormalizedRecord, TokenCounts
from backend.normalize import normalize_daily, normalize_session


def _claude_record(group_key, models):
    """Build a NormalizedRecord with record-level totals summed from models."""
    total_tokens = TokenCounts(
        input=sum(m.tokens.input for m in models),
        output=sum(m.tokens.output for m in models),
        cache_creation=sum(m.tokens.cache_creation for m in models),
        cache_read=sum(m.tokens.cache_read for m in models),
        reasoning=sum(m.tokens.reasoning for m in models),
    )
    return NormalizedRecord(
        agent=models[0].agent if models else "claude",
        group_key=group_key,
        group_kind="date",
        tokens=total_tokens,
        cost_usd=sum(m.cost_usd for m in models),
        models=tuple(models),
    )


def _mu(agent, model_name, input=0, output=0, cache_creation=0, cache_read=0, reasoning=0, cost=0.0):
    return ModelUsage(
        agent=agent,
        model_name=model_name,
        tokens=TokenCounts(
            input=input, output=output, cache_creation=cache_creation,
            cache_read=cache_read, reasoning=reasoning,
        ),
        cost_usd=cost,
    )


class TestBuildBreakdownModelDimensionFixtures:
    def test_slices_sum_to_grand_total_and_sorted_desc(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        assert vm["dimension"] == "model"
        assert sum(s["value"] for s in vm["slices"]) == vm["grand_total_tokens"]
        values = [s["value"] for s in vm["slices"]]
        assert values == sorted(values, reverse=True)

    def test_grand_total_tokens_matches_raw_totals(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        assert vm["grand_total_tokens"] == claude_daily_raw["totals"]["totalTokens"]

    def test_pct_sums_to_100(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        assert sum(s["pct"] for s in vm["slices"]) == pytest.approx(100.0, abs=0.1)

    def test_table_rows_have_required_fields(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        for row in vm["table"]:
            for key in (
                "label", "input", "output", "cache_creation", "cache_read",
                "reasoning", "total", "cost_usd",
            ):
                assert key in row
            assert row["total"] == (
                row["input"] + row["output"] + row["cache_creation"]
                + row["cache_read"] + row["reasoning"]
            )

    def test_grand_total_cost_matches_raw(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        assert vm["grand_total_cost"] == pytest.approx(
            claude_daily_raw["totals"]["totalCost"]
        )


class TestBuildBreakdownModelDimensionSynthetic:
    def test_groups_and_sums_across_records(self):
        records = [
            _claude_record("2026-01-01", [
                _mu("claude", "claude-opus", input=10, output=20, cost=1.0),
                _mu("claude", "claude-sonnet", input=5, output=5, cost=0.5),
            ]),
            _claude_record("2026-01-02", [
                _mu("claude", "claude-opus", input=100, output=200, cost=5.0),
            ]),
        ]
        vm = build_breakdown(records, "model")
        by_label = {s["label"]: s["value"] for s in vm["slices"]}
        assert by_label["claude-opus"] == 10 + 20 + 100 + 200
        assert by_label["claude-sonnet"] == 5 + 5
        assert vm["slices"][0]["label"] == "claude-opus"  # sorted desc
        assert vm["grand_total_tokens"] == 10 + 20 + 5 + 5 + 100 + 200

    def test_table_rows_match_slices_labels(self):
        records = [
            _claude_record("2026-01-01", [
                _mu("claude", "claude-opus", input=10, output=20, cost=1.0),
            ]),
        ]
        vm = build_breakdown(records, "model")
        table_labels = {r["label"] for r in vm["table"]}
        slice_labels = {s["label"] for s in vm["slices"]}
        assert table_labels == slice_labels


class TestBuildBreakdownTokenType:
    def test_excludes_always_zero_token_types_claude_only(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "token_type")
        assert vm["dimension"] == "token_type"
        labels = {s["label"] for s in vm["slices"]}
        assert "reasoning" not in labels
        # Claude fixtures have real cache activity, so it should appear.
        assert "cache_read" in labels

    def test_pct_sums_to_100(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "token_type")
        assert sum(s["pct"] for s in vm["slices"]) == pytest.approx(100.0, abs=0.1)

    def test_slices_sorted_desc_and_sum_to_grand_total(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "token_type")
        values = [s["value"] for s in vm["slices"]]
        assert values == sorted(values, reverse=True)
        assert sum(values) == vm["grand_total_tokens"]

    def test_excludes_reasoning_and_cache_when_all_zero_synthetic(self):
        # Codex-shaped records: cache_* always 0, reasoning present.
        records = [
            _claude_record("2026-01-01", [
                _mu("codex", "gpt-5.5", input=10, output=20, reasoning=5, cost=1.0),
            ]),
        ]
        vm = build_breakdown(records, "token_type")
        labels = {s["label"] for s in vm["slices"]}
        assert "cache_creation" not in labels
        assert "cache_read" not in labels
        assert "reasoning" in labels
        assert "input" in labels
        assert "output" in labels


class TestBuildBreakdownSession:
    def test_groups_by_group_key_session_fixture(self, claude_session_raw):
        records = normalize_session(claude_session_raw, agent="claude")
        vm = build_breakdown(records, "session")
        assert vm["dimension"] == "session"
        assert sum(s["value"] for s in vm["slices"]) == vm["grand_total_tokens"]
        # One slice per distinct session group_key present in records.
        expected_keys = {r.group_key for r in records}
        actual_labels = {s["label"] for s in vm["slices"]}
        assert actual_labels == expected_keys

    def test_groups_by_group_key_daily_fixture(self, claude_daily_raw):
        # Same code path, but records are date-grouped when called with
        # daily-normalized records (per contract note in task spec).
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "session")
        expected_keys = {r.group_key for r in records}
        actual_labels = {s["label"] for s in vm["slices"]}
        assert actual_labels == expected_keys
        assert sum(s["value"] for s in vm["slices"]) == vm["grand_total_tokens"]


class TestBuildBreakdownEmptySafe:
    def test_empty_records_gives_zero_grand_total_no_exception(self):
        for dimension in ("model", "token_type", "session"):
            vm = build_breakdown([], dimension)
            assert vm["grand_total_tokens"] == 0
            assert vm["grand_total_cost"] == 0.0
            assert vm["slices"] == []
            assert vm["table"] == []
            assert vm["dimension"] == dimension

    def test_zero_token_records_pct_is_zero_not_nan(self):
        records = [
            _claude_record("2026-01-01", [_mu("claude", "claude-opus", cost=0.0)]),
        ]
        vm = build_breakdown(records, "model")
        assert vm["grand_total_tokens"] == 0
        for s in vm["slices"]:
            assert s["pct"] == 0.0


class TestBuildComparison:
    def test_aligns_model_union_and_totals(self):
        claude_records = [
            _claude_record("2026-01-01", [
                _mu("claude", "opus", input=10, output=10, cost=1.0),
                _mu("claude", "sonnet", input=5, output=5, cost=0.5),
            ]),
        ]
        codex_records = [
            _claude_record("2026-01-01", [
                _mu("codex", "gpt-5.5", input=3, output=3, reasoning=2, cost=0.2),
                _mu("codex", "sonnet", input=1, output=1, cost=0.1),
            ]),
        ]
        vm = build_comparison(claude_records, codex_records)
        assert vm["models"] == sorted({"opus", "sonnet", "gpt-5.5"})
        idx = {m: i for i, m in enumerate(vm["models"])}
        assert vm["series"]["claude"][idx["opus"]] == 20
        assert vm["series"]["claude"][idx["sonnet"]] == 10
        assert vm["series"]["claude"][idx["gpt-5.5"]] == 0
        assert vm["series"]["codex"][idx["gpt-5.5"]] == 8
        assert vm["series"]["codex"][idx["sonnet"]] == 2
        assert vm["series"]["codex"][idx["opus"]] == 0
        assert vm["totals"]["claude"] == 30
        assert vm["totals"]["codex"] == 10

    def test_series_aligned_length_to_models(self):
        claude_records = [_claude_record("d", [_mu("claude", "a", input=1)])]
        codex_records = [_claude_record("d", [_mu("codex", "b", input=2)])]
        vm = build_comparison(claude_records, codex_records)
        assert len(vm["series"]["claude"]) == len(vm["models"])
        assert len(vm["series"]["codex"]) == len(vm["models"])

    def test_empty_both_agents(self):
        vm = build_comparison([], [])
        assert vm["models"] == []
        assert vm["series"]["claude"] == []
        assert vm["series"]["codex"] == []
        assert vm["totals"]["claude"] == 0
        assert vm["totals"]["codex"] == 0

    def test_one_agent_empty(self):
        claude_records = [_claude_record("d", [_mu("claude", "opus", input=10, output=5)])]
        vm = build_comparison(claude_records, [])
        assert vm["models"] == ["opus"]
        assert vm["series"]["claude"] == [15]
        assert vm["series"]["codex"] == [0]
        assert vm["totals"]["claude"] == 15
        assert vm["totals"]["codex"] == 0

    def test_period_label_is_string(self):
        vm = build_comparison([], [])
        assert isinstance(vm["period_label"], str)
