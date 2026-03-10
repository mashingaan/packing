from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.export import build_success_result, validate_constraints, write_result_json
from packing_mvp.packer import PackOutcome


class ValidationTests(unittest.TestCase):
    def test_validation_fails_when_length_exceeds_limit(self) -> None:
        verdict = validate_constraints(
            (10284.0, 2400.0, 1800.0),
            {"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 0},
        )

        self.assertFalse(verdict["fits"])
        self.assertTrue(verdict["does_not_fit"])
        self.assertEqual(
            verdict["violations"],
            [
                {
                    "axis": "L",
                    "max": 10000,
                    "actual": 10284,
                    "excess": 284,
                }
            ],
        )

    def test_validation_succeeds_when_within_limits(self) -> None:
        verdict = validate_constraints(
            (9980.0, 2400.0, 1800.0),
            {"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 0},
        )

        self.assertTrue(verdict["fits"])
        self.assertFalse(verdict["does_not_fit"])
        self.assertEqual(verdict["violations"], [])

    def test_result_json_contains_fit_status_and_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = Path(tmp_dir) / "result.json"
            result = build_success_result(
                input_paths=[Path("demo.step")],
                constraints={"maxL": 10000, "maxW": 3000, "maxH": 2000, "gap": 0},
                outcome=PackOutcome(
                    placements=[],
                    used_extents=(10284.0, 2400.0, 1800.0),
                    recommended_dims=(10284, 2400, 1800),
                    container_dims=(10000, 3000, 2000),
                    search_length=10000,
                    fill_ratio_bbox=0.0,
                ),
                units={
                    "scale": 1.0,
                    "manual_scale": 1.0,
                    "auto_scale_applied": False,
                    "auto_scale_factor": 1.0,
                },
            )

            write_result_json(result, result_path)
            data = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(data["fits"])
        self.assertTrue(data["does_not_fit"])
        self.assertEqual(data["violations"][0]["axis"], "L")
        self.assertEqual(data["violations"][0]["actual"], 10284)
        self.assertEqual(data["used_extents_mm"]["L"], 10284)
        self.assertEqual(data["constraints"]["maxL"], 10000)


if __name__ == "__main__":
    unittest.main()
