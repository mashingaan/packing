from __future__ import annotations

from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.catalog import CatalogItem
from packing_mvp.cli import main


def _catalog_item(path: Path, *, quantity: int = 1) -> CatalogItem:
    return CatalogItem(
        item_id=f"item_{path.stem}",
        filename=path.name,
        source_path=str(path),
        detected_dims_mm=(1000.0, 800.0, 600.0),
        dimensions_mm=(1000.0, 800.0, 600.0),
        quantity=quantity,
    )


def _fake_render(placements, out_dir: Path, container_dims, logger=None):
    out_dir = Path(out_dir)
    (out_dir / "preview_top.png").write_bytes(b"top")
    (out_dir / "preview_side.png").write_bytes(b"side")
    return out_dir / "preview_top.png", out_dir / "preview_side.png"


def _fake_render_gif(placements, out_dir: Path, container_dims, logger=None):
    out_dir = Path(out_dir)
    gif_path = out_dir / "preview.gif"
    gif_path.write_bytes(b"GIF89a-preview")
    return gif_path


def _fake_export_scene(placements, output_step: Path, logger=None):
    output_step.write_text("packed-step", encoding="utf-8")
    return "source_models"


class CliSmokeTests(unittest.TestCase):
    def test_cli_handles_non_utf_console_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            input_path = tmp / "dummy.step"
            out_dir = tmp / "out"
            input_path.write_text("dummy", encoding="utf-8")
            stdout_buffer = BytesIO()
            stderr_buffer = BytesIO()
            stdout_stream = TextIOWrapper(stdout_buffer, encoding="cp1252")
            stderr_stream = TextIOWrapper(stderr_buffer, encoding="cp1252")

            def fake_extract(input_path: Path, *, item_id: str, quantity: int = 1, scale: float = 1.0, logger=None):
                return _catalog_item(input_path, quantity=quantity)

            with patch.object(sys, "stdout", stdout_stream):
                with patch.object(sys, "stderr", stderr_stream):
                    with patch("packing_mvp.runner.extract_catalog_item", side_effect=fake_extract):
                        with patch("packing_mvp.runner.export_packed_scene", side_effect=_fake_export_scene):
                            with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                                with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                                    exit_code = main(["--input", str(input_path), "--out", str(out_dir)])

            stdout_stream.flush()
            stderr_stream.flush()

        self.assertEqual(exit_code, 0)
        self.assertIn(str(out_dir).encode("ascii"), stdout_buffer.getvalue())

    def test_cli_creates_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            first = tmp / "first.step"
            second = tmp / "second.step"
            out_dir = tmp / "out"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            def fake_extract(input_path: Path, *, item_id: str, quantity: int = 1, scale: float = 1.0, logger=None):
                return _catalog_item(input_path, quantity=quantity)

            with patch("packing_mvp.runner.extract_catalog_item", side_effect=fake_extract):
                with patch("packing_mvp.runner.export_packed_scene", side_effect=_fake_export_scene):
                    with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                        with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                            exit_code = main(
                                [
                                    "--input",
                                    str(first),
                                    str(second),
                                    "--quantity",
                                    "2",
                                    "1",
                                    "--out",
                                    str(out_dir),
                                ]
                            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "result.json").exists())
            self.assertTrue((out_dir / "placements.csv").exists())
            self.assertTrue((out_dir / "arranged.step").exists())
            self.assertTrue((out_dir / "preview.gif").exists())
            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["success"])
            self.assertEqual(result["packed_count"], 3)
            self.assertEqual([item["quantity"] for item in result["catalog"]], [2, 1])


if __name__ == "__main__":
    unittest.main()
