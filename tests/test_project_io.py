from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.catalog import CatalogItem, PackProject, TruckConfig
from packing_mvp.project_io import load_project, save_project


class ProjectIoTests(unittest.TestCase):
    def test_project_save_load_roundtrip(self) -> None:
        project = PackProject(
            items=(
                CatalogItem(
                    item_id="item_001",
                    filename="crate.step",
                    source_path="crate.step",
                    detected_dims_mm=(1000.0, 800.0, 600.0),
                    dimensions_mm=(1010.0, 810.0, 610.0),
                    quantity=2,
                    manual_override=True,
                ),
            ),
            truck=TruckConfig(length_mm=9000.0, width_mm=2350.0, height_mm=2400.0, gap_mm=50.0),
            result={"status": "failed", "unplaced_items": [{"item_id": "item_001", "quantity": 1}]},
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = save_project(project, Path(tmp_dir) / "demo.packproj")
            restored = load_project(path)

        self.assertEqual(restored.truck.length_mm, 9000.0)
        self.assertEqual(restored.items[0].dimensions_mm, (1010.0, 810.0, 610.0))
        self.assertTrue(restored.items[0].manual_override)
        self.assertEqual(restored.result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
