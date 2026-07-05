"""Unit tests for app.poller (design doc section 5.7, task T-108).

Only the GUI-free concurrency logic (`RefreshCoordinator`) is unit tested
here -- no pywebview Window, no pystray icon, no real background thread
scheduling loop is exercised (that part needs a manual GUI smoke test,
documented separately, per the T-108 acceptance criteria).
"""
from __future__ import annotations

import threading
import time

import pytest

from app.poller import RefreshCoordinator


# ---------------------------------------------------------------------------
# RefreshCoordinator: only one in-flight call per view key
# ---------------------------------------------------------------------------


class TestRefreshCoordinatorSerializes:
    def test_concurrent_calls_for_same_key_do_not_run_simultaneously(self):
        """Two threads racing to refresh the same view: the expensive
        function must never be observed running twice at once."""
        coordinator = RefreshCoordinator()
        concurrent_count = 0
        max_concurrent = 0
        lock = threading.Lock()

        def expensive():
            nonlocal concurrent_count, max_concurrent
            with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            time.sleep(0.05)
            with lock:
                concurrent_count -= 1
            return "result"

        results = []

        def worker():
            results.append(coordinator.run("view-a", expensive))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert max_concurrent == 1
        # every caller gets a result (blocking behavior, not skip)
        assert len(results) == 5

    def test_second_caller_skips_while_first_in_flight(self):
        """The no-op/skip variant: if implemented as skip-on-busy, the
        second concurrent call for the same key returns immediately
        without invoking the expensive function a second time."""
        coordinator = RefreshCoordinator()
        call_count = 0
        started = threading.Event()
        release = threading.Event()

        def expensive():
            nonlocal call_count
            call_count += 1
            started.set()
            release.wait(timeout=5)
            return "result"

        first_thread = threading.Thread(
            target=lambda: coordinator.run("view-a", expensive)
        )
        first_thread.start()
        assert started.wait(timeout=5)

        # second call while first is still in flight for the SAME key
        second_result = coordinator.run("view-a", lambda: "should-not-run")

        release.set()
        first_thread.join(timeout=5)

        assert call_count == 1
        # skip variant returns None (or a sentinel) rather than executing
        assert second_result is None

    def test_different_keys_do_not_block_each_other(self):
        coordinator = RefreshCoordinator()
        started = threading.Event()
        release = threading.Event()
        other_ran = threading.Event()

        def blocking():
            started.set()
            release.wait(timeout=5)
            return "a"

        def other():
            other_ran.set()
            return "b"

        t = threading.Thread(target=lambda: coordinator.run("view-a", blocking))
        t.start()
        assert started.wait(timeout=5)

        result = coordinator.run("view-b", other)

        assert other_ran.is_set()
        assert result == "b"

        release.set()
        t.join(timeout=5)

    def test_run_returns_function_result_when_not_busy(self):
        coordinator = RefreshCoordinator()

        result = coordinator.run("view-a", lambda: 42)

        assert result == 42

    def test_sequential_calls_for_same_key_both_execute(self):
        coordinator = RefreshCoordinator()
        calls = []

        r1 = coordinator.run("view-a", lambda: calls.append(1) or "first")
        r2 = coordinator.run("view-a", lambda: calls.append(2) or "second")

        assert calls == [1, 2]
        assert r1 == "first"
        assert r2 == "second"


# ---------------------------------------------------------------------------
# Poller: manual refresh trigger + tick delegate to the coordinator
# ---------------------------------------------------------------------------


class TestPollerManualRefresh:
    def test_refresh_now_invokes_view_fetcher_and_pushes_to_window(self):
        from app.poller import Poller

        pushed = []

        class FakeWindow:
            def evaluate_js(self, script):
                pushed.append(script)

        def current_view():
            return ("breakdown", {"period": "7d", "dimension": "model", "agent": "claude"})

        def fetch_breakdown(period, dimension, agent):
            return {"grand_total_tokens": 123}

        api = type(
            "FakeApi",
            (),
            {"get_breakdown": staticmethod(fetch_breakdown)},
        )()

        poller = Poller(
            window=FakeWindow(),
            api=api,
            get_current_view=current_view,
            poll_interval_s=60,
        )

        poller.refresh_now()

        assert len(pushed) == 1
        assert "onUsageRefresh" in pushed[0]
        assert "123" in pushed[0]

    def test_refresh_now_for_comparison_view(self):
        from app.poller import Poller

        pushed = []

        class FakeWindow:
            def evaluate_js(self, script):
                pushed.append(script)

        def current_view():
            return ("comparison", {"period": "7d"})

        api = type(
            "FakeApi",
            (),
            {"get_comparison": staticmethod(lambda period: {"totals": {"claude": 1}})},
        )()

        poller = Poller(
            window=FakeWindow(),
            api=api,
            get_current_view=current_view,
            poll_interval_s=60,
        )

        poller.refresh_now()

        assert len(pushed) == 1
        assert "onUsageRefresh" in pushed[0]

    def test_concurrent_refresh_now_and_tick_serialize_via_coordinator(self):
        """The Poller must route both the manual trigger and the periodic
        tick through the same RefreshCoordinator so they can't both hit
        ccusage at once for the same view."""
        from app.poller import Poller

        call_count = 0
        max_concurrent = 0
        concurrent = 0
        lock = threading.Lock()

        class FakeWindow:
            def evaluate_js(self, script):
                pass

        def slow_get_breakdown(period, dimension, agent):
            nonlocal call_count, max_concurrent, concurrent
            with lock:
                call_count += 1
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            time.sleep(0.05)
            with lock:
                concurrent -= 1
            return {"grand_total_tokens": 1}

        api = type(
            "FakeApi",
            (),
            {"get_breakdown": staticmethod(slow_get_breakdown)},
        )()

        poller = Poller(
            window=FakeWindow(),
            api=api,
            get_current_view=lambda: ("breakdown", {"period": "7d", "dimension": "model", "agent": "claude"}),
            poll_interval_s=60,
        )

        threads = [threading.Thread(target=poller.refresh_now) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert max_concurrent == 1
