from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.catalog import CatalogItem
from packing_mvp.gui import PackingGui


class GuiStepLoadingTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Tk GUI tests are skipped on GitHub-hosted runners.")
        try:
            app = PackingGui()
            app.update()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def _wait_for_loader(self, app: PackingGui, *, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.update()
            if not app._loading_inputs:
                return
            time.sleep(0.02)
        self.fail("Timed out waiting for STEP loader to finish.")

    def test_async_loading_failure_does_not_add_placeholder_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            broken_path = Path(tmp_dir) / "broken.step"
            broken_path.write_text("broken", encoding="utf-8")

            app = self._build_app()
            try:
                with patch("packing_mvp.gui.extract_catalog_item", side_effect=RuntimeError("gmsh failed")):
                    with patch("packing_mvp.gui.messagebox.showerror") as showerror:
                        app._load_input_paths_async([broken_path])
                        self._wait_for_loader(app)

                self.assertEqual(app._catalog_items, [])
                showerror.assert_called_once()
                error_text = showerror.call_args.args[1]
                self.assertIn("broken.step", error_text)
                self.assertIn("gmsh failed", error_text)
            finally:
                app.destroy()

    def test_sync_loading_keeps_valid_items_and_skips_failed_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_path = Path(tmp_dir) / "good.step"
            bad_path = Path(tmp_dir) / "bad.step"
            good_path.write_text("good", encoding="utf-8")
            bad_path.write_text("bad", encoding="utf-8")

            def fake_extract_catalog_item(
                input_path: Path,
                *,
                item_id: str,
                quantity: int = 1,
                scale: float = 1.0,
                logger: object | None = None,
            ) -> CatalogItem:
                del quantity, scale, logger
                resolved = Path(input_path).resolve()
                if resolved == bad_path.resolve():
                    raise RuntimeError("bad bbox")
                return CatalogItem(
                    item_id=item_id,
                    filename=resolved.name,
                    source_path=str(resolved),
                    detected_dims_mm=(1200.0, 800.0, 700.0),
                    dimensions_mm=(1200.0, 800.0, 700.0),
                    quantity=1,
                )

            app = self._build_app()
            try:
                with patch("packing_mvp.gui.extract_catalog_item", side_effect=fake_extract_catalog_item):
                    with patch("packing_mvp.gui.messagebox.showerror") as showerror:
                        app._apply_input_paths([good_path, bad_path])

                self.assertEqual(len(app._catalog_items), 1)
                self.assertEqual(app._catalog_items[0].filename, "good.step")
                self.assertEqual(app._catalog_items[0].dimensions_mm, (1200.0, 800.0, 700.0))
                showerror.assert_called_once()
                error_text = showerror.call_args.args[1]
                self.assertIn("bad.step", error_text)
                self.assertIn("bad bbox", error_text)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
