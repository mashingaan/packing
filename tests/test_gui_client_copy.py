from __future__ import annotations

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
    def test_client_result_copy_explains_short_length_without_technical_terms(self) -> None:
        report = _format_client_result(
            {
                "status": "ok",
                "input": {
                    "file": r"C:\tmp\demo.step",
                },
                "constraints": {
                    "maxL": 1600,
                    "seed": 42,
                },
                "recommended_dims_mm": {
                    "L": 120,
                    "W": 2400,
                    "H": 1800,
                },
                "used_extents_mm": {
                    "maxX": 110,
                    "maxY": 2200,
                    "maxZ": 1700,
                },
                "stats": {
                    "n_parts": 12,
                    "packed": 12,
                    "unpacked": 0,
                    "fill_ratio_bbox": 0.75,
                },
                "units": {
                    "scale": 1.0,
                    "manual_scale": 1.0,
                    "auto_scale_applied": False,
                    "auto_scale_factor": 1.0,
                },
            }
        )

        self.assertTrue(report.startswith("Все детали помещаются\nРекомендуемые размеры ящика: 120 x 2400 x 1800 мм"))
        self.assertIn("Короткая длина возможна: 120 мм — это только длина, а не весь размер ящика", report)
        self.assertIn("Габариты уложенных деталей: 110 x 2200 x 1700 мм", report)
        self.assertIn("Детали могут быть повернуты на 90° и разложены по ширине/высоте", report)
        self.assertIn("Деталей: 12", report)
        self.assertIn("Использовано: 8% длины", report)
        self.assertIn("Заполнение по габаритам деталей: 75.0%", report)
        self.assertNotIn("Рекомендуемая длина", report)
        self.assertNotIn("bbox", report.lower())
        self.assertNotIn("seed", report.lower())
        self.assertNotIn("scale", report.lower())

    def test_client_result_copy_mentions_auto_scale_without_showing_scale_key(self) -> None:
        report = _format_client_result(
            {
                "status": "ok",
                "input": {},
                "recommended_dims_mm": {
                    "L": 500,
                    "W": 400,
                    "H": 300,
                },
                "used_extents_mm": {
                    "maxX": 480,
                    "maxY": 380,
                    "maxZ": 290,
                },
                "stats": {
                    "n_parts": 3,
                    "packed": 3,
                    "unpacked": 0,
                    "fill_ratio_bbox": 0.42,
                },
                "units": {
                    "scale": 1000.0,
                    "manual_scale": 1.0,
                    "auto_scale_applied": True,
                    "auto_scale_factor": 1000.0,
                },
            }
        )

        self.assertIn("Рекомендуемые размеры ящика: 500 x 400 x 300 мм", report)
        self.assertIn("Короткая длина возможна: 500 мм — это только длина, а не весь размер ящика", report)
        self.assertIn("автоматически приведены к миллиметрам", report)
        self.assertNotIn("scale", report.lower())


class GuiBehaviorTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        try:
            app = PackingGui()
            app.update_idletasks()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def test_gui_hides_seed_control_and_collapses_advanced_section_by_default(self) -> None:
        app = self._build_app()
        try:
            self.assertFalse(hasattr(app, "seed_var"))
            self.assertFalse(app._advanced_visible)
            self.assertEqual(
                app.advanced_toggle_button.cget("text"),
                "Показать дополнительные параметры",
            )

            app._toggle_advanced()
            self.assertTrue(app._advanced_visible)
            self.assertEqual(
                app.advanced_toggle_button.cget("text"),
                "Скрыть дополнительные параметры",
            )
        finally:
            app.destroy()

    def test_gui_request_uses_default_seed_without_input_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "demo.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            app = self._build_app()
            try:
                app.input_var.set(str(input_path))
                app.output_var.set(str(out_dir))
                app.max_w_var.set("1200")
                app.max_h_var.set("800")
                app.max_l_var.set("")
                app.gap_var.set("10")
                app.scale_var.set("1.0")

                request = app._build_request()
            finally:
                app.destroy()

        self.assertEqual(request.seed, DEFAULT_GUI_SEED)
        self.assertEqual(request.scale, 1.0)

    def test_gui_tracks_multiple_selected_input_files_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_input = tmp_path / "first.step"
            second_input = tmp_path / "second.step"
            first_input.write_text("first", encoding="utf-8")
            second_input.write_text("second", encoding="utf-8")

            app = self._build_app()
            try:
                app._apply_input_paths([first_input, second_input])
                request = app._build_request()
                input_count = app.input_count_var.get()
                input_value = app.input_var.get()
            finally:
                app.destroy()

        self.assertEqual(request.input_path, first_input)
        self.assertEqual(request.input_paths, (first_input, second_input))
        self.assertEqual(input_count, "2")
        self.assertIn(str(first_input), input_value)
        self.assertIn(str(second_input), input_value)

    def test_gui_expands_file_quantities_into_request_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_input = tmp_path / "first.step"
            second_input = tmp_path / "second.step"
            first_input.write_text("first", encoding="utf-8")
            second_input.write_text("second", encoding="utf-8")

            app = self._build_app()
            try:
                app._apply_input_paths([first_input, second_input])
                app._input_quantity_vars[first_input].set("2")
                app._input_quantity_vars[second_input].set("3")
                request = app._build_request()
                input_count = app.input_count_var.get()
                summary = app.input_summary_var.get()
            finally:
                app.destroy()

        self.assertEqual(
            request.input_paths,
            (first_input, first_input, second_input, second_input, second_input),
        )
        self.assertEqual(input_count, "5")
        self.assertIn("Всего деталей: 5", summary)


    def test_gui_uses_fit_verdict_for_success_message(self) -> None:
        app = self._build_app()
        try:
            result = PackingRunResult(
                exit_code=0,
                out_dir=Path("out"),
                result_path=Path("out/result.json"),
                placements_path=Path("out/placements.csv"),
                log_path=Path("out/packing.log"),
                preview_top_path=None,
                preview_side_path=None,
                preview_gif_path=None,
                result_data={
                    "status": "ok",
                    "fits": False,
                    "does_not_fit": False,
                    "violations": [
                        {
                            "axis": "L",
                            "max": 10000,
                            "actual": 10284,
                            "excess": 284,
                        }
                    ],
                    "constraints": {"maxL": 10000, "maxW": 2500, "maxH": 1800},
                    "used_extents_mm": {"L": 10284, "W": 2400, "H": 1700, "maxX": 10274, "maxY": 2390, "maxZ": 1690},
                    "stats": {"n_parts": 5},
                },
            )

            with patch("packing_mvp.gui.messagebox.showinfo") as showinfo:
                with patch("packing_mvp.gui.messagebox.showerror") as showerror:
                    app._handle_result(result)

            showinfo.assert_not_called()
            showerror.assert_called_once()
            self.assertGreaterEqual(len(showerror.call_args.args), 2)
            self.assertIn("10284 / 10000", showerror.call_args.args[1])
            self.assertNotIn("Р’СЃРµ РґРµС‚Р°Р»Рё РїРѕРјРµС‰Р°СЋС‚СЃСЏ", app.status_var.get())
            self.assertIn("10284 / 10000", app.status_var.get())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
