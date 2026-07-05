"""Unit tests for backend.export (view-model -> JSON string / Markdown string).

Contract: design doc section 5.5, GitHub Issue #6 (T-105).
"""
from __future__ import annotations

import json
import re

import pytest

from backend.aggregate import build_breakdown
from backend.export import to_json, to_markdown
from backend.model import ModelUsage, NormalizedRecord, TokenCounts
from backend.normalize import normalize_daily


def _claude_record(group_key, models):
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


def _fmt_commas(n: int) -> str:
    return f"{n:,}"


class TestToMarkdownClaude:
    def test_golden_string_from_fixture(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        bd_claude = build_breakdown(records, "model")
        md = to_markdown(bd_claude, None, "test-period")

        lines = md.splitlines()
        assert lines[0] == "## 使用量サマリー（test-period）"
        assert lines[1] == "### Claude Code"

        # One bullet per model row, in table order.
        model_lines = lines[2:2 + len(bd_claude["table"])]
        assert len(model_lines) == len(bd_claude["table"])

        for line, row in zip(model_lines, bd_claude["table"]):
            expected_total = _fmt_commas(row["total"])
            assert line.startswith(f"- {row['label']}: {expected_total} tokens (")
            assert line.endswith(")")

            m = re.search(
                r"\(input (\d+)%, output (\d+)%, cache read (\d+)%, cache write (\d+)%\)",
                line,
            )
            assert m is not None, f"line did not match expected pattern: {line}"
            input_pct, output_pct, cache_read_pct, cache_write_pct = (int(g) for g in m.groups())

            total = row["total"]
            expected_input_pct = round(row["input"] / total * 100)
            expected_output_pct = round(row["output"] / total * 100)
            expected_cache_read_pct = round(row["cache_read"] / total * 100)
            expected_cache_write_pct = round(row["cache_creation"] / total * 100)

            assert input_pct == expected_input_pct
            assert output_pct == expected_output_pct
            assert cache_read_pct == expected_cache_read_pct
            assert cache_write_pct == expected_cache_write_pct

            pct_sum = input_pct + output_pct + cache_read_pct + cache_write_pct
            assert pct_sum == pytest.approx(100, abs=2)

        # Codex section still present with no-data marker.
        assert "### Codex" in lines
        codex_idx = lines.index("### Codex")
        assert lines[codex_idx + 1] == "- (データなし)"

    def test_bullet_order_matches_table_order(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        bd_claude = build_breakdown(records, "model")
        md = to_markdown(bd_claude, None, "p")
        lines = md.splitlines()
        model_lines = lines[2:2 + len(bd_claude["table"])]
        labels_in_md = [line.split(":")[0][2:] for line in model_lines]
        expected_labels = [row["label"] for row in bd_claude["table"]]
        assert labels_in_md == expected_labels


class TestToMarkdownCodex:
    def _codex_breakdown(self):
        records = [
            _claude_record("2026-07-01", [
                _mu("codex", "gpt-5-codex", input=195200, output=48800, reasoning=366000, cost=1.5),
            ]),
            _claude_record("2026-07-02", [
                _mu("codex", "gpt-5.5", input=10000, output=5000, reasoning=5000, cost=0.2),
            ]),
        ]
        return build_breakdown(records, "model")

    def test_reasoning_pct_instead_of_cache(self):
        bd_codex = self._codex_breakdown()
        md = to_markdown(None, bd_codex, "test-period")
        lines = md.splitlines()

        assert lines[0] == "## 使用量サマリー（test-period）"
        assert lines[1] == "### Claude Code"
        assert lines[2] == "- (データなし)"
        assert "### Codex" in lines
        codex_idx = lines.index("### Codex")
        model_lines = lines[codex_idx + 1:codex_idx + 1 + len(bd_codex["table"])]
        assert len(model_lines) == len(bd_codex["table"])

        for line, row in zip(model_lines, bd_codex["table"]):
            expected_total = _fmt_commas(row["total"])
            assert line.startswith(f"- {row['label']}: {expected_total} tokens (")
            assert "cache read" not in line
            assert "cache write" not in line

            m = re.search(
                r"\(input (\d+)%, output (\d+)%, reasoning (\d+)%\)", line
            )
            assert m is not None, f"line did not match expected pattern: {line}"
            input_pct, output_pct, reasoning_pct = (int(g) for g in m.groups())

            total = row["total"]
            expected_input_pct = round(row["input"] / total * 100)
            expected_output_pct = round(row["output"] / total * 100)
            expected_reasoning_pct = round(row["reasoning"] / total * 100)

            assert input_pct == expected_input_pct
            assert output_pct == expected_output_pct
            assert reasoning_pct == expected_reasoning_pct

            pct_sum = input_pct + output_pct + reasoning_pct
            assert pct_sum == pytest.approx(100, abs=2)

    def test_gpt_5_codex_example_shape(self):
        # Mirrors the original spec example line shape (model name, comma total).
        bd_codex = self._codex_breakdown()
        md = to_markdown(None, bd_codex, "2026-07-01〜07-05")
        assert "gpt-5-codex: 610,000 tokens (" in md


class TestToMarkdownNoData:
    def test_both_agents_none_renders_no_data_for_both(self):
        md = to_markdown(None, None, "empty-period")
        lines = md.splitlines()
        assert lines[0] == "## 使用量サマリー（empty-period）"
        assert lines[1] == "### Claude Code"
        assert lines[2] == "- (データなし)"
        assert lines[3] == "### Codex"
        assert lines[4] == "- (データなし)"

    def test_empty_breakdown_vm_treated_like_no_data(self):
        # An empty (but non-None) BreakdownVM (no records, empty table)
        # renders the same "no data" marker as bd_claude=None.
        empty_vm = build_breakdown([], "model")
        md = to_markdown(empty_vm, None, "p")
        lines = md.splitlines()
        assert lines[0] == "## 使用量サマリー（p）"
        assert lines[1] == "### Claude Code"
        assert lines[2] == "- (データなし)"
        assert lines[3] == "### Codex"
        assert lines[4] == "- (データなし)"


class TestToJson:
    def test_round_trips_plain_dict(self):
        vm = {"a": 1, "b": [1, 2, 3], "c": {"x": "y"}}
        s = to_json(vm)
        assert json.loads(s) == vm

    def test_pretty_printed_indent_2(self):
        vm = {"a": 1}
        s = to_json(vm)
        assert s == json.dumps(vm, indent=2, ensure_ascii=False)

    def test_japanese_characters_unescaped(self):
        vm = {"label": "使用量サマリー"}
        s = to_json(vm)
        assert "使用量サマリー" in s
        assert "\\u" not in s

    def test_breakdown_vm_round_trips(self, claude_daily_raw):
        records = normalize_daily(claude_daily_raw, agent="claude")
        vm = build_breakdown(records, "model")
        s = to_json(vm)
        assert json.loads(s) == vm
