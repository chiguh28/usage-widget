"""Entrypoint: `python -m app.main` (design doc section 5.7, task T-108).

Wires together:
  - app.config.load_config()      -- persisted user config
  - app.api.Api                   -- the pywebview JS-bridge object
  - a pywebview Window over ui/panel.html, with js_api=api so
    window.pywebview.api is available in JS
  - app.poller.Poller             -- background daemon thread pushing
    window.onUsageRefresh(...) at poll_interval_s, plus a manual
    refresh_now() the Api/tray can call
  - app.tray.TrayIcon             -- pystray icon (開く / 終了)

pywebview's `webview.start()` and pystray's `Icon.run()` are BOTH blocking
calls that want to own a loop. The pattern used here: pystray's icon runs
on its own background thread (`TrayIcon.run` in a `threading.Thread`),
while `webview.start()` runs on the main thread (required on some
platforms, e.g. macOS, where GUI toolkits must be driven from the main
thread). Quitting the tray's "終了" menu item stops the poller and calls
`window.destroy()`, which unblocks `webview.start()` so the process exits.
"""
from __future__ import annotations

import threading
from pathlib import Path

import webview

from app import config as config_module
from app.api import Api
from app.poller import Poller
from app.tray import TrayIcon

_UI_PANEL = Path(__file__).resolve().parent.parent / "ui" / "panel.html"


def _get_current_view(api: Api):
    """What the UI is "currently showing", derived from Api's own idea of
    the last-used breakdown params if tracked; falls back to the
    configured default_period comparison view when nothing has been
    fetched yet.

    Api (T-106) does not currently track the last-viewed dimension/agent,
    only `_last_refresh`. Until the UI (T-107) reports its active tab back
    through the bridge, the poller conservatively refreshes the default
    comparison view for the configured default_period -- this keeps the
    poller safe/functional out of the box without requiring UI changes
    outside this task's scope.
    """
    config = config_module.load_config()
    period = config.get("default_period", "7d")
    return ("comparison", {"period": period})


def main() -> None:
    config = config_module.load_config()
    api = Api()

    window = webview.create_window(
        "Usage Widget",
        url=str(_UI_PANEL),
        js_api=api,
        width=480,
        height=640,
    )

    poller = Poller(
        window=window,
        api=api,
        get_current_view=lambda: _get_current_view(api),
        poll_interval_s=config.get("poll_interval_s", 60),
    )

    def show_window():
        window.show()

    def quit_app():
        poller.stop()
        window.destroy()

    tray = TrayIcon(show_window=show_window, on_quit=quit_app)

    def on_window_shown():
        poller.start()

    window.events.shown += on_window_shown

    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    webview.start()

    # webview.start() has returned (window closed / destroyed) -- make sure
    # the poller and tray are torn down even if quit came from window close
    # rather than the tray's "終了" menu item.
    poller.stop()
    tray.stop()


if __name__ == "__main__":
    main()
