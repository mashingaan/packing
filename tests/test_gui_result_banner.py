from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.presentation import ERROR_BANNER, NO_FIT_BANNER, SUCCESS_BANNER, get_result_banner


class GuiResultBannerTests(unittest.TestCase):
    def test_success_result_shows_green_banner(self) -> None:
        self.assertEqual(get_result_banner(exit_code=0, result_data={"status": "ok", "fits": True}), SUCCESS_BANNER)

    def test_constraint_failure_shows_not_fit_banner(self) -> None:
        self.assertEqual(get_result_banner(exit_code=2, result_data={"status": "failed", "does_not_fit": True}), NO_FIT_BANNER)

    def test_non_constraint_failure_shows_generic_error_banner(self) -> None:
        self.assertEqual(get_result_banner(exit_code=2, result_data={"status": "failed", "error": "Failed to read STEP"}), ERROR_BANNER)


if __name__ == "__main__":
    unittest.main()
