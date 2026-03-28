from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.export import build_success_result, validate_constraints
from packing_mvp.packer import DoesNotFitError, PackOutcome


class ValidationTests(unittest.TestCase):
    def test_validation_fails_when_length_exceeds_limit(self) -> None:
        verdict = validate_constraints((10284.0, 2400.0, 1800.0), {"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 50})

        self.assertFalse(verdict["fits"])
        self.assertEqual(verdict["violations"][0]["axis"], "L")
        self.assertEqual(verdict["violations"][0]["actual"], 10284)

    def test_validation_succeeds_when_within_limits(self) -> None:
        verdict = validate_constraints((9980.0, 2400.0, 1800.0), {"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 50})

        self.assertTrue(verdict["fits"])
        self.assertEqual(verdict["violations"], [])

    def test_build_success_result_rejects_constraint_violation(self) -> None:
        with self.assertRaisesRegex(DoesNotFitError, "Превышение по длине кузова: 10284 мм при пределе 10000 мм, запас превышен на 284 мм."):
            build_success_result(
                input_paths=[Path("demo.step")],
                constraints={"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 50},
                outcome=PackOutcome(
                    placements=[],
                    used_extents=(10284.0, 2400.0, 1800.0),
                    recommended_dims=(10284, 2400, 1800),
                    container_dims=(10000, 3000, 2000),
                    search_length=10000,
                    fill_ratio_bbox=0.0,
                ),
                units={"scale": 1.0, "manual_scale": 1.0, "auto_scale_applied": False, "auto_scale_factor": 1.0},
            )


if __name__ == "__main__":
    unittest.main()
