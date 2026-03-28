from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.gui import DEFAULT_GUI_SEED, PackingGui, _format_client_result
from packing_mvp.runner import PackingRunResult


class GuiClientCopyTests(unittest.TestCase):
    def test_client_result_copy_mentions_fill_and_bbox(self) -> None:
        report = _format_client_result(
            {
                "status": "ok",
                "fits": True,
                "used_extents_mm": {"L": 500, "W": 400, "H": 300, "maxX": 480, "maxY": 380, "maxZ": 290},
                "truck": {"length_mm": 13400, "width_mm": 2350, "height_mm": 2400},
                "packed_count": 3,
                "fill_ratio": 0.42,
                "stats": {"n_parts": 3},
            }
        )

        self.assertIn("Все грузовые места размещены внутри кузова.", report)
        self.assertIn("Габариты уложенной сцены (мм): 480 x 380 x 290", report)
        self.assertIn("Заполнение кузова: 42.0%", report)

    def test_client_result_copy_mentions_auto_scale(self) -> None:
        report = _format_client_result(
            {
                "status": "ok",
                "fits": True,
                "used_extents_mm": {"L": 500, "W": 400, "H": 300, "maxX": 480, "maxY": 380, "maxZ": 290},
                "truck": {"length_mm": 13400, "width_mm": 2350, "height_mm": 2400},
                "packed_count": 3,
                "fill_ratio": 0.42,
                "stats": {"n_parts": 3},
                "units": {"auto_scale_applied": True},
            }
        )

        self.assertIn("автоматически приведены к миллиметрам", report)


class GuiBehaviorTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Tk GUI smoke tests are skipped on GitHub-hosted runners.")
        try:
            app = PackingGui()
            app.update_idletasks()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def test_gui_hides_advanced_section_by_default(self) -> None:
        app = self._build_app()
        try:
            self.assertFalse(app._advanced_visible)
            self.assertEqual(app.advanced_toggle_button.cget("text"), "Показать дополнительные параметры")
            app._toggle_advanced()
            self.assertTrue(app._advanced_visible)
            self.assertEqual(app.advanced_toggle_button.cget("text"), "Скрыть дополнительные параметры")
        finally:
            app.destroy()

    def test_gui_request_uses_default_seed_and_quantities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            first = tmp / "first.step"
            second = tmp / "second.step"
            first.write_text("x", encoding="utf-8")
            second.write_text("x", encoding="utf-8")

            app = self._build_app()
            try:
                app._apply_input_paths([first, second])
                app._input_quantity_vars[first.resolve()].set("2")
                app._input_quantity_vars[second.resolve()].set("3")
                request = app._build_request()
            finally:
                app.destroy()

        self.assertEqual(request.seed, DEFAULT_GUI_SEED)
        self.assertEqual(request.input_quantities, (2, 3))
        self.assertEqual(request.catalog_items[0].quantity, 2)
        self.assertEqual(request.catalog_items[1].quantity, 3)

    def test_gui_uses_fit_verdict_for_failure_message(self) -> None:
        app = self._build_app()
        try:
            result = PackingRunResult(
                exit_code=2,
                out_dir=Path("out"),
                result_path=Path("out/result.json"),
                placements_path=Path("out/placements.csv"),
                log_path=Path("out/packing.log"),
                preview_top_path=None,
                preview_side_path=None,
                preview_gif_path=None,
                result_data={
                    "status": "failed",
                    "does_not_fit": True,
                    "error": "Не все грузовые места помещаются в кузов.",
                    "unplaced_items": [{"name": "crate.step", "quantity": 2}],
                    "packed_count": 1,
                    "unpacked_count": 2,
                    "stats": {"n_parts": 3},
                },
            )
            with patch("packing_mvp.gui.messagebox.showinfo") as showinfo:
                with patch("packing_mvp.gui.messagebox.showerror") as showerror:
                    app._handle_result(result)

            showinfo.assert_not_called()
            showerror.assert_called_once()
            self.assertIn("crate.step x2", app.status_var.get())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
