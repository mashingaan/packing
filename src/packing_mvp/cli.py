from __future__ import annotations

import argparse
from pathlib import Path
import sys

from packing_mvp.presentation import format_result_summary
from packing_mvp.runner import PackingRequest, run_packing_job


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive integer.")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive number.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packer",
        description="Pack STEP assembly solids into a container using bbox-based extreme points.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to .stp or .step file")
    parser.add_argument("--out", required=True, type=Path, help="Output folder")
    parser.add_argument("--maxW", required=True, type=float, help="Container max width in mm")
    parser.add_argument("--maxH", required=True, type=float, help="Container max height in mm")
    parser.add_argument("--maxL", type=float, default=None, help="Container max length in mm")
    parser.add_argument("--gap", required=True, type=float, help="Gap between parts and walls in mm")
    parser.add_argument("--scale", type=float, default=1.0, help="Manual scale multiplier")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed for tie-breaking")
    parser.add_argument(
        "--flat-only",
        action="store_true",
        help="Allow only flat orientations where part height equals its minimal original dimension",
    )
    parser.add_argument(
        "--treat-input-as-single-item",
        action="store_true",
        help="Treat the whole input STEP as one rigid item and preserve relative positions of its solids",
    )
    parser.add_argument(
        "--copies",
        type=_positive_int,
        default=1,
        help="Pack N identical rigid copies of the same input STEP model (requires --treat-input-as-single-item)",
    )
    parser.add_argument(
        "--planar-rotation-step-deg",
        type=_positive_float,
        default=0.0,
        help="Experimental in-plane rotation step in degrees for flat rigid items (requires --flat-only and --treat-input-as-single-item)",
    )
    parser.add_argument(
        "--step-units",
        choices=("packed", "source"),
        default="packed",
        help="Units for arranged.step output: packed coordinates or original source units",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_packing_job(
        PackingRequest(
            input_path=args.input,
            out_dir=args.out,
            max_w=args.maxW,
            max_h=args.maxH,
            max_l=args.maxL,
            gap=args.gap,
            scale=args.scale,
            seed=args.seed,
            step_units=args.step_units,
            flat_only=args.flat_only,
            treat_input_as_single_item=args.treat_input_as_single_item,
            copies=args.copies,
            planar_rotation_step_deg=args.planar_rotation_step_deg,
        ),
        with_console=True,
    )
    stream = sys.stdout if result.exit_code == 0 else sys.stderr
    print(format_result_summary(result.result_data), file=stream)
    print(f"Результаты сохранены в: {result.out_dir}", file=stream)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
