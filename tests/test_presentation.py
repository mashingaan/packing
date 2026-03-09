from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.presentation import format_result_summary


class PresentationTests(unittest.TestCase):
    def test_success_summary_shows_full_dims_and_requested_length_percentage(self) -> None:
        summary = format_result_summary(
            {
                "status": "ok",
                "constraints": {"maxL": 4900},
                "recommended_dims_mm": {"L": 4280, "W": 2400, "H": 1800},
                "stats": {"n_parts": 24},
            }
        )

        self.assertEqual(
            summary,
            "\n".join(
                [
                    "Все детали помещаются",
                    "Размеры ящика: 4280 x 2400 x 1800 мм",
                    "4280 мм относится только к длине; детали могут быть повернуты на 90° и уложены по ширине/высоте",
                    "Использовано: 87% длины",
                    "Деталей: 24",
                ]
            ),
        )

    def test_success_summary_hides_usage_when_max_length_is_not_provided(self) -> None:
        summary = format_result_summary(
            {
                "status": "ok",
                "constraints": {"maxL": None},
                "recommended_dims_mm": {"L": 120, "W": 2400, "H": 1800},
                "stats": {"n_parts": 12},
            }
        )

        self.assertIn("Размеры ящика: 120 x 2400 x 1800 мм", summary)
        self.assertNotIn("Использовано:", summary)

    def test_success_summary_mentions_flat_only_when_enabled(self) -> None:
        summary = format_result_summary(
            {
                "status": "ok",
                "constraints": {"maxL": 4900, "flat_only": True},
                "recommended_dims_mm": {"L": 4280, "W": 2400, "H": 1800},
                "stats": {"n_parts": 24},
            }
        )

        self.assertIn("детали укладываются только плашмя", summary)
        self.assertIn("минимальному исходному габариту", summary)
        self.assertNotIn("детали могут быть повернуты", summary)

    def test_failure_summary_includes_error_and_parts(self) -> None:
        summary = format_result_summary(
            {
                "status": "failed",
                "error": "Packing failed",
                "stats": {"n_parts": 5},
            }
        )

        self.assertEqual(
            summary,
            "\n".join(
                [
                    "Не удалось уложить детали",
                    "Причина: Packing failed",
                    "Деталей: 5",
                ]
            ),
        )

    def test_failure_summary_includes_limit_exceeded_details(self) -> None:
        summary = format_result_summary(
            {
                "status": "failed",
                "error": "Не помещается",
                "limit_exceeded": {"axis": "L", "max": 10000, "actual": 10284, "excess": 284},
                "stats": {"n_parts": 5},
            }
        )

        self.assertEqual(
            summary,
            "\n".join(
                [
                    "Не удалось уложить детали",
                    "Причина: Не помещается",
                    "Превышен лимит: L = 10284 / 10000 мм, +284 мм",
                    "Деталей: 5",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
