from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.utils import Part, Placement
from packing_mvp.viz import render_preview_gif


def _sample_placements() -> list[Placement]:
    part_a = Part(
        part_id="part_001",
        solid_tag=1,
        dims=(300.0, 200.0, 100.0),
        volume=300.0 * 200.0 * 100.0,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(300.0, 200.0, 100.0),
    )
    part_b = Part(
        part_id="part_002",
        solid_tag=2,
        dims=(220.0, 180.0, 140.0),
        volume=220.0 * 180.0 * 140.0,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(220.0, 180.0, 140.0),
    )
    return [
        Placement(part=part_a, x=10.0, y=10.0, z=10.0, dims=part_a.dims, rot="XYZ"),
        Placement(part=part_b, x=330.0, y=10.0, z=10.0, dims=part_b.dims, rot="XYZ"),
    ]


class PreviewGifTests(unittest.TestCase):
    def test_render_preview_gif_creates_non_empty_gif(self) -> None:
        placements = _sample_placements()

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            gif_path = render_preview_gif(
                placements=placements,
                out_dir=out_dir,
                container_dims=(1000, 600, 400),
            )

            data = gif_path.read_bytes()
            self.assertTrue(gif_path.exists())
            self.assertGreater(len(data), 6)
            self.assertTrue(data.startswith((b"GIF87a", b"GIF89a")))

            with Image.open(gif_path) as image:
                self.assertEqual(getattr(image, "n_frames", 1), len(placements) + 1)

    def test_render_preview_gif_keeps_one_frame_per_part_for_longer_sequence(self) -> None:
        base = _sample_placements()
        placements = base * 4

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            gif_path = render_preview_gif(
                placements=placements,
                out_dir=out_dir,
                container_dims=(1400, 600, 400),
            )

            with Image.open(gif_path) as image:
                self.assertEqual(getattr(image, "n_frames", 1), len(placements) + 1)


if __name__ == "__main__":
    unittest.main()
