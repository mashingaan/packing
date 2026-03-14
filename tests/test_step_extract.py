from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.step_extract import build_parts_from_scaled_solids, extract_parts_from_step_files
from packing_mvp.utils import Part, SourceSolid


class StepExtractTests(unittest.TestCase):
    def test_group_bbox_creation(self) -> None:
        solids = [
            SourceSolid(
                tag=11,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(100.0, 50.0, 20.0),
            ),
            SourceSolid(
                tag=12,
                bbox_min=(150.0, 10.0, 5.0),
                bbox_max=(260.0, 60.0, 40.0),
            ),
        ]

        parts = build_parts_from_scaled_solids(
            solids,
            treat_input_as_single_item=True,
        )

        self.assertEqual(len(parts), 1)
        part = parts[0]
        self.assertEqual(part.part_id, "assembly_0")
        self.assertEqual(part.mode, "rigid_group")
        self.assertEqual(part.orientation_policy, "assembly_axes_parallel_to_box_axes")
        self.assertEqual(part.dims, (260.0, 60.0, 40.0))
        self.assertEqual(part.bbox_min, (0.0, 0.0, 0.0))
        self.assertEqual(part.bbox_max, (260.0, 60.0, 40.0))
        self.assertEqual([solid.tag for solid in part.source_solids], [11, 12])

    def test_extract_parts_from_step_files_returns_one_part_per_file(self) -> None:
        grouped_parts = [
            [
                Part(
                    part_id="assembly_0",
                    solid_tag=None,
                    dims=(100.0, 50.0, 20.0),
                    volume=100.0 * 50.0 * 20.0,
                    bbox_min=(0.0, 0.0, 0.0),
                    bbox_max=(100.0, 50.0, 20.0),
                    mode="rigid_group",
                    source_solids=(
                        SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=(100.0, 50.0, 20.0)),
                    ),
                )
            ],
            [
                Part(
                    part_id="assembly_0",
                    solid_tag=None,
                    dims=(80.0, 40.0, 10.0),
                    volume=80.0 * 40.0 * 10.0,
                    bbox_min=(0.0, 0.0, 0.0),
                    bbox_max=(80.0, 40.0, 10.0),
                    mode="rigid_group",
                    source_solids=(
                        SourceSolid(tag=2, bbox_min=(0.0, 0.0, 0.0), bbox_max=(80.0, 40.0, 10.0)),
                    ),
                )
            ],
        ]
        unit_payloads = [
            {
                "scale": 1.0,
                "manual_scale": 1.0,
                "auto_scale_applied": False,
                "auto_scale_factor": 1.0,
                "raw_max_dim": 100.0,
            },
            {
                "scale": 1.0,
                "manual_scale": 1.0,
                "auto_scale_applied": False,
                "auto_scale_factor": 1.0,
                "raw_max_dim": 80.0,
            },
        ]

        with patch(
            "packing_mvp.step_extract.extract_parts_from_step",
            side_effect=list(zip(grouped_parts, unit_payloads)),
        ):
            parts, units = extract_parts_from_step_files(
                [Path("first.step"), Path("second.step")],
                scale=1.0,
            )

        self.assertEqual([part.part_id for part in parts], ["file_001", "file_002"])
        self.assertTrue(all(part.mode == "rigid_group" for part in parts))
        self.assertEqual(units["scale"], 1.0)
        self.assertEqual(units["auto_scale_factor"], 1.0)
        self.assertEqual(len(units["source_units"]), 2)


if __name__ == "__main__":
    unittest.main()
