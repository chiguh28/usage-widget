"""Normalized data model for usage-widget (ADR-0012).

A single, sparse, union token model is used as the internal lingua franca
across both agents (Claude Code, Codex). Every record carries all five
canonical token types; fields not applicable to a given agent are 0
(Codex -> cache_creation/cache_read = 0; Claude -> reasoning = 0).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TokenCounts:
    """Union token counts. cache_* are Claude-only (0 for Codex); reasoning
    is Codex-only (0 for Claude)."""

    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    reasoning: int = 0

    @property
    def total(self) -> int:
        """Sum of all five fields. MUST equal ccusage totalTokens per
        record (invariant I3, enforced in backend.normalize tests)."""
        return (
            self.input
            + self.output
            + self.cache_creation
            + self.cache_read
            + self.reasoning
        )


@dataclass(frozen=True)
class ModelUsage:
    agent: str
    model_name: str
    tokens: TokenCounts
    cost_usd: float


@dataclass(frozen=True)
class NormalizedRecord:
    agent: str  # "claude" | "codex"
    group_key: str  # date "YYYY-MM-DD" (daily) or session short-id (session)
    group_kind: str  # "date" | "session"
    tokens: TokenCounts  # record-level totals
    cost_usd: float
    models: tuple[ModelUsage, ...] = field(default_factory=tuple)
    last_activity: str | None = None  # ISO timestamp, session mode only
