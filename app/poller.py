"""Background poller thread + refresh concurrency coordinator.

Design doc section 5.7 / task T-108.

Two pieces:

- `RefreshCoordinator`: a small, GUI-free class that guarantees only one
  "expensive" call (a ccusage-backed fetch) is ever in flight at a time for
  a given view key. If a second caller shows up for the SAME key while the
  first is still running, it is skipped (no-op, returns ``None``) rather
  than firing a second concurrent subprocess call. Different keys never
  block each other. This is the part that is unit-testable without any
  GUI (see tests/test_poller.py).

- `Poller`: wires the coordinator to "the currently active view" (supplied
  via a `get_current_view` callable so this module has zero knowledge of
  the actual UI state) and to a pywebview `Window`-like object exposing
  `evaluate_js`. It runs its periodic tick on a daemon thread and also
  exposes `refresh_now()` for a manual "refresh" trigger (e.g. the UI's
  refresh button, wired through the Api bridge, or the tray).
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable


class RefreshCoordinator:
    """Ensures only one in-flight call per view key.

    If `run(key, fn)` is called while a previous `run(key, ...)` for the
    SAME key is still executing (on another thread), the second call is
    skipped entirely -- it does not invoke `fn` and returns `None`
    immediately -- rather than blocking or running concurrently. Calls for
    DIFFERENT keys never block each other.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._in_flight: set[Any] = set()

    def run(self, key: Any, fn: Callable[[], Any]) -> Any:
        with self._guard:
            if key in self._in_flight:
                return None
            self._in_flight.add(key)

        try:
            return fn()
        finally:
            with self._guard:
                self._in_flight.discard(key)


class Poller:
    """Ticks every `poll_interval_s` seconds on a daemon thread, refreshing
    whatever view is currently active in the UI.

    `get_current_view` must return a tuple of `(kind, params)` where `kind`
    is `"breakdown"` or `"comparison"` and `params` is a dict of the
    matching `Api` method's keyword arguments, e.g.:

        ("breakdown", {"period": "7d", "dimension": "model", "agent": "claude"})
        ("comparison", {"period": "7d"})

    `api` is the pywebview JS-bridge `Api` instance (or any object exposing
    the matching `get_breakdown` / `get_comparison` methods -- tests inject
    a fake). `window` is the pywebview `Window` instance (or a fake
    exposing `evaluate_js`).
    """

    def __init__(
        self,
        window: Any,
        api: Any,
        get_current_view: Callable[[], tuple[str, dict]],
        poll_interval_s: float = 60,
        coordinator: RefreshCoordinator | None = None,
    ) -> None:
        self._window = window
        self._api = api
        self._get_current_view = get_current_view
        self._poll_interval_s = poll_interval_s
        self._coordinator = coordinator if coordinator is not None else RefreshCoordinator()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # -- fetch + push --------------------------------------------------------

    def _fetch_current(self) -> Any:
        kind, params = self._get_current_view()
        if kind == "comparison":
            return self._api.get_comparison(**params)
        if kind == "breakdown":
            return self._api.get_breakdown(**params)
        raise ValueError(f"unknown view kind: {kind!r}")

    def _push(self, vm: Any) -> None:
        payload = json.dumps(vm, ensure_ascii=False)
        self._window.evaluate_js(f"window.onUsageRefresh({payload})")

    def _refresh_key(self) -> Any:
        kind, params = self._get_current_view()
        return (kind, tuple(sorted(params.items())))

    def refresh_now(self) -> Any:
        """Manual "refresh now" trigger (e.g. wired to the UI's refresh
        button through the Api bridge, or the tray). Shares the same
        RefreshCoordinator as the periodic tick, so a manual refresh and a
        poller tick for the same view never run concurrently."""

        def do_refresh():
            vm = self._fetch_current()
            self._push(vm)
            return vm

        return self._coordinator.run(self._refresh_key(), do_refresh)

    # -- background loop ------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval_s):
            self.refresh_now()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
