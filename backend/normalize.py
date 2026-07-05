"""Pure mappers: raw ccusage JSON (Claude Code / Codex, daily / session) ->
list[NormalizedRecord] (ADR-0012 shape, design doc section 5.3).

Only these two entry points are public. Never touches subprocess/GUI.

Invariants:
- I-immut: never mutates the `raw` dict passed in.
- I3 (token conservation): for every record, TokenCounts.total ==
  raw record's totalTokens.
"""
from __future__ import annotations

from backend.model import ModelUsage, NormalizedRecord, TokenCounts


def _model_usage_from_breakdown(mb: dict, agent: str) -> ModelUsage:
    tokens = TokenCounts(
        input=mb.get("inputTokens", 0),
        output=mb.get("outputTokens", 0),
        cache_creation=mb.get("cacheCreationTokens", 0),
        cache_read=mb.get("cacheReadTokens", 0),
        reasoning=mb.get("reasoningOutputTokens", 0),
    )
    return ModelUsage(
        agent=agent,
        model_name=mb["modelName"],
        tokens=tokens,
        cost_usd=mb.get("cost", 0.0),
    )


def _record_cost_usd(entry: dict) -> float:
    # Claude Code namespaced daily/session entries use totalCost; Codex
    # entries may use costUSD instead (design doc section 3). Missing -> 0.0.
    if "totalCost" in entry:
        return entry["totalCost"]
    return entry.get("costUSD", 0.0)


def _normalize_entry(
    entry: dict, agent: str, group_key: str, group_kind: str, last_activity: str | None
) -> NormalizedRecord:
    tokens = TokenCounts(
        input=entry.get("inputTokens", 0),
        output=entry.get("outputTokens", 0),
        cache_creation=entry.get("cacheCreationTokens", 0),
        cache_read=entry.get("cacheReadTokens", 0),
        reasoning=entry.get("reasoningOutputTokens", 0),
    )
    models = tuple(
        _model_usage_from_breakdown(mb, agent)
        for mb in entry.get("modelBreakdowns", [])
    )
    return NormalizedRecord(
        agent=agent,
        group_key=group_key,
        group_kind=group_kind,
        tokens=tokens,
        cost_usd=_record_cost_usd(entry),
        models=models,
        last_activity=last_activity,
    )


def normalize_daily(raw: dict, agent: str) -> list[NormalizedRecord]:
    """Map a raw `<agent> daily --json` envelope to NormalizedRecord list.

    Does not mutate `raw`. group_key = the `date` field; group_kind = "date".
    """
    return [
        _normalize_entry(day, agent, group_key=day["date"], group_kind="date", last_activity=None)
        for day in raw.get("daily", [])
    ]


def normalize_session(raw: dict, agent: str) -> list[NormalizedRecord]:
    """Map a raw `<agent> session --json` envelope to NormalizedRecord list.

    Does not mutate `raw`. group_key = first 8 chars of the session UUID
    (the `sessionId` field in the real ccusage output); group_kind =
    "session". last_activity is carried through from `lastActivity`.
    """
    return [
        _normalize_entry(
            session,
            agent,
            group_key=session["sessionId"][:8],
            group_kind="session",
            last_activity=session.get("lastActivity"),
        )
        for session in raw.get("sessions", [])
    ]
