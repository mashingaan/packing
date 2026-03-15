from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.runner import PackingRequest
from packing_mvp.strategies import resolve_packing_strategy


class StrategySelectionTests(unittest.TestCase):
    def test_strategy_selection_default_solids(self) -> None:
        strategy = resolve_packing_strategy(
            PackingRequest(
                input_path=Path("demo.step"),
                out_dir=Path("out"),
                max_w=1000.0,
                max_h=1000.0,
                gap=10.0,
            )
        )

        self.assertEqual(strategy.packing_mode, "solids")
        self.assertFalse(strategy.treat_input_as_single_item)
        self.assertFalse(strategy.flat_only)

    def test_strategy_selection_single_root_shape(self) -> None:
        strategy = resolve_packing_strategy(
            PackingRequest(
                input_path=Path("demo.step"),
                out_dir=Path("out"),
                max_w=1000.0,
                max_h=1000.0,
                gap=10.0,
                packing_mode="single_root_shape",
            )
        )

        self.assertEqual(strategy.packing_mode, "single_root_shape")
        self.assertTrue(strategy.treat_input_as_single_item)
        self.assertFalse(strategy.flat_only)
        self.assertEqual(strategy.orientation_policy, "default")

    def test_strategy_selection_flat_assembly_footprint(self) -> None:
        strategy = resolve_packing_strategy(
            PackingRequest(
                input_path=Path("demo.step"),
                out_dir=Path("out"),
                max_w=1000.0,
                max_h=1000.0,
                gap=10.0,
                packing_mode="flat_assembly_footprint",
                planar_rotation_step_deg=5.0,
            )
        )

        self.assertEqual(strategy.packing_mode, "flat_assembly_footprint")
        self.assertTrue(strategy.treat_input_as_single_item)
        self.assertTrue(strategy.flat_only)
        self.assertEqual(strategy.orientation_policy, "flat_assembly_footprint")
        self.assertEqual(strategy.planar_rotation_step_deg, 0.0)


if __name__ == "__main__":
    unittest.main()
