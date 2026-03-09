from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.gui import _pick_step_file, _pick_step_files


class GuiDragDropTests(unittest.TestCase):
    def test_pick_step_file_prefers_supported_step_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            text_path = tmp_path / "notes.txt"
            step_path = tmp_path / "model.step"
            second_step_path = tmp_path / "model.stp"
            text_path.write_text("x", encoding="utf-8")
            step_path.write_text("step", encoding="utf-8")
            second_step_path.write_text("step", encoding="utf-8")

            picked = _pick_step_file([str(text_path), str(step_path), str(second_step_path)])

            self.assertEqual(picked, step_path)

    def test_pick_step_file_accepts_bytes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            step_path = Path(tmp_dir) / "demo.step"
            step_path.write_text("step", encoding="utf-8")

            picked = _pick_step_file([str(step_path).encode("utf-8")])

            self.assertEqual(picked, step_path)

    def test_pick_step_file_returns_none_for_dirs_and_other_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            folder_path = tmp_path / "folder.step"
            folder_path.mkdir()
            text_path = tmp_path / "demo.txt"
            text_path.write_text("x", encoding="utf-8")

            picked = _pick_step_file([str(folder_path), str(text_path)])

            self.assertIsNone(picked)

    def test_pick_step_files_returns_all_supported_files_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            first_step = tmp_path / "first.step"
            second_step = tmp_path / "second.stp"
            note_path = tmp_path / "note.txt"
            first_step.write_text("a", encoding="utf-8")
            second_step.write_text("b", encoding="utf-8")
            note_path.write_text("x", encoding="utf-8")

            picked = _pick_step_files([str(note_path), str(first_step), str(second_step)])

            self.assertEqual(picked, (first_step, second_step))


if __name__ == "__main__":
    unittest.main()
