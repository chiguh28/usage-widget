"""pystray tray icon (design doc section 5.7, task T-108).

Not unit tested (GUI/OS tray integration) -- covered by the manual smoke
checklist in README (task T-109). Kept intentionally small and free of any
business logic: it only toggles window visibility and triggers a clean
shutdown.

Behavior notes (documented per the task's "pick one, document it"):
- Clicking the tray icon itself, or the "開く" (open) menu item, SHOWS the
  pywebview window if it is hidden. If the window is already visible, this
  is a no-op (it does not close it) -- this avoids surprising the user by
  closing the window on an accidental double-click of the tray icon.
- "終了" (quit) stops the poller thread (if one was supplied) and destroys
  the pywebview window, which unblocks `webview.start()` in app.main and
  lets the process exit cleanly.
"""
from __future__ import annotations

from typing import Any, Callable

from PIL import Image, ImageDraw
import pystray


def _generate_icon_image(size: int = 64) -> Image.Image:
    """A simple generated icon: a solid circle on a transparent background.

    No polished art needed per the task spec -- pystray requires *some*
    image, and Pillow is already a pystray dependency.
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(0, 122, 204, 255),  # a simple blue
    )
    return image


class TrayIcon:
    """Wraps a `pystray.Icon` with an "open" and "quit" menu.

    `show_window` / `on_quit` are injected callables so this class has no
    direct dependency on a real pywebview `Window` -- it just needs
    something to call.
    """

    def __init__(
        self,
        show_window: Callable[[], None],
        on_quit: Callable[[], None],
        name: str = "usage-widget",
        title: str = "Usage Widget",
    ) -> None:
        self._show_window = show_window
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            name,
            icon=_generate_icon_image(),
            title=title,
            menu=pystray.Menu(
                pystray.MenuItem("開く", self._on_open),
                pystray.MenuItem("終了", self._on_exit),
            ),
        )
        # clicking the tray icon itself (default action) also opens the panel
        self._icon.default_action = self._on_open

    def _on_open(self, icon: Any = None, item: Any = None) -> None:
        self._show_window()

    def _on_exit(self, icon: Any = None, item: Any = None) -> None:
        try:
            self._on_quit()
        finally:
            self._icon.stop()

    def run(self) -> None:
        """Blocking call -- run this on its own thread (see app.main)."""
        self._icon.run()

    def run_detached(self) -> None:
        """Non-blocking variant, where supported by the platform backend."""
        self._icon.run_detached()

    def stop(self) -> None:
        self._icon.stop()
