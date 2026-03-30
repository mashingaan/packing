from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.catalog import CatalogItem
from packing_mvp.step_extract import _load_scaled_solids, build_parts_from_scaled_solids, extract_parts_from_step_files
from packing_mvp.utils import SourceSolid


class _FakeOption:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def setNumber(self, name: str, value: float) -> None:
        self.calls.append((name, value))


class _FakeOcc:
    def importShapes(self, path: str, highestDimOnly: bool = True, format: str = "step"):
        return [(3, 1)]

    def synchronize(self) -> None:
        pass


class _FakeModel:
    def __init__(self) -> None:
        self.occ = _FakeOcc()
        self.names: list[str] = []

    def add(self, name: str) -> None:
        self.names.append(name)

    def getEntities(self, dim: int):
        if dim == 3:
            return [(3, 1)]
        return []

    def getBoundingBox(self, dim: int, tag: int):
        return (0.0, 0.0, 0.0, 100.0, 50.0, 20.0)


class _FakeGmsh:
    def __init__(self) -> None:
        self.option = _FakeOption()
        self.model = _FakeModel()
        self.initialize_kwargs: list[dict[str, object]] = []
        self.clear_calls = 0
        self.finalize_calls = 0

    def initialize(self, **kwargs) -> None:
        self.initialize_kwargs.append(dict(kwargs))

    def clear(self) -> None:
        self.clear_calls += 1

    def finalize(self) -> None:
        self.finalize_calls += 1


class StepExtractTests(unittest.TestCase):
    def test_dimension_extraction_or_override(self) -> None:
        solids = [
            SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=(1000.0, 500.0, 400.0)),
            SourceSolid(tag=2, bbox_min=(1200.0, 0.0, 0.0), bbox_max=(1800.0, 600.0, 450.0)),
        ]
        parts = build_parts_from_scaled_solids(solids, treat_input_as_single_item=True)

        self.assertEqual(parts[0].dims, (1800.0, 600.0, 450.0))

        item = CatalogItem(
            item_id="item_001",
            filename="demo.step",
            source_path="demo.step",
            detected_dims_mm=parts[0].dims,
            dimensions_mm=parts[0].dims,
            quantity=1,
        ).with_dimensions((1810.0, 610.0, 455.0))

        self.assertTrue(item.manual_override)
        self.assertEqual(item.dimensions_mm, (1810.0, 610.0, 455.0))

    def test_extract_parts_from_step_files_returns_one_part_per_file(self) -> None:
        grouped_parts = [
            build_parts_from_scaled_solids(
                [SourceSolid(tag=1, bbox_min=(0.0, 0.0, 0.0), bbox_max=(100.0, 50.0, 20.0))],
                treat_input_as_single_item=True,
            ),
            build_parts_from_scaled_solids(
                [SourceSolid(tag=2, bbox_min=(0.0, 0.0, 0.0), bbox_max=(80.0, 40.0, 10.0))],
                treat_input_as_single_item=True,
            ),
        ]
        unit_payloads = [
            {"scale": 1.0, "manual_scale": 1.0, "auto_scale_applied": False, "auto_scale_factor": 1.0, "raw_max_dim": 100.0},
            {"scale": 1.0, "manual_scale": 1.0, "auto_scale_applied": False, "auto_scale_factor": 1.0, "raw_max_dim": 80.0},
        ]

        with patch("packing_mvp.step_extract.extract_parts_from_step", side_effect=list(zip(grouped_parts, unit_payloads))):
            parts, units = extract_parts_from_step_files([Path("first.step"), Path("second.step")], scale=1.0)

        self.assertEqual([part.part_id for part in parts], ["file_001", "file_002"])
        self.assertEqual([part.source_path for part in parts], ["first.step", "second.step"])
        self.assertEqual(len(units["source_units"]), 2)

    def test_load_scaled_solids_disables_gmsh_signal_handlers(self) -> None:
        fake_gmsh = _FakeGmsh()

        with patch.dict(sys.modules, {"gmsh": fake_gmsh}):
            with patch("pathlib.Path.exists", return_value=True):
                solids, units = _load_scaled_solids(
                    input_path=Path("demo.step"),
                    scale=1.0,
                    logger=None,
                )

        self.assertEqual(len(solids), 1)
        self.assertEqual(units["scale"], 1.0)
        self.assertEqual(fake_gmsh.initialize_kwargs, [{"interruptible": False}])
        self.assertEqual(fake_gmsh.finalize_calls, 1)


if __name__ == "__main__":
    unittest.main()
