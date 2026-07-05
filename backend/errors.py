"""Typed errors and status enums for the backend.ccusage_client subprocess
boundary (see design doc section 5.2 and 6)."""
from __future__ import annotations

from enum import Enum


class CcusageError(Exception):
    """Base exception for all ccusage-related failures."""


class NodeMissingError(CcusageError):
    """Raised when node/npx is not available on this machine."""


class CcusageFailedError(CcusageError):
    """Raised when the ccusage subprocess exits with a nonzero status."""


class CcusageTimeoutError(CcusageError):
    """Raised when the ccusage subprocess exceeds the configured timeout."""


class CcusageParseError(CcusageError):
    """Raised when ccusage stdout is not valid/parseable JSON."""


class NodeStatus(Enum):
    OK = "ok"
    MISSING = "missing"
