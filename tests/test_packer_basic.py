from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.catalog import CatalogItem, build_parts_from_catalog
from packing_mvp.packer import _resolve_allowed_orientations, pack_items_in_truck
from packing_mvp.utils import Part, SourceSolid


def _part(part_id: str, dims: tuple[float, float, float]) -> Part:
    return Part(
        part_id=part_id,
        solid_tag=None,
        dims=dims,
        volume=dims[0] * dims[1] * dims[2],
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=dims,
        mode="rigid_group",
        source_solids=(SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=dims),),
        source_path=f"{part_id}.step",
    )


class PackerBasicTests(unittest.TestCase):
    def test_quantity_expansion(self) -> None:
        parts = build_parts_from_catalog(
            [
                CatalogItem(
                    item_id="item_001",
                    filename="crate.step",
                    source_path="crate.step",
                    detected_dims_mm=(1000.0, 800.0, 600.0),
                    dimensions_mm=(1000.0, 800.0, 600.0),
                    quantity=3,
                )
            ]
        )

        self.assertEqual(len(parts), 3)
        self.assertEqual([part.part_id for part in parts], ["item_001_copy_001", "item_001_copy_002", "item_001_copy_003"])

    def test_z_rotation_only_orientations(self) -> None:
        orientations = _resolve_allowed_orientations(_part("box", (1200.0, 800.0, 600.0)))

        self.assertEqual([candidate.rot for candidate in orientations], ["XYZ", "YXZ"])
        self.assertEqual([candidate.dims for candidate in orientations], [(1200.0, 800.0, 600.0), (800.0, 1200.0, 600.0)])
        self.assertTrue(all(candidate.planar_angle_deg == 0.0 for candidate in orientations))

    def test_basic_fit_inside_truck(self) -> None:
        outcome = pack_items_in_truck(
            [
                _part("box_a", (2000.0, 1000.0, 1000.0)),
                _part("box_b", (1500.0, 1000.0, 1000.0)),
                _part("box_c", (1200.0, 1000.0, 800.0)),
            ],
            truck_l=7000.0,
            truck_w=2350.0,
            truck_h=2400.0,
            gap=50.0,
        )

        self.assertTrue(outcome.success)
        self.assertEqual(len(outcome.placements), 3)
        self.assertFalse(outcome.unplaced_parts)
        for placement in outcome.placements:
            self.assertLessEqual(placement.x + placement.dx, 7000.0 + 1e-6)
            self.assertLessEqual(placement.y + placement.dy, 2350.0 + 1e-6)
            self.assertLessEqual(placement.z + placement.dz, 2400.0 + 1e-6)

    def test_not_all_items_fit_reports_unplaced(self) -> None:
        outcome = pack_items_in_truck(
            [
                _part("box_a", (3000.0, 1000.0, 1000.0)),
                _part("box_b", (3000.0, 1000.0, 1000.0)),
                _part("box_c", (3000.0, 1000.0, 1000.0)),
            ],
            truck_l=5000.0,
            truck_w=1200.0,
            truck_h=1200.0,
            gap=50.0,
        )

        self.assertFalse(outcome.success)
        self.assertGreaterEqual(len(outcome.placements), 1)
        self.assertEqual(len(outcome.unplaced_parts), 2)


if __name__ == "__main__":
    unittest.main()
