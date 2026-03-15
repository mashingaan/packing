from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.packer import PackingError, _resolve_allowed_orientations, pack_parts
from packing_mvp.utils import (
    Part,
    SourceSolid,
    build_rigid_group_copy_parts,
    canonical_flat_assembly_orientation,
    canonical_rigid_assembly_orientation,
    filter_orientations_flat_only,
    orientation_to_rigid_rotation,
    rigid_group_flat_assembly_footprint_dims,
    rotation_matrix_determinant,
    rotation_matrix_is_orthonormal,
    sample_planar_angles,
)


def _rigid_group_part(dims: tuple[float, float, float]) -> Part:
    primary_max = (dims[0] * 0.75, dims[1], dims[2])
    secondary_min = (dims[0] * 0.8, dims[1] * 0.1, 0.0)
    secondary_max = (dims[0], dims[1] * 0.4, dims[2] * 0.5)
    return Part(
        part_id="assembly_0",
        solid_tag=None,
        dims=dims,
        volume=dims[0] * dims[1] * dims[2],
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=dims,
        mode="rigid_group",
        orientation_policy="assembly_axes_parallel_to_box_axes",
        source_solids=(
            SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=primary_max),
            SourceSolid(tag=2, bbox_min=secondary_min, bbox_max=secondary_max),
        ),
    )


def _flat_assembly_part(dims: tuple[float, float, float]) -> Part:
    part = _rigid_group_part(dims)
    return Part(
        part_id=part.part_id,
        solid_tag=part.solid_tag,
        dims=part.dims,
        volume=part.volume,
        bbox_min=part.bbox_min,
        bbox_max=part.bbox_max,
        mode=part.mode,
        orientation_policy="flat_assembly_footprint",
        source_solids=part.source_solids,
    )


class PackerBasicTests(unittest.TestCase):
    def test_orientations_without_flat_only(self) -> None:
        orientations = filter_orientations_flat_only((100.0, 200.0, 300.0), flat_only=False)

        self.assertEqual(len(orientations), 6)
        self.assertEqual(
            orientations,
            [
                ("XYZ", (100.0, 200.0, 300.0)),
                ("XZY", (100.0, 300.0, 200.0)),
                ("YXZ", (200.0, 100.0, 300.0)),
                ("YZX", (200.0, 300.0, 100.0)),
                ("ZXY", (300.0, 100.0, 200.0)),
                ("ZYX", (300.0, 200.0, 100.0)),
            ],
        )

    def test_orientations_with_flat_only(self) -> None:
        orientations = filter_orientations_flat_only((100.0, 200.0, 300.0), flat_only=True)

        self.assertEqual(
            orientations,
            [
                ("YZX", (200.0, 300.0, 100.0)),
                ("ZYX", (300.0, 200.0, 100.0)),
            ],
        )
        self.assertTrue(all(abs(rotated_dims[2] - 100.0) <= 1e-6 for _, rotated_dims in orientations))
        self.assertFalse(any(abs(rotated_dims[2] - 200.0) <= 1e-6 for _, rotated_dims in orientations))
        self.assertFalse(any(abs(rotated_dims[2] - 300.0) <= 1e-6 for _, rotated_dims in orientations))

    def test_flat_only_single_root_shape(self) -> None:
        group = _rigid_group_part((100.0, 200.0, 300.0))

        orientations = filter_orientations_flat_only(group.dims, flat_only=True)

        self.assertEqual(
            orientations,
            [
                ("YZX", (200.0, 300.0, 100.0)),
                ("ZYX", (300.0, 200.0, 100.0)),
            ],
        )
        self.assertTrue(all(abs(rotated_dims[2] - 100.0) <= 1e-6 for _, rotated_dims in orientations))

    def test_flat_only_filters_labels_but_not_transform_type(self) -> None:
        orientations = filter_orientations_flat_only((100.0, 200.0, 300.0), flat_only=True)
        self.assertEqual([label for label, _ in orientations], ["YZX", "ZYX"])

        for label, _ in orientations:
            with self.subTest(label=label):
                rotation = orientation_to_rigid_rotation(label)
                self.assertTrue(rotation_matrix_is_orthonormal(rotation.matrix))
                self.assertAlmostEqual(rotation_matrix_determinant(rotation.matrix), 1.0, places=6)

    def test_pack_parts_finds_solution_and_recommended_dims(self) -> None:
        parts = [
            Part("part_001", 1, (500.0, 300.0, 200.0), 500.0 * 300.0 * 200.0, (0.0, 0.0, 0.0), (500.0, 300.0, 200.0)),
            Part("part_002", 2, (400.0, 250.0, 250.0), 400.0 * 250.0 * 250.0, (0.0, 0.0, 0.0), (400.0, 250.0, 250.0)),
            Part("part_003", 3, (300.0, 200.0, 150.0), 300.0 * 200.0 * 150.0, (0.0, 0.0, 0.0), (300.0, 200.0, 150.0)),
        ]

        outcome = pack_parts(
            parts=parts,
            max_w=1200.0,
            max_h=900.0,
            gap=10.0,
            max_l=None,
            seed=42,
        )

        self.assertEqual(len(outcome.placements), 3)
        self.assertGreater(outcome.recommended_dims[0], 0)
        self.assertGreater(outcome.recommended_dims[1], 0)
        self.assertGreater(outcome.recommended_dims[2], 0)
        self.assertGreaterEqual(outcome.recommended_dims[0], int(outcome.used_extents[0]))
        self.assertGreaterEqual(outcome.recommended_dims[1], int(outcome.used_extents[1]))
        self.assertGreaterEqual(outcome.recommended_dims[2], int(outcome.used_extents[2]))
        self.assertGreater(outcome.fill_ratio_bbox, 0.0)

        for placement in outcome.placements:
            self.assertGreaterEqual(placement.x, 10.0)
            self.assertGreaterEqual(placement.y, 10.0)
            self.assertGreaterEqual(placement.z, 10.0)
            self.assertLessEqual(placement.x + placement.dx, outcome.search_length - 10.0 + 1e-6)
            self.assertLessEqual(placement.y + placement.dy, 1200.0 - 10.0 + 1e-6)
            self.assertLessEqual(placement.z + placement.dz, 900.0 - 10.0 + 1e-6)

    def test_pack_parts_raises_when_fixed_length_too_small(self) -> None:
        parts = [
            Part("part_001", 1, (700.0, 300.0, 200.0), 700.0 * 300.0 * 200.0, (0.0, 0.0, 0.0), (700.0, 300.0, 200.0)),
            Part("part_002", 2, (650.0, 280.0, 220.0), 650.0 * 280.0 * 220.0, (0.0, 0.0, 0.0), (650.0, 280.0, 220.0)),
        ]

        with self.assertRaises(PackingError):
            pack_parts(
                parts=parts,
                max_w=350.0,
                max_h=250.0,
                gap=10.0,
                max_l=800.0,
                seed=42,
            )

    def test_pack_parts_can_minimize_length_by_rotating_thin_parts(self) -> None:
        parts = [
            Part(
                f"part_{index:03d}",
                index,
                (1000.0, 500.0, 20.0),
                1000.0 * 500.0 * 20.0,
                (0.0, 0.0, 0.0),
                (1000.0, 500.0, 20.0),
            )
            for index in range(1, 13)
        ]

        outcome = pack_parts(
            parts=parts,
            max_w=2400.0,
            max_h=1800.0,
            gap=10.0,
            max_l=None,
            seed=42,
        )

        self.assertEqual(len(outcome.placements), 12)
        self.assertLess(outcome.recommended_dims[0], 200)
        self.assertLess(outcome.recommended_dims[0], max(parts[0].dims))
        self.assertTrue(any(placement.rot != "XYZ" for placement in outcome.placements))
        self.assertTrue(any(abs(placement.dx - 20.0) <= 1e-6 for placement in outcome.placements))

        for placement in outcome.placements:
            self.assertGreaterEqual(placement.x, 10.0)
            self.assertGreaterEqual(placement.y, 10.0)
            self.assertGreaterEqual(placement.z, 10.0)
            self.assertLessEqual(placement.x + placement.dx, outcome.search_length - 10.0 + 1e-6)
            self.assertLessEqual(placement.y + placement.dy, 2400.0 - 10.0 + 1e-6)
            self.assertLessEqual(placement.z + placement.dz, 1800.0 - 10.0 + 1e-6)

    def test_single_root_shape_mode_has_one_placement(self) -> None:
        group = _rigid_group_part((300.0, 200.0, 100.0))

        outcome = pack_parts(
            parts=[group],
            max_w=600.0,
            max_h=400.0,
            gap=10.0,
            max_l=500.0,
            flat_only=True,
        )

        self.assertEqual(len(outcome.placements), 1)
        placement = outcome.placements[0]
        self.assertEqual(placement.part.part_id, "assembly_0")
        self.assertEqual(placement.part.mode, "rigid_group")
        self.assertEqual(len(placement.part.source_solids), 2)
        self.assertAlmostEqual(placement.dz, 100.0)

    def test_multi_copy_single_root_shape_creates_n_items(self) -> None:
        group = _rigid_group_part((200.0, 350.0, 100.0))
        copies = build_rigid_group_copy_parts(group, 5)

        outcome = pack_parts(
            parts=copies,
            max_w=500.0,
            max_h=150.0,
            max_l=1200.0,
            gap=10.0,
            flat_only=True,
            planar_rotation_step_deg=5.0,
        )

        self.assertEqual(len(outcome.placements), 5)
        self.assertEqual(
            sorted(placement.part.part_id for placement in outcome.placements),
            [f"assembly_0_copy_{index:03d}" for index in range(5)],
        )
        self.assertTrue(all(placement.part.mode == "rigid_group" for placement in outcome.placements))

    def test_flat_only_single_item_disables_planar_rotation_sampling(self) -> None:
        group = _rigid_group_part((100.0, 200.0, 300.0))

        orientations = _resolve_allowed_orientations(
            group,
            flat_only=True,
            planar_rotation_step_deg=90.0,
        )

        self.assertEqual(len(orientations), 1)
        self.assertEqual([candidate.planar_angle_deg for candidate in orientations], [0.0])
        self.assertEqual([candidate.rot for candidate in orientations], ["ZYX"])
        self.assertEqual([candidate.dims for candidate in orientations], [(300.0, 200.0, 100.0)])

    def test_flat_only_single_item_uses_one_base_orientation_without_planar_step(self) -> None:
        group = _rigid_group_part((10000.0, 900.0, 300.0))

        orientations = _resolve_allowed_orientations(
            group,
            flat_only=True,
            planar_rotation_step_deg=0.0,
        )

        self.assertEqual(len(orientations), 1)
        self.assertEqual(orientations[0].rot, "XYZ")
        self.assertEqual(orientations[0].planar_angle_deg, 0.0)
        self.assertEqual(orientations[0].dims, (10000.0, 900.0, 300.0))

    def test_canonical_rigid_assembly_orientation_maps_longest_middle_shortest(self) -> None:
        rot, dims = canonical_rigid_assembly_orientation((900.0, 300.0, 10000.0))

        self.assertEqual(rot, "ZXY")
        self.assertEqual(dims, (10000.0, 900.0, 300.0))

    def test_flat_assembly_orientation_policy(self) -> None:
        rot, dims = canonical_flat_assembly_orientation((900.0, 300.0, 10000.0))
        flat_part = _flat_assembly_part((900.0, 300.0, 10000.0))
        footprint_rot, footprint_dims = rigid_group_flat_assembly_footprint_dims(
            flat_part.source_solids,
            flat_part.dims,
        )

        self.assertEqual(rot, "ZXY")
        self.assertEqual(dims, (10000.0, 900.0, 300.0))
        self.assertEqual(footprint_rot, "ZXY")
        self.assertEqual(footprint_dims, (10000.0, 900.0, 300.0))

    def test_single_item_ladder_like_model_stays_axis_aligned(self) -> None:
        group = _rigid_group_part((10000.0, 900.0, 300.0))

        outcome = pack_parts(
            parts=[group],
            max_w=1200.0,
            max_h=500.0,
            max_l=11000.0,
            gap=10.0,
            flat_only=True,
            planar_rotation_step_deg=5.0,
        )

        self.assertEqual(len(outcome.placements), 1)
        placement = outcome.placements[0]
        self.assertEqual(placement.rot, "XYZ")
        self.assertEqual(placement.planar_angle_deg, 0.0)
        self.assertEqual((placement.dx, placement.dy, placement.dz), (10000.0, 900.0, 300.0))

    def test_planar_angle_sampling(self) -> None:
        self.assertEqual(sample_planar_angles(5.0), [float(value) for value in range(0, 360, 5)])
        self.assertEqual(sample_planar_angles(1.0), [float(value) for value in range(0, 360)])
        self.assertEqual(len(sample_planar_angles(5.0)), len(set(sample_planar_angles(5.0))))
        self.assertEqual(len(sample_planar_angles(1.0)), len(set(sample_planar_angles(1.0))))


if __name__ == "__main__":
    unittest.main()
