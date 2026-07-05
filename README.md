# usage-widget

## What this is

`usage-widget` is a local-only desktop tray widget that visualizes Claude
Code and Codex CLI token usage. It reads usage data by shelling out to
[`ccusage`](https://www.npmjs.com/package/ccusage) (via `npx ccusage@latest`)
— the only external process it ever talks to. There is no network access
beyond that local `npx` invocation (no telemetry, no remote API calls). The
UI is a small pywebview panel opened from a system tray icon, showing a
"内訳分析" (breakdown) tab with a period/dimension switcher and a pie chart
+ table, and a "比較" (comparison) tab with a bar chart comparing Claude
Code vs Codex usage.

## Prerequisites

- **Python >= 3.10** (per `pyproject.toml`).
- **Node.js and npm**, specifically a working `node` and `npx` on `PATH`.
  `ccusage` itself is not a Python dependency — it's fetched on demand via
  `npx ccusage@latest` each time data is requested.

If Node.js/npx is missing or broken, the app does not crash: at startup
`backend/ccusage_client.check_node_available()` runs `node --version` and
`npx --version`, and if either fails (or isn't found), every API call that
needs ccusage data returns a `node_missing` error. The UI then shows a
banner with the message:

> "Node.js が見つかりません。Node.js をインストールしてください。"
> (Node.js was not found. Please install Node.js.)

No retry button is offered for this banner (unlike the timeout case) —
you need to install/fix Node.js and restart the app.

## Install

Python dependencies are declared in `pyproject.toml` (`pystray`, `pywebview`,
`pyperclip`, `tzlocal`, plus `pytest` under the `dev` extra). Install the
project in editable mode from the repo root:

```bash
pip install -e .
```

For running the test suite too, install the `dev` extra as well:

```bash
pip install -e ".[dev]"
```

Then make sure Node.js/npm is installed and on `PATH` (verify with
`node --version` and `npx --version`); `ccusage` itself needs no separate
install step since `npx ccusage@latest` fetches it automatically the first
time it's invoked.

## Run

```bash
python -m app.main
```

This launches the pystray tray icon plus the pywebview panel (see
`app/main.py`). The panel window is shown once you interact with the tray
icon (see the smoke-test checklist below); a background poller then starts
refreshing the currently active view every `poll_interval_s` seconds
(60s by default, configurable via the persisted config file — see
`app/config.py`, stored at `%APPDATA%/usage-widget/config.json` on Windows
or `~/.config/usage-widget/config.json` elsewhere).

## Running tests

```bash
python -m pytest -q
```

All tests are currently passing (confirmed by re-running this exact command
during this task — see the implementer's report for the live output/count;
this README intentionally does not hardcode a test count, since it will go
stale).

## Manual GUI smoke-test checklist

This checklist has **not** been executed as part of this docs task (writing
README.md is documentation-only, per the task spec) — it is derived from
reading `app/main.py`, `app/tray.py`, and `ui/app.js`/`ui/panel.html`. Use it
to manually verify the built app:

1. **Launch the app**
   - Run `python -m app.main`.
   - Confirm a tray icon appears (a solid blue circle, per
     `app/tray.py:_generate_icon_image`) with tooltip title "Usage Widget".

2. **Open the panel via the tray**
   - Left-click (or use the default action of) the tray icon — this calls
     the "開く" (open) behavior and shows the pywebview window.
   - Alternatively, right-click the tray icon to see the context menu; it
     has exactly two items: **開く** (open) and **終了** (quit).
   - Clicking **開く** while the window is already visible is a no-op (it
     will not hide/close an already-open window).

3. **内訳分析 (breakdown) tab — default tab on load**
   - Confirm the "内訳分析" tab button is active by default.
   - Confirm a doughnut/pie chart renders in the chart area, plus a data
     table below it with columns: 項目 / input / output / cache作成 /
     cache読取 / reasoning / 合計 / コスト(USD).
   - Confirm the "合計トークン数" / "合計コスト" summary line above the
     table updates.
   - **Period switch:** click each of the three period radio buttons
     (24時間 / 7日間 / 30日間) under "期間" and confirm the chart + table +
     grand-total refresh each time.
   - **Dimension switch:** change the "モデル別 / トークン種別別 /
     セッション別" dropdown and confirm the chart/table re-render with the
     new dimension's data.

4. **比較 (comparison) tab**
   - Click the "比較" tab button.
   - Confirm a horizontal bar chart renders with two series, "Claude Code"
     (orange, `#d97757`) and "Codex" (blue, `#4f7cff`).
   - Switch the period radios (24時間 / 7日間 / 30日間) on this tab and
     confirm the bar chart refreshes.

5. **Copy JSON button**
   - On the 内訳分析 tab, click "JSONとしてコピー".
   - Confirm a "コピーしました" confirmation flashes near the copy buttons
     (visible for about 1.8s, per `ui/app.js:flashCopyConfirm`).
   - Paste the clipboard contents somewhere and confirm it is valid JSON
     matching the current breakdown period/dimension/agent selection.

6. **Copy Markdown button**
   - Click "Markdownとしてコピー".
   - Confirm the same "コピーしました" confirmation flashes.
   - Paste the clipboard contents and confirm it is a Markdown-formatted
     summary of the current breakdown period.

7. **Node-missing banner**
   - Simulate this by making `node`/`npx` unavailable to the app's
     subprocess calls before launching, e.g. temporarily rename the Node.js
     install directory or otherwise remove it from `PATH` for the shell you
     launch `python -m app.main` from (on Windows, launch from a shell
     where you've temporarily stripped the Node directory out of `%PATH%`;
     confirm first with `node --version` / `npx --version` failing in that
     shell).
   - Launch the app and open the panel; confirm the banner text reads:
     "Node.js が見つかりません。Node.js をインストールしてください。" and
     that no retry button is shown for this error (per
     `ui/app.js:handleErrorIfAny`, only the `ccusage_timeout` case gets a
     retry button).
   - Restore `PATH` afterwards.
   - As a lighter-weight alternative (no PATH editing), you can open
     `ui/panel.html` directly in a plain browser with `?mock=node_missing`
     in the URL — the page's built-in mock bridge (active only when
     `window.pywebview` is undefined) will simulate the same banner without
     touching your real Node.js install. Other supported `?mock=` values
     for exercising banners without the full app: `timeout`, `failed`,
     `empty`, `ok` (default).
   - Note: this in-browser mock path exercises the UI/JS logic only, not
     the real Python bridge — it's a fast manual check, not a substitute
     for testing the real `node_missing` path end-to-end via step 7 above.

8. **Empty-period-data state**
   - Pick a period/dimension combination with no usage data (e.g. a very
     recent 24時間 window on a machine with no recent Claude Code/Codex
     activity, or use `?mock=empty` per step 7 in a plain browser).
   - Confirm the "この期間のデータはありません。" empty banner is shown
     instead of a chart, and that the chart/table area does not render
     stale or placeholder data.

9. **Quit via tray menu**
   - Right-click the tray icon and click "終了".
   - Confirm the background poller stops and the pywebview window closes,
     and the process exits cleanly (no hung process left running).

## Fixture re-capture commands

If `ccusage`'s output format ever changes, regenerate the fixtures under
`tests/fixtures/` with the real CLI (see `tests/conftest.py` for how each
fixture file is loaded/used):

```bash
npx ccusage@latest claude daily --json > tests/fixtures/claude_daily.json
npx ccusage@latest claude session --json > tests/fixtures/claude_session.json
npx ccusage@latest codex daily --json > tests/fixtures/codex_daily.json
```

`tests/fixtures/empty_codex_daily.json` and `tests/fixtures/malformed.json`
are hand-authored, not captured from `ccusage` (the former is a minimal
valid empty-data shape, the latter deliberately-broken JSON for parse-error
tests) — they do not need to be re-captured, only re-checked for shape if
the real `codex daily --json` schema changes.
