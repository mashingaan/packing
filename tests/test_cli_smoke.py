from __future__ import annotations

import csv
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

from packing_mvp.cli import main
from packing_mvp.utils import Part, SourceSolid


def _solid_parts() -> list[Part]:
    return [
        Part(
            part_id="part_001",
            solid_tag=1,
            dims=(300.0, 200.0, 100.0),
            volume=300.0 * 200.0 * 100.0,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(300.0, 200.0, 100.0),
        ),
        Part(
            part_id="part_002",
            solid_tag=2,
            dims=(200.0, 150.0, 150.0),
            volume=200.0 * 150.0 * 150.0,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(200.0, 150.0, 150.0),
        ),
    ]


def _rigid_group_parts() -> list[Part]:
    return [
        Part(
            part_id="assembly_0",
            solid_tag=None,
            dims=(350.0, 200.0, 100.0),
            volume=350.0 * 200.0 * 100.0,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(350.0, 200.0, 100.0),
            mode="rigid_group",
            source_solids=(
                SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=(300.0, 200.0, 100.0)),
                SourceSolid(tag=2, bbox_min=(320.0, 20.0, 10.0), bbox_max=(350.0, 80.0, 60.0)),
            ),
        )
    ]


def _fake_extract(
    input_path: Path,
    scale: float = 1.0,
    treat_input_as_single_item: bool = False,
    logger=None,
):
    parts = _rigid_group_parts() if treat_input_as_single_item else _solid_parts()
    return parts, {
        "scale": scale,
        "manual_scale": scale,
        "auto_scale_applied": False,
        "auto_scale_factor": 1.0,
    }


def _fake_render(placements, out_dir: Path, container_dims, logger=None):
    out_dir = Path(out_dir)
    (out_dir / "preview_top.png").write_bytes(b"fake-top")
    (out_dir / "preview_side.png").write_bytes(b"fake-side")
    return out_dir / "preview_top.png", out_dir / "preview_side.png"


def _fake_render_gif(placements, out_dir: Path, container_dims, logger=None):
    out_dir = Path(out_dir)
    gif_path = out_dir / "preview.gif"
    gif_path.write_bytes(b"GIF89a-test-preview")
    return gif_path


def _fake_export_arranged_step(
    input_step: Path,
    placements_csv: Path,
    output_step: Path,
    *,
    scale: float = 1.0,
    units_mode: str = "packed",
    packing_mode: str = "solids",
    logger=None,
):
    output_step = Path(output_step)
    output_step.parent.mkdir(parents=True, exist_ok=True)
    output_step.write_text(
        f"{Path(input_step).name}|{Path(placements_csv).name}|{scale}|{units_mode}|{packing_mode}",
        encoding="utf-8",
    )


class CliSmokeTests(unittest.TestCase):
    def test_cli_creates_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ) as export_mock:
                            exit_code = main(
                                [
                                    "--input",
                                    str(input_path),
                                    "--out",
                                    str(out_dir),
                                    "--maxW",
                                    "1000",
                                    "--maxH",
                                    "1000",
                                    "--gap",
                                    "10",
                                    "--seed",
                                    "42",
                                    "--step-units",
                                    "source",
                                ]
                            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "result.json").exists())
            self.assertTrue((out_dir / "placements.csv").exists())
            self.assertTrue((out_dir / "arranged.step").exists())
            self.assertTrue((out_dir / "preview_top.png").exists())
            self.assertTrue((out_dir / "preview_side.png").exists())
            self.assertTrue((out_dir / "preview.gif").exists())
            self.assertTrue((out_dir / "preview.gif").read_bytes().startswith(b"GIF"))
            self.assertTrue((out_dir / "packing.log").exists())
            export_mock.assert_called_once()
            self.assertEqual(export_mock.call_args.args[1], out_dir / "placements.csv")
            self.assertEqual(export_mock.call_args.args[2], out_dir / "arranged.step")
            self.assertEqual(export_mock.call_args.kwargs["scale"], 1.0)
            self.assertEqual(export_mock.call_args.kwargs["units_mode"], "source")
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "solids")

            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["stats"]["packed"], 2)
            self.assertFalse(result["constraints"]["flat_only"])
            self.assertFalse(result["treat_input_as_single_item"])
            self.assertEqual(result["packing_mode"], "solids")

    def test_cli_creates_expected_artifacts_with_flat_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ):
                            exit_code = main(
                                [
                                    "--input",
                                    str(input_path),
                                    "--out",
                                    str(out_dir),
                                    "--maxW",
                                    "1000",
                                    "--maxH",
                                    "1000",
                                    "--gap",
                                    "10",
                                    "--flat-only",
                                ]
                            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "result.json").exists())
            self.assertTrue((out_dir / "placements.csv").exists())
            self.assertTrue((out_dir / "arranged.step").exists())
            self.assertTrue((out_dir / "preview_top.png").exists())
            self.assertTrue((out_dir / "preview_side.png").exists())
            self.assertTrue((out_dir / "preview.gif").exists())
            self.assertTrue((out_dir / "preview.gif").read_bytes().startswith(b"GIF"))

            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["stats"]["packed"], 2)
            self.assertTrue(result["constraints"]["flat_only"])
            self.assertTrue(result["flat_only"])

            log_text = (out_dir / "packing.log").read_text(encoding="utf-8")
            self.assertIn("Flat-only orientation filtering enabled", log_text)

    def test_cli_creates_expected_artifacts_with_single_item_and_flat_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ) as export_mock:
                            exit_code = main(
                                [
                                    "--input",
                                    str(input_path),
                                    "--out",
                                    str(out_dir),
                                    "--maxW",
                                    "1000",
                                    "--maxH",
                                    "1000",
                                    "--gap",
                                    "10",
                                    "--flat-only",
                                    "--treat-input-as-single-item",
                                ]
                            )

            self.assertEqual(exit_code, 0)
            export_mock.assert_called_once()
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "single_root_shape")

            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["stats"]["packed"], 1)
            self.assertTrue(result["constraints"]["treat_input_as_single_item"])
            self.assertTrue(result["treat_input_as_single_item"])
            self.assertTrue(result["flat_only"])
            self.assertEqual(result["packing_mode"], "single_root_shape")

            placements_header = (out_dir / "placements.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(
                placements_header,
                "item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz",
            )

    def test_cli_accepts_copies_and_planar_rotation_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ) as export_mock:
                            exit_code = main(
                                [
                                    "--input",
                                    str(input_path),
                                    "--out",
                                    str(out_dir),
                                    "--maxW",
                                    "500",
                                    "--maxH",
                                    "150",
                                    "--maxL",
                                    "2000",
                                    "--gap",
                                    "10",
                                    "--flat-only",
                                    "--treat-input-as-single-item",
                                    "--copies",
                                    "5",
                                    "--planar-rotation-step-deg",
                                    "5",
                                ]
                            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "single_root_shape")

            result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["copies"], 5)
            self.assertEqual(result["planar_rotation_step_deg"], 5.0)
            self.assertEqual(result["stats"]["packed"], 5)

            with (out_dir / "placements.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 5)
            self.assertEqual(sorted(row["copy_index"] for row in rows), [str(index) for index in range(5)])
            self.assertTrue(all(row["planar_angle_deg"] for row in rows))


if __name__ == "__main__":
    unittest.main()
