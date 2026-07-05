"""Config load/save for usage-widget (design doc section 5.7).

Persists a small JSON file in a per-user config directory:
  - Windows (os.name == "nt"): %APPDATA%/usage-widget/config.json
  - Elsewhere: ~/.config/usage-widget/config.json

No new dependency required -- pure stdlib (os / pathlib / json).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "poll_interval_s": 60,
    "default_period": "7d",
    "timezone": None,
}


def _config_dir() -> Path:
    """Return the per-user config directory for usage-widget.

    Separated into its own function so tests can monkeypatch it to an
    isolated tmp_path instead of touching the real %APPDATA%/~/.config.
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "usage-widget"
    return Path.home() / ".config" / "usage-widget"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def load_config() -> dict:
    """Load the config, creating the dir/file with defaults if missing.

    Defense in depth: a corrupt (non-JSON) config.json falls back to
    DEFAULT_CONFIG rather than raising, so a hand-edited/corrupted file on
    disk can't crash a caller. Actual I/O errors (permissions, missing
    drive, etc.) still raise -- callers across the pywebview bridge (see
    app.api.Api.get_status) are responsible for the final degrade-gracefully
    catch per design section 5.6.
    """
    path = _config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return dict(DEFAULT_CONFIG)

    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(patch: dict) -> dict:
    """Merge `patch` into the existing config, persist it, and return the
    full resulting config."""
    current = load_config()
    current.update(patch)

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")

    return current
