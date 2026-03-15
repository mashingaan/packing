from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TextIO

from packing_mvp.presentation import format_result_summary, result_is_successful_fit
from packing_mvp.runner import PackingRequest, run_packing_job
from packing_mvp.strategies import USER_PACKING_MODES


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
        "--packing-mode",
        choices=USER_PACKING_MODES,
        default=None,
        help=(
            "Packing strategy: solids, single_root_shape, or flat_assembly_footprint. "
            "If omitted, legacy flags are normalized to one resolved mode."
        ),
    )
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


def _print_text(stream: TextIO, text: str) -> None:
    try:
        print(text, file=stream)
        return
    except UnicodeEncodeError:
        if _try_reconfigure_utf8(stream):
            print(text, file=stream)
            return

    _write_with_replacement(stream, f"{text}\n")


def _try_reconfigure_utf8(stream: TextIO) -> bool:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return False
    try:
        reconfigure(encoding="utf-8", errors="strict")
    except (OSError, ValueError):
        return False
    return True


def _write_with_replacement(stream: TextIO, text: str) -> None:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    payload = text.encode(encoding, errors="replace")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
    else:
        stream.write(payload.decode(encoding, errors="replace"))
    stream.flush()


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
            packing_mode=args.packing_mode,
            flat_only=args.flat_only,
            treat_input_as_single_item=args.treat_input_as_single_item,
            copies=args.copies,
            planar_rotation_step_deg=args.planar_rotation_step_deg,
        ),
        with_console=True,
    )
    stream = sys.stdout if result.exit_code == 0 and result_is_successful_fit(result.result_data) else sys.stderr
    _print_text(stream, format_result_summary(result.result_data))
    _print_text(stream, f"Результаты сохранены в: {result.out_dir}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
