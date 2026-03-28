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
    def test_success_summary_mentions_used_space_and_fill(self) -> None:
        summary = format_result_summary(
            {
                "status": "ok",
                "fits": True,
                "truck": {"length_mm": 13400, "width_mm": 2350, "height_mm": 2400},
                "used_extents_mm": {"L": 4280, "W": 2200, "H": 1800},
                "packed_count": 24,
                "fill_ratio": 0.37,
                "stats": {"n_parts": 24},
            }
        )

        self.assertIn("Все грузовые места размещены внутри кузова.", summary)
        self.assertIn("Использованные габариты кузова (мм): 4280 x 2200 x 1800", summary)
        self.assertIn("Заполнение кузова: 37.0%", summary)
        self.assertIn("Размещено мест: 24", summary)

    def test_failure_summary_includes_unplaced_items(self) -> None:
        summary = format_result_summary(
            {
                "status": "failed",
                "error": "Не все грузовые места помещаются в кузов.",
                "packed_count": 1,
                "unpacked_count": 2,
                "unplaced_items": [{"name": "crate.step", "quantity": 2}],
                "stats": {"n_parts": 3},
            }
        )

        self.assertIn("Не все грузовые места помещаются в кузов.", summary)
        self.assertIn("Размещено мест: 1", summary)
        self.assertIn("Неразмещено мест: 2", summary)
        self.assertIn("Список неразмещённых: crate.step x2", summary)
        self.assertIn("Запрошено всего: 3", summary)


if __name__ == "__main__":
    unittest.main()
