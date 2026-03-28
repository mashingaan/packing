from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp import __version__
from packing_mvp.gui import PackingGui


class GuiUpdateTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Tk update UI tests are skipped on GitHub-hosted runners.")
        try:
            app = PackingGui()
            app.update()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def test_gui_shows_update_controls(self) -> None:
        app = self._build_app()
        try:
            self.assertTrue(app.check_updates_button.winfo_ismapped())
            self.assertIn(__version__, app.update_status_var.get())
            self.assertEqual(str(app.check_updates_button.cget("state")), "normal")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
