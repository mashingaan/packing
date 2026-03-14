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

from packing_mvp.runner import (
    PackingRequest,
    PackingRunResult,
    make_default_output_dir,
    run_packing_job,
    run_packing_job_in_subprocess,
)
from packing_mvp.packer import PackOutcome
from packing_mvp.presentation import format_result_summary
from packing_mvp.utils import Part, Placement, SourceSolid


def _solid_parts() -> list[Part]:
    return [
        Part("part_001", 1, (300.0, 200.0, 100.0), 300.0 * 200.0 * 100.0, (0.0, 0.0, 0.0), (300.0, 200.0, 100.0)),
        Part("part_002", 2, (200.0, 150.0, 150.0), 200.0 * 150.0 * 150.0, (0.0, 0.0, 0.0), (200.0, 150.0, 150.0)),
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
            orientation_policy="assembly_axes_parallel_to_box_axes",
            source_solids=(
                SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=(300.0, 200.0, 100.0)),
                SourceSolid(tag=2, bbox_min=(320.0, 20.0, 10.0), bbox_max=(350.0, 80.0, 60.0)),
            ),
        )
    ]


def _multi_file_parts() -> list[Part]:
    return [
        Part(
            part_id="file_001",
            solid_tag=None,
            dims=(300.0, 200.0, 100.0),
            volume=300.0 * 200.0 * 100.0,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(300.0, 200.0, 100.0),
            mode="rigid_group",
            source_solids=(
                SourceSolid(tag=11, bbox_min=(0.0, 0.0, 0.0), bbox_max=(300.0, 200.0, 100.0)),
            ),
        ),
        Part(
            part_id="file_002",
            solid_tag=None,
            dims=(250.0, 150.0, 120.0),
            volume=250.0 * 150.0 * 120.0,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(250.0, 150.0, 120.0),
            mode="rigid_group",
            source_solids=(
                SourceSolid(tag=22, bbox_min=(0.0, 0.0, 0.0), bbox_max=(250.0, 150.0, 120.0)),
            ),
        ),
    ]


def _fake_extract(
    input_path: Path,
    scale: float = 1.0,
    treat_input_as_single_item: bool = False,
    logger=None,
):
    return (
        _rigid_group_parts() if treat_input_as_single_item else _solid_parts(),
        {
            "scale": scale,
            "manual_scale": scale,
            "auto_scale_applied": False,
            "auto_scale_factor": 1.0,
        },
    )


def _fake_extract_files(input_paths, scale: float = 1.0, logger=None):
    return (
        _multi_file_parts(),
        {
            "scale": scale,
            "manual_scale": scale,
            "auto_scale_applied": False,
            "auto_scale_factor": 1.0,
            "source_units": [
                {
                    "path": str(Path(input_paths[0])),
                    "scale": scale,
                    "manual_scale": scale,
                    "auto_scale_applied": False,
                    "auto_scale_factor": 1.0,
                },
                {
                    "path": str(Path(input_paths[1])),
                    "scale": scale,
                    "manual_scale": scale,
                    "auto_scale_applied": False,
                    "auto_scale_factor": 1.0,
                },
            ],
        },
    )


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
    input_steps=None,
    item_scales=None,
    logger=None,
):
    output_step = Path(output_step)
    output_step.parent.mkdir(parents=True, exist_ok=True)
    output_step.write_text(
        f"{Path(input_step).name}|{Path(placements_csv).name}|{scale}|{units_mode}|{packing_mode}",
        encoding="utf-8",
    )


def _fake_merge_step_files(input_paths, output_path: Path, *, logger=None):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "|".join(Path(path).name for path in input_paths),
        encoding="utf-8",
    )
    return output_path


def _fake_pack_outcome_with_length_overrun(
    parts,
    max_w: float,
    max_h: float,
    gap: float,
    max_l: float | None = None,
    seed: int = 42,
    flat_only: bool = False,
    planar_rotation_step_deg: float = 0.0,
    logger=None,
):
    placements = [
        Placement(
            part=part,
            x=float(index * 400),
            y=0.0,
            z=0.0,
            dims=part.dims,
            rot="xyz",
            planar_angle_deg=0.0,
        )
        for index, part in enumerate(parts)
    ]
    return PackOutcome(
        placements=placements,
        used_extents=(10274.0, 2137.0, 938.0),
        recommended_dims=(10284, 2147, 948),
        container_dims=(10000, 2500, 1000),
        search_length=10000,
        fill_ratio_bbox=0.964,
    )


class _FakeQueue:
    def __init__(self) -> None:
        self.items: list[tuple[str, object]] = []

    def put(self, item: tuple[str, object]) -> None:
        self.items.append(item)


class RunnerSmokeTests(unittest.TestCase):
    def test_make_default_output_dir_is_timestamped(self) -> None:
        base = Path(r"C:\tmp\example.step")
        generated = make_default_output_dir(base)
        self.assertEqual(generated.parent, base.parent)
        self.assertTrue(generated.name.startswith("PackingResult_"))

    def test_run_packing_job_creates_artifacts(self) -> None:
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
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=1000.0,
                                    max_h=1000.0,
                                    gap=10.0,
                                    seed=42,
                                ),
                                with_console=False,
                            )

            self.assertEqual(result.exit_code, 0)
            self.assertTrue(result.result_path.exists())
            self.assertTrue(result.placements_path.exists())
            self.assertTrue(result.log_path.exists())
            self.assertTrue((out_dir / "arranged.step").exists())
            self.assertTrue((out_dir / "preview_top.png").exists())
            self.assertTrue((out_dir / "preview_side.png").exists())
            self.assertTrue((out_dir / "preview.gif").exists())
            self.assertTrue((out_dir / "preview.gif").read_bytes().startswith(b"GIF"))
            self.assertEqual(result.preview_gif_path, out_dir / "preview.gif")
            export_mock.assert_called_once()
            self.assertEqual(export_mock.call_args.args[1], out_dir / "placements.csv")
            self.assertEqual(export_mock.call_args.args[2], out_dir / "arranged.step")
            self.assertEqual(export_mock.call_args.kwargs["scale"], 1.0)
            self.assertEqual(export_mock.call_args.kwargs["units_mode"], "packed")
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "solids")

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_json["status"], "ok")
            self.assertFalse(result_json["constraints"]["flat_only"])
            self.assertFalse(result_json["treat_input_as_single_item"])
            self.assertEqual(result_json["packing_mode"], "solids")
            self.assertEqual(result_json["input"]["count"], 1)
            self.assertEqual(result_json["input"]["files"], [str(input_path)])

    def test_run_packing_job_accepts_preloaded_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")
            messages: list[str] = []

            with patch("packing_mvp.runner.extract_parts_from_step") as extract_mock:
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ):
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=1000.0,
                                    max_h=1000.0,
                                    gap=10.0,
                                    seed=42,
                                ),
                                with_console=False,
                                status_callback=messages.append,
                                preloaded_parts=_fake_extract(input_path)[0],
                                preloaded_units=_fake_extract(input_path)[1],
                            )

            extract_mock.assert_not_called()
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(result.result_path.exists())
            self.assertTrue(result.placements_path.exists())
            self.assertEqual(len(messages), 5)
            self.assertEqual(messages[2], "Exporting arranged STEP...")
            self.assertTrue(messages[0])
            self.assertTrue(messages[1])
            self.assertTrue(messages[3])
            self.assertTrue(messages[4])

    def test_run_packing_job_keeps_success_when_gif_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                    with patch("packing_mvp.runner.render_preview_gif", side_effect=RuntimeError("gif failed")):
                        with patch(
                            "packing_mvp.runner.export_arranged_step",
                            side_effect=_fake_export_arranged_step,
                        ):
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=1000.0,
                                    max_h=1000.0,
                                    gap=10.0,
                                    seed=42,
                                ),
                                with_console=False,
                            )

            self.assertEqual(result.exit_code, 0)
            self.assertIsNone(result.preview_gif_path)
            self.assertFalse((out_dir / "preview.gif").exists())

            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("WARNING", log_text)
            self.assertIn("Failed to build preview.gif", log_text)

    def test_run_packing_job_fails_when_arranged_step_export_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.export_arranged_step", side_effect=RuntimeError("step export failed")):
                    result = run_packing_job(
                        PackingRequest(
                            input_path=input_path,
                            out_dir=out_dir,
                            max_w=1000.0,
                            max_h=1000.0,
                            gap=10.0,
                            seed=42,
                        ),
                        with_console=False,
                    )

            self.assertEqual(result.exit_code, 2)
            self.assertFalse((out_dir / "arranged.step").exists())
            self.assertEqual(result.result_data["status"], "failed")
            self.assertIn("step export failed", result.result_data["error"])
            self.assertFalse(result.result_data["does_not_fit"])

    def test_run_packing_job_treats_each_input_file_as_one_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_input = tmp_path / "first.step"
            second_input = tmp_path / "second.step"
            out_dir = tmp_path / "out"
            first_input.write_text("first", encoding="utf-8")
            second_input.write_text("second", encoding="utf-8")

            with patch("packing_mvp.runner.merge_step_files") as merge_mock:
                with patch(
                    "packing_mvp.runner.extract_parts_from_step_files",
                    side_effect=_fake_extract_files,
                ) as extract_files_mock:
                    with patch("packing_mvp.runner.render_previews", side_effect=_fake_render):
                        with patch("packing_mvp.runner.render_preview_gif", side_effect=_fake_render_gif):
                            with patch(
                                "packing_mvp.runner.export_arranged_step",
                                side_effect=_fake_export_arranged_step,
                            ) as export_mock:
                                result = run_packing_job(
                                    PackingRequest(
                                        input_path=first_input,
                                        input_paths=(first_input, second_input),
                                        out_dir=out_dir,
                                        max_w=1000.0,
                                        max_h=1000.0,
                                        gap=10.0,
                                        seed=42,
                                    ),
                                    with_console=False,
                                )

            self.assertEqual(result.exit_code, 0)
            merge_mock.assert_not_called()
            extract_files_mock.assert_called_once()
            self.assertEqual(
                extract_files_mock.call_args.kwargs["input_paths"],
                (first_input, second_input),
            )
            self.assertEqual(export_mock.call_args.args[0], first_input)
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "multi_root_shapes")
            self.assertEqual(export_mock.call_args.kwargs["input_steps"], (first_input, second_input))
            self.assertEqual(export_mock.call_args.kwargs["item_scales"], (1.0, 1.0))

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_json["input"]["count"], 2)
            self.assertEqual(result_json["input"]["files"], [str(first_input), str(second_input)])
            self.assertEqual(result_json["stats"]["packed"], 2)
            self.assertEqual(result_json["stats"]["n_parts"], 2)
            self.assertEqual(result_json["packing_mode"], "multi_root_shapes")
            self.assertIn("Деталей: 2", format_result_summary(result_json))

    def test_run_packing_job_uses_single_root_shape_export_when_requested(self) -> None:
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
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=1000.0,
                                    max_h=1000.0,
                                    gap=10.0,
                                    seed=42,
                                    flat_only=True,
                                    treat_input_as_single_item=True,
                                ),
                                with_console=False,
                            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "single_root_shape")
            self.assertTrue((out_dir / "arranged.step").exists())

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_json["status"], "ok")
            self.assertEqual(result_json["stats"]["packed"], 1)
            self.assertTrue(result_json["constraints"]["flat_only"])
            self.assertTrue(result_json["constraints"]["treat_input_as_single_item"])
            self.assertEqual(result_json["constraints"]["orientation_policy"], "assembly_axes_parallel_to_box_axes")
            self.assertTrue(result_json["constraints"]["longest_to_length"])
            self.assertTrue(result_json["constraints"]["shortest_to_height"])
            self.assertTrue(result_json["treat_input_as_single_item"])
            self.assertEqual(result_json["packing_mode"], "single_root_shape")
            self.assertEqual(result_json["orientation_policy"], "assembly_axes_parallel_to_box_axes")
            self.assertTrue(result_json["longest_to_length"])
            self.assertTrue(result_json["shortest_to_height"])

            placements_header = result.placements_path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(
                placements_header,
                "item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz",
            )
            placement_lines = result.placements_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(placement_lines), 2)
            self.assertTrue(placement_lines[1].startswith("assembly_0,rigid_group,0,"))

    def test_run_packing_job_writes_one_rigid_row_per_copy(self) -> None:
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
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=500.0,
                                    max_h=150.0,
                                    max_l=2000.0,
                                    gap=10.0,
                                    seed=42,
                                    flat_only=True,
                                    treat_input_as_single_item=True,
                                    copies=5,
                                    planar_rotation_step_deg=5.0,
                                ),
                                with_console=False,
                            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(export_mock.call_args.kwargs["packing_mode"], "single_root_shape")

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_json["status"], "ok")
            self.assertEqual(result_json["stats"]["packed"], 5)
            self.assertEqual(result_json["stats"]["n_parts"], 5)
            self.assertEqual(result_json["copies"], 5)
            self.assertFalse(result_json["does_not_fit"])
            self.assertEqual(result_json["packed_count"], 5)
            self.assertEqual(result_json["unpacked_count"], 0)
            self.assertEqual(result_json["planar_rotation_step_deg"], 0.0)
            self.assertEqual(result_json["constraints"]["copies"], 5)
            self.assertEqual(result_json["constraints"]["planar_rotation_step_deg"], 0.0)
            self.assertEqual(result_json["orientation_policy"], "assembly_axes_parallel_to_box_axes")
            self.assertTrue(result_json["longest_to_length"])
            self.assertTrue(result_json["shortest_to_height"])

            placement_lines = result.placements_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(placement_lines), 6)
            self.assertEqual(
                placement_lines[0],
                "item_id,mode,copy_index,source_count,source_tags,dx,dy,dz,x,y,z,rot,planar_angle_deg,bbox_minx,bbox_miny,bbox_minz,bbox_maxx,bbox_maxy,bbox_maxz",
            )
            with result.placements_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(
                sorted(row["item_id"] for row in rows),
                [f"assembly_0_copy_{index:03d}" for index in range(5)],
            )
            self.assertEqual(
                sorted(row["copy_index"] for row in rows),
                [str(index) for index in range(5)],
            )
            self.assertTrue(all(row["planar_angle_deg"] for row in rows))
            self.assertTrue(all(row["planar_angle_deg"] == "0.000" for row in rows))

            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("planar rotation disabled for rigid assembly axis-aligned mode", log_text)

    def test_run_packing_job_fails_when_final_length_exceeds_max_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                with patch("packing_mvp.runner.pack_parts", side_effect=_fake_pack_outcome_with_length_overrun):
                    with patch("packing_mvp.runner.render_previews") as render_mock:
                        with patch("packing_mvp.runner.render_preview_gif") as gif_mock:
                            with patch("packing_mvp.runner.export_arranged_step") as export_mock:
                                result = run_packing_job(
                                    PackingRequest(
                                        input_path=input_path,
                                        out_dir=out_dir,
                                        max_w=2500.0,
                                        max_h=1000.0,
                                        max_l=10000.0,
                                        gap=10.0,
                                        seed=42,
                                        flat_only=True,
                                        treat_input_as_single_item=True,
                                        copies=5,
                                    ),
                                    with_console=False,
                                )

            self.assertEqual(result.exit_code, 2)
            self.assertFalse(result.placements_path.exists())
            self.assertFalse((out_dir / "arranged.step").exists())
            self.assertFalse((out_dir / "preview_top.png").exists())
            self.assertFalse((out_dir / "preview_side.png").exists())
            self.assertFalse((out_dir / "preview.gif").exists())
            export_mock.assert_not_called()
            render_mock.assert_not_called()
            gif_mock.assert_not_called()

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result_json["status"], "failed")
            self.assertFalse(result_json["fits"])
            self.assertTrue(result_json["does_not_fit"])
            self.assertEqual(
                result_json["violations"],
                [
                    {
                        "axis": "L",
                        "actual": 10284,
                        "max": 10000,
                        "excess": 284,
                    }
                ],
            )
            self.assertEqual(
                result_json["error"],
                "Не помещается: длина 10284 мм превышает допустимые 10000 мм на 284 мм",
            )
            self.assertEqual(result_json["used_extents_mm"]["L"], 10284)
            self.assertEqual(result_json["used_extents_mm"]["W"], 2147)
            self.assertEqual(result_json["used_extents_mm"]["H"], 948)

            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("Final verdict: DOES NOT FIT", log_text)
            self.assertIn("Не помещается: длина 10284 мм превышает допустимые 10000 мм на 284 мм", log_text)

    def test_five_copies_fit_or_fail_cleanly(self) -> None:
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
                            result = run_packing_job(
                                PackingRequest(
                                    input_path=input_path,
                                    out_dir=out_dir,
                                    max_w=500.0,
                                    max_h=150.0,
                                    max_l=10000.0,
                                    gap=10.0,
                                    seed=42,
                                    flat_only=True,
                                    treat_input_as_single_item=True,
                                    copies=5,
                                ),
                                with_console=False,
                            )

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            if result_json["status"] == "ok":
                self.assertEqual(result.exit_code, 0)
                self.assertFalse(result_json["does_not_fit"])
                self.assertEqual(result_json["packed_count"], 5)
                self.assertEqual(result_json["unpacked_count"], 0)
                self.assertTrue((out_dir / "arranged.step").exists())
                self.assertLessEqual(result_json["used_extents_mm"]["maxX"], 9990)
                self.assertLessEqual(result_json["used_extents_mm"]["maxY"], 490)
                self.assertLessEqual(result_json["used_extents_mm"]["maxZ"], 140)
                with result.placements_path.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 5)
                for row in rows:
                    with self.subTest(item_id=row["item_id"]):
                        self.assertLessEqual(float(row["x"]) + float(row["dx"]), 9990.0 + 1e-6)
                        self.assertLessEqual(float(row["y"]) + float(row["dy"]), 490.0 + 1e-6)
                        self.assertLessEqual(float(row["z"]) + float(row["dz"]), 140.0 + 1e-6)
            else:
                self.assertEqual(result.exit_code, 2)
                self.assertTrue(result_json["does_not_fit"])
                self.assertEqual(result_json["packed_count"], 0)
                self.assertEqual(result_json["unpacked_count"], 5)
                self.assertFalse((out_dir / "arranged.step").exists())

    def test_result_reports_does_not_fit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "dummy.step"
            out_dir = tmp_path / "out"
            input_path.write_text("dummy", encoding="utf-8")

            with patch("packing_mvp.runner.extract_parts_from_step", side_effect=_fake_extract):
                result = run_packing_job(
                    PackingRequest(
                        input_path=input_path,
                        out_dir=out_dir,
                        max_w=500.0,
                        max_h=90.0,
                        max_l=10000.0,
                        gap=10.0,
                        seed=42,
                        flat_only=True,
                        treat_input_as_single_item=True,
                        copies=5,
                    ),
                    with_console=False,
                )

            result_json = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(result_json["status"], "failed")
            self.assertTrue(result_json["does_not_fit"])
            self.assertEqual(result_json["packed_count"], 0)
            self.assertEqual(result_json["unpacked_count"], 5)
            self.assertFalse((out_dir / "arranged.step").exists())
            self.assertFalse((out_dir / "placements.csv").exists())
            self.assertIn("does not fit", result_json["error"])

    def test_run_packing_job_in_subprocess_emits_status_and_result(self) -> None:
        request = PackingRequest(
            input_path=Path("dummy.step"),
            out_dir=Path("out"),
            max_w=1000.0,
            max_h=1000.0,
            gap=10.0,
        )
        result = PackingRunResult(
            exit_code=0,
            out_dir=Path("out"),
            result_path=Path("out/result.json"),
            placements_path=Path("out/placements.csv"),
            log_path=Path("out/packing.log"),
            preview_top_path=None,
            preview_side_path=None,
            preview_gif_path=None,
            result_data={"status": "ok"},
        )
        events = _FakeQueue()

        def _fake_run(request_arg, **kwargs):
            kwargs["status_callback"]("reading")
            kwargs["status_callback"]("packing")
            return result

        with patch("packing_mvp.runner.run_packing_job", side_effect=_fake_run):
            run_packing_job_in_subprocess(request, events)

        self.assertEqual(
            events.items,
            [
                ("status", "reading"),
                ("status", "packing"),
                ("done", result),
            ],
        )

    def test_run_packing_job_in_subprocess_turns_crash_into_failure_result(self) -> None:
        request = PackingRequest(
            input_path=Path("dummy.step"),
            out_dir=Path("out"),
            max_w=1000.0,
            max_h=1000.0,
            gap=10.0,
        )
        failure_result = PackingRunResult(
            exit_code=3,
            out_dir=Path("out"),
            result_path=Path("out/result.json"),
            placements_path=Path("out/placements.csv"),
            log_path=Path("out/packing.log"),
            preview_top_path=None,
            preview_side_path=None,
            preview_gif_path=None,
            result_data={"status": "failed", "error": "Background worker failed: boom"},
        )
        events = _FakeQueue()

        with patch("packing_mvp.runner.run_packing_job", side_effect=RuntimeError("boom")):
            with patch("packing_mvp.runner.create_failure_run_result", return_value=failure_result):
                run_packing_job_in_subprocess(request, events)

        self.assertEqual(events.items, [("done", failure_result)])


if __name__ == "__main__":
    unittest.main()
