"""Pure serialization: view-model -> JSON string / Markdown string
(design doc section 5.5).

Two public entry points only. Never touches subprocess/GUI/file IO.

Markdown format MUST match spec 6.2 exactly:
  ## 使用量サマリー（<period_label>）
  ### Claude Code
  - <model>: <total-with-commas> tokens (input X%, output X%, cache read X%, cache write X%)
  ### Codex
  - <model>: <total-with-commas> tokens (input X%, output X%, reasoning X%)
Agent with no data -> "- (データなし)" instead of bullet lines.
"""
from __future__ import annotations

import json


def to_json(vm) -> str:
    """Pretty-print any view-model (breakdown or comparison dict) as JSON.

    Generic: does not care whether `vm` is a BreakdownVM, ComparisonVM, or
    any other JSON-serializable object.
    """
    return json.dumps(vm, indent=2, ensure_ascii=False)


def _pct(value: int, total: int) -> int:
    if total == 0:
        return 0
    return round(value / total * 100)


def _claude_model_line(row: dict) -> str:
    total = row["total"]
    input_pct = _pct(row["input"], total)
    output_pct = _pct(row["output"], total)
    cache_read_pct = _pct(row["cache_read"], total)
    cache_write_pct = _pct(row["cache_creation"], total)
    return (
        f"- {row['label']}: {total:,} tokens "
        f"(input {input_pct}%, output {output_pct}%, "
        f"cache read {cache_read_pct}%, cache write {cache_write_pct}%)"
    )


def _codex_model_line(row: dict) -> str:
    total = row["total"]
    input_pct = _pct(row["input"], total)
    output_pct = _pct(row["output"], total)
    reasoning_pct = _pct(row["reasoning"], total)
    return (
        f"- {row['label']}: {total:,} tokens "
        f"(input {input_pct}%, output {output_pct}%, reasoning {reasoning_pct}%)"
    )


def _agent_section(bd, line_fn) -> list[str]:
    if bd is None or not bd.get("table"):
        return ["- (データなし)"]
    return [line_fn(row) for row in bd["table"]]


def to_markdown(bd_claude, bd_codex, period_label: str) -> str:
    """Render the Claude Code + Codex breakdown VMs as the spec 6.2 Markdown
    summary. bd_claude/bd_codex are BreakdownVM (dimension="model") or None
    when that agent has no data for the period.
    """
    lines = [f"## 使用量サマリー（{period_label}）"]
    lines.append("### Claude Code")
    lines.extend(_agent_section(bd_claude, _claude_model_line))
    lines.append("### Codex")
    lines.extend(_agent_section(bd_codex, _codex_model_line))
    return "\n".join(lines)
