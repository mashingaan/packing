from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.gui import PackingGui


def _scrollregion_height(scrollregion: str) -> int:
    left, top, right, bottom = (int(float(value)) for value in scrollregion.split())
    return bottom - top


class GuiLayoutTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        try:
            app = PackingGui()
            app.update()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def _window_bottom(self, app: PackingGui) -> int:
        return app.winfo_rooty() + app.winfo_height()

    def _widget_bottom(self, widget: tk.Widget) -> int:
        return widget.winfo_rooty() + widget.winfo_height()

    def test_default_layout_keeps_footer_visible(self) -> None:
        app = self._build_app()
        try:
            self.assertTrue(app.action_bar.winfo_ismapped())
            self.assertTrue(app.status_frame.winfo_ismapped())
            self.assertTrue(app.log_container.winfo_ismapped())
            self.assertGreater(app.status_frame.winfo_height(), 100)
            self.assertGreater(app.log_container.winfo_height(), 100)

            window_bottom = self._window_bottom(app)
            self.assertLessEqual(self._widget_bottom(app.action_bar), window_bottom)
            self.assertLessEqual(self._widget_bottom(app.status_frame), window_bottom)
        finally:
            app.destroy()

    def test_small_window_scrolls_form_instead_of_hiding_footer(self) -> None:
        app = self._build_app()
        try:
            app.geometry("920x700")
            app.update()

            self.assertTrue(app.action_bar.winfo_ismapped())
            self.assertTrue(app.status_frame.winfo_ismapped())
            self.assertTrue(app.log_container.winfo_ismapped())

            window_bottom = self._window_bottom(app)
            self.assertLessEqual(self._widget_bottom(app.action_bar), window_bottom)
            self.assertLessEqual(self._widget_bottom(app.status_frame), window_bottom)
            self.assertLess(app.scroll_canvas.yview()[1], 1.0)

            initial_height = _scrollregion_height(str(app.scroll_canvas.cget("scrollregion")))

            app._toggle_advanced()
            app.update()

            expanded_height = _scrollregion_height(str(app.scroll_canvas.cget("scrollregion")))
            self.assertGreater(expanded_height, initial_height)
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
