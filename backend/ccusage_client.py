"""The sole subprocess boundary in this codebase (invariant I1).

No other module may import subprocess. This module checks for a working
Node.js/npx installation and shells out to `npx ccusage@latest ...`
(invariant I2: no other host/URL is ever contacted), mapping failures onto
the typed errors in backend.errors.
"""
from __future__ import annotations

import json
import subprocess

from backend.errors import (
    CcusageFailedError,
    CcusageParseError,
    CcusageTimeoutError,
    NodeMissingError,
    NodeStatus,
)


def _version_ok(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "--version"],
            shell=False,
            timeout=10.0,
            encoding="utf-8",
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def check_node_available() -> NodeStatus:
    """Return NodeStatus.OK only if both `node --version` and
    `npx --version` succeed; MISSING otherwise."""
    if _version_ok("node") and _version_ok("npx"):
        return NodeStatus.OK
    return NodeStatus.MISSING


def run_ccusage(
    agent: str,
    subcommand: str,
    since: str | None = None,
    until: str | None = None,
    timezone: str | None = None,
    timeout_s: float = 60.0,
) -> dict:
    """Run `npx ccusage@latest <agent> <subcommand> --json [--since ..]
    [--until ..] [-z ..]` and return the parsed JSON dict as-is.

    agent in {claude, codex}; subcommand in {daily, session}.
    Raises NodeMissingError / CcusageTimeoutError / CcusageFailedError /
    CcusageParseError on failure (see backend.errors).
    """
    args = ["npx", "ccusage@latest", agent, subcommand, "--json"]
    if since is not None:
        args += ["--since", since]
    if until is not None:
        args += ["--until", until]
    if timezone is not None:
        args += ["-z", timezone]

    try:
        result = subprocess.run(
            args,
            shell=False,
            timeout=timeout_s,
            encoding="utf-8",
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise NodeMissingError(
            "node/npx not found while running ccusage"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CcusageTimeoutError(
            f"ccusage timed out after {timeout_s}s: {' '.join(args)}"
        ) from exc

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-2000:]
        raise CcusageFailedError(
            f"ccusage exited with code {result.returncode}: {stderr_tail}"
        )

    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CcusageParseError(
            f"ccusage stdout was not valid JSON: {exc}"
        ) from exc
