from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.gui import PackingGui


class GuiLayoutTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Tk layout tests are skipped on GitHub-hosted runners.")
        try:
            app = PackingGui()
            app.update()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def test_default_layout_keeps_footer_visible(self) -> None:
        app = self._build_app()
        try:
            self.assertTrue(app.action_bar.winfo_ismapped())
            self.assertTrue(app.status_frame.winfo_ismapped())
            self.assertTrue(app.log_container.winfo_ismapped())
        finally:
            app.destroy()

    def test_small_window_still_has_scrollable_form(self) -> None:
        app = self._build_app()
        try:
            app.geometry("980x720")
            app.update()
            initial = str(app.scroll_canvas.cget("scrollregion"))
            app._toggle_advanced()
            app.update()
            expanded = str(app.scroll_canvas.cget("scrollregion"))
            self.assertNotEqual(initial, expanded)
        finally:
            app.destroy()

    def test_mousewheel_scrolls_top_area(self) -> None:
        app = self._build_app()
        try:
            app.scroll_canvas.configure(scrollregion=(0, 0, 1200, 3200))
            app.scroll_canvas.yview_moveto(0.0)
            app.update()
            start = app.scroll_canvas.yview()
            event = SimpleNamespace(
                x_root=app.run_button.winfo_rootx() + 5,
                y_root=app.run_button.winfo_rooty() + 5,
                delta=-120,
                widget=app.run_button,
            )
            result = app._handle_global_mousewheel(event)
            app.update()
            self.assertEqual(result, "break")
            self.assertNotEqual(start, app.scroll_canvas.yview())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
