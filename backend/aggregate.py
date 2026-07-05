"""Pure aggregation: NormalizedRecord[] -> view-models (design doc section 5.4).

Two public entry points only. Never touches subprocess/GUI. Pure functions
over the ADR-0012 normalized model.

Invariants:
- Never divide by zero: grand_total_tokens == 0 -> every pct is 0.0.
- slices sorted by value descending.
- token_type dimension filters out token types that are always 0 across
  every record/model passed in.
"""
from __future__ import annotations

from backend.model import TokenCounts, NormalizedRecord

TOKEN_TYPES = ("input", "output", "cache_creation", "cache_read", "reasoning")


def _pct(value: int, grand_total: int) -> float:
    if grand_total == 0:
        return 0.0
    return value / grand_total * 100.0


def _slices_from_totals(totals: dict[str, int], grand_total_tokens: int) -> list[dict]:
    slices = [
        {"label": label, "value": value, "pct": _pct(value, grand_total_tokens)}
        for label, value in totals.items()
    ]
    slices.sort(key=lambda s: s["value"], reverse=True)
    return slices


def _table_row(label: str, tokens: TokenCounts, cost_usd: float) -> dict:
    return {
        "label": label,
        "input": tokens.input,
        "output": tokens.output,
        "cache_creation": tokens.cache_creation,
        "cache_read": tokens.cache_read,
        "reasoning": tokens.reasoning,
        "total": tokens.total,
        "cost_usd": cost_usd,
    }


def _empty_breakdown_vm(dimension: str, period_label: str) -> dict:
    return {
        "dimension": dimension,
        "period_label": period_label,
        "slices": [],
        "table": [],
        "grand_total_tokens": 0,
        "grand_total_cost": 0.0,
    }


def _build_breakdown_model(records: list[NormalizedRecord], period_label: str) -> dict:
    token_totals: dict[str, int] = {}
    cost_totals: dict[str, float] = {}
    tokens_by_label: dict[str, TokenCounts] = {}

    for record in records:
        for mu in record.models:
            label = mu.model_name
            token_totals[label] = token_totals.get(label, 0) + mu.tokens.total
            cost_totals[label] = cost_totals.get(label, 0.0) + mu.cost_usd
            prev = tokens_by_label.get(label)
            if prev is None:
                tokens_by_label[label] = mu.tokens
            else:
                tokens_by_label[label] = TokenCounts(
                    input=prev.input + mu.tokens.input,
                    output=prev.output + mu.tokens.output,
                    cache_creation=prev.cache_creation + mu.tokens.cache_creation,
                    cache_read=prev.cache_read + mu.tokens.cache_read,
                    reasoning=prev.reasoning + mu.tokens.reasoning,
                )

    grand_total_tokens = sum(token_totals.values())
    grand_total_cost = sum(cost_totals.values())
    slices = _slices_from_totals(token_totals, grand_total_tokens)
    table = [
        _table_row(label, tokens_by_label[label], cost_totals[label])
        for label in token_totals
    ]
    table.sort(key=lambda r: r["total"], reverse=True)

    return {
        "dimension": "model",
        "period_label": period_label,
        "slices": slices,
        "table": table,
        "grand_total_tokens": grand_total_tokens,
        "grand_total_cost": grand_total_cost,
    }


def _build_breakdown_token_type(records: list[NormalizedRecord], period_label: str) -> dict:
    totals = {t: 0 for t in TOKEN_TYPES}
    total_cost = 0.0

    for record in records:
        for t in TOKEN_TYPES:
            totals[t] += getattr(record.tokens, t)
        total_cost += record.cost_usd

    grand_total_tokens = sum(totals.values())
    non_zero_totals = {t: v for t, v in totals.items() if v != 0}
    slices = _slices_from_totals(non_zero_totals, grand_total_tokens)
    table = [
        _table_row(t, TokenCounts(**{t: totals[t]}), 0.0)
        for t in non_zero_totals
    ]
    table.sort(key=lambda r: r["total"], reverse=True)

    return {
        "dimension": "token_type",
        "period_label": period_label,
        "slices": slices,
        "table": table,
        "grand_total_tokens": grand_total_tokens,
        "grand_total_cost": total_cost,
    }


def _build_breakdown_session(records: list[NormalizedRecord], period_label: str) -> dict:
    token_totals: dict[str, int] = {}
    cost_totals: dict[str, float] = {}
    tokens_by_key: dict[str, TokenCounts] = {}

    for record in records:
        key = record.group_key
        token_totals[key] = token_totals.get(key, 0) + record.tokens.total
        cost_totals[key] = cost_totals.get(key, 0.0) + record.cost_usd
        prev = tokens_by_key.get(key)
        if prev is None:
            tokens_by_key[key] = record.tokens
        else:
            tokens_by_key[key] = TokenCounts(
                input=prev.input + record.tokens.input,
                output=prev.output + record.tokens.output,
                cache_creation=prev.cache_creation + record.tokens.cache_creation,
                cache_read=prev.cache_read + record.tokens.cache_read,
                reasoning=prev.reasoning + record.tokens.reasoning,
            )

    grand_total_tokens = sum(token_totals.values())
    grand_total_cost = sum(cost_totals.values())
    slices = _slices_from_totals(token_totals, grand_total_tokens)
    table = [
        _table_row(key, tokens_by_key[key], cost_totals[key])
        for key in token_totals
    ]
    table.sort(key=lambda r: r["total"], reverse=True)

    return {
        "dimension": "session",
        "period_label": period_label,
        "slices": slices,
        "table": table,
        "grand_total_tokens": grand_total_tokens,
        "grand_total_cost": grand_total_cost,
    }


def build_breakdown(records: list[NormalizedRecord], dimension: str) -> dict:
    """Build the breakdown view-model (pie slices + raw-numbers table) for
    the given dimension ("model" | "token_type" | "session").

    period_label is a placeholder string here; the real label is supplied
    by the caller in T-106. Empty-safe: never divides by zero.
    """
    period_label = "placeholder"

    if not records:
        return _empty_breakdown_vm(dimension, period_label)

    if dimension == "model":
        return _build_breakdown_model(records, period_label)
    if dimension == "token_type":
        return _build_breakdown_token_type(records, period_label)
    if dimension == "session":
        return _build_breakdown_session(records, period_label)

    raise ValueError(f"unknown dimension: {dimension!r}")


def build_comparison(
    claude_records: list[NormalizedRecord], codex_records: list[NormalizedRecord]
) -> dict:
    """Build the comparison view-model (Claude vs Codex tokens per model)."""
    claude_totals: dict[str, int] = {}
    codex_totals: dict[str, int] = {}

    for record in claude_records:
        for mu in record.models:
            claude_totals[mu.model_name] = claude_totals.get(mu.model_name, 0) + mu.tokens.total

    for record in codex_records:
        for mu in record.models:
            codex_totals[mu.model_name] = codex_totals.get(mu.model_name, 0) + mu.tokens.total

    models = sorted(set(claude_totals) | set(codex_totals))

    return {
        "period_label": "placeholder",
        "models": models,
        "series": {
            "claude": [claude_totals.get(m, 0) for m in models],
            "codex": [codex_totals.get(m, 0) for m in models],
        },
        "totals": {
            "claude": sum(claude_totals.values()),
            "codex": sum(codex_totals.values()),
        },
    }
