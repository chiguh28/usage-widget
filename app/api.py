"""pywebview JS-bridge API class (design doc section 5.6).

`Api` orchestrates the backend pipeline (client -> normalize -> aggregate ->
export) and config load/save. It holds NO business logic itself and NEVER
lets a backend exception propagate across the bridge -- pywebview would
otherwise hang/break the UI on an uncaught Python exception, so every public
method catches backend.errors.CcusageError (and subclasses) and returns
{"error": code, "message": str(exc)} instead.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

import pyperclip

from app import config as config_module
from backend import ccusage_client
from backend.aggregate import build_breakdown, build_comparison
from backend.errors import (
    CcusageError,
    CcusageFailedError,
    CcusageParseError,
    CcusageTimeoutError,
    NodeMissingError,
    NodeStatus,
)
from backend.export import to_json, to_markdown
from backend.normalize import normalize_daily, normalize_session

_ERROR_CODES = (
    (NodeMissingError, "node_missing"),
    (CcusageFailedError, "ccusage_failed"),
    (CcusageTimeoutError, "ccusage_timeout"),
    (CcusageParseError, "ccusage_parse"),
)

_DATE_FMT = "%Y%m%d"

_PERIOD_LABELS = {"24h": "24時間", "7d": "7日間", "30d": "30日間"}


def _error_code_for(exc: CcusageError) -> str:
    for exc_type, code in _ERROR_CODES:
        if isinstance(exc, exc_type):
            return code
    return "ccusage_failed"


def _since_until(period: str, today: dt.date) -> tuple[str, str]:
    if period == "24h":
        since = today - dt.timedelta(days=1)
    elif period == "7d":
        since = today - dt.timedelta(days=6)
    elif period == "30d":
        since = today - dt.timedelta(days=29)
    else:
        raise ValueError(f"unknown period: {period!r}")
    return since.strftime(_DATE_FMT), today.strftime(_DATE_FMT)


class Api:
    """The pywebview JS-bridge API object (exposed as window.pywebview.api)."""

    def __init__(self, client=None, clock: Callable[[], dt.date] | None = None):
        # client defaults to the real backend.ccusage_client module (its two
        # public functions are used as a namespace); tests inject a fake
        # object exposing the same check_node_available/run_ccusage surface.
        self._client = client if client is not None else ccusage_client
        self._clock = clock if clock is not None else dt.date.today
        self._last_refresh: str | None = None

    # -- status / config ---------------------------------------------------

    def get_status(self) -> dict:
        status = self._client.check_node_available()
        node = "ok" if status == NodeStatus.OK else "missing"
        message = None if node == "ok" else "Node.js/npx not found"
        config = config_module.load_config()
        return {
            "node": node,
            "message": message,
            "poll_interval_s": config["poll_interval_s"],
            "last_refresh": self._last_refresh,
        }

    def get_config(self) -> dict:
        return config_module.load_config()

    def set_config(self, patch: dict) -> dict:
        return config_module.save_config(patch)

    # -- data fetch helpers --------------------------------------------------

    def _records_for(self, agent: str, dimension: str, since: str, until: str) -> list:
        subcommand = "session" if dimension == "session" else "daily"
        raw = self._client.run_ccusage(agent, subcommand, since=since, until=until)
        if subcommand == "session":
            return normalize_session(raw, agent)
        return normalize_daily(raw, agent)

    # -- breakdown / comparison ---------------------------------------------

    def get_breakdown(self, period: str, dimension: str, agent: str) -> dict:
        try:
            since, until = _since_until(period, self._clock())
            if agent == "all":
                records = self._records_for("claude", dimension, since, until)
                records += self._records_for("codex", dimension, since, until)
            else:
                records = self._records_for(agent, dimension, since, until)

            vm = build_breakdown(records, dimension)
            vm["period_label"] = _PERIOD_LABELS.get(period, period)
            return vm
        except CcusageError as exc:
            return {"error": _error_code_for(exc), "message": str(exc)}

    def get_comparison(self, period: str) -> dict:
        try:
            since, until = _since_until(period, self._clock())
            claude_records = self._records_for("claude", "model", since, until)
            codex_records = self._records_for("codex", "model", since, until)

            vm = build_comparison(claude_records, codex_records)
            vm["period_label"] = _PERIOD_LABELS.get(period, period)
            return vm
        except CcusageError as exc:
            return {"error": _error_code_for(exc), "message": str(exc)}

    # -- copy to clipboard ---------------------------------------------------

    def copy_json(self, period: str, dimension: str, agent: str) -> dict:
        vm = self.get_breakdown(period, dimension, agent)
        if isinstance(vm, dict) and "error" in vm:
            return vm
        pyperclip.copy(to_json(vm))
        return {"ok": True}

    def copy_markdown(self, period: str) -> dict:
        bd_claude = self.get_breakdown(period, "model", "claude")
        if isinstance(bd_claude, dict) and "error" in bd_claude:
            return bd_claude
        bd_codex = self.get_breakdown(period, "model", "codex")
        if isinstance(bd_codex, dict) and "error" in bd_codex:
            return bd_codex

        period_label = _PERIOD_LABELS.get(period, period)
        markdown = to_markdown(bd_claude, bd_codex, period_label)
        pyperclip.copy(markdown)
        return {"ok": True}
