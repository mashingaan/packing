from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.presentation import ERROR_BANNER, NO_FIT_BANNER, SUCCESS_BANNER, get_result_banner


def _make_result_data(*, status: str, error: str | None = None) -> dict[str, str]:
    result_data = {"status": status}
    if error is not None:
        result_data["error"] = error
    return result_data


class GuiResultBannerTests(unittest.TestCase):
    def test_success_result_shows_green_banner(self) -> None:
        result_data = _make_result_data(status="ok")
        self.assertEqual(get_result_banner(exit_code=0, result_data=result_data), SUCCESS_BANNER)

    def test_constraint_failure_shows_not_fit_banner(self) -> None:
        result_data = _make_result_data(
            status="failed",
            error="Packing failed: parts do not fit into L=1200, W=800, H=600.",
        )
        self.assertEqual(get_result_banner(exit_code=2, result_data=result_data), NO_FIT_BANNER)

    def test_non_constraint_failure_shows_generic_error_banner(self) -> None:
        result_data = _make_result_data(
            status="failed",
            error="Failed to read STEP file 'bad.step': No solids found in STEP file.",
        )
        self.assertEqual(get_result_banner(exit_code=2, result_data=result_data), ERROR_BANNER)

    def test_explicit_does_not_fit_shows_not_fit_banner(self) -> None:
        result_data = _make_result_data(status="failed", error="Не помещается")
        result_data["does_not_fit"] = True
        self.assertEqual(get_result_banner(exit_code=2, result_data=result_data), NO_FIT_BANNER)


if __name__ == "__main__":
    unittest.main()
