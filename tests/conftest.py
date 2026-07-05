"""Shared pytest fixtures loading captured ccusage JSON from tests/fixtures/."""
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def claude_daily_raw():
    """Real captured `npx ccusage@latest claude daily --json` output."""
    return _load("claude_daily.json")


@pytest.fixture
def codex_daily_raw():
    """Real captured `npx ccusage@latest codex daily --json` output
    (zero/empty data on this machine)."""
    return _load("codex_daily.json")


@pytest.fixture
def claude_session_raw():
    """Real captured `npx ccusage@latest claude session --json` output."""
    return _load("claude_session.json")


@pytest.fixture
def empty_codex_daily_raw():
    """Minimal valid empty-data JSON matching the codex daily shape."""
    return _load("empty_codex_daily.json")


@pytest.fixture
def malformed_json_path():
    """Path to a deliberately broken JSON file, for parse-error testing."""
    return FIXTURES_DIR / "malformed.json"
