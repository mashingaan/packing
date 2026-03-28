from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TextIO

from packing_mvp.presentation import format_result_summary, result_is_successful_fit
from packing_mvp.project_io import load_project
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


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be non-negative.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packer",
        description="Pack STEP-based shipping places into a truck cargo space.",
    )
    parser.add_argument("--input", nargs="+", type=Path, help="One or more .stp/.step files")
    parser.add_argument("--project", type=Path, help="Load a .packproj file instead of raw STEP inputs")
    parser.add_argument("--quantity", nargs="*", type=_positive_int, default=(), help="Quantity per input STEP file")
    parser.add_argument("--out", required=True, type=Path, help="Output folder")
    parser.add_argument("--maxL", type=_positive_float, default=13400.0, help="Truck length in mm")
    parser.add_argument("--maxW", type=_positive_float, default=2350.0, help="Truck width in mm")
    parser.add_argument("--maxH", type=_positive_float, default=2400.0, help="Truck height in mm")
    parser.add_argument("--gap", type=_nonnegative_float, default=50.0, help="Gap between neighboring items in mm")
    parser.add_argument("--scale", type=_positive_float, default=1.0, help="Manual scale multiplier for STEP import")
    parser.add_argument("--seed", type=int, default=42, help="Reserved deterministic seed")
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
    if args.project:
        project = load_project(args.project)
        request = PackingRequest(
            input_path=Path(project.items[0].source_path) if project.items else Path("project.packproj"),
            input_paths=tuple(Path(item.source_path) for item in project.items),
            input_quantities=tuple(item.quantity for item in project.items),
            catalog_items=tuple(project.items),
            out_dir=args.out,
            max_l=args.maxL if args.maxL else project.truck.length_mm,
            max_w=args.maxW if args.maxW else project.truck.width_mm,
            max_h=args.maxH if args.maxH else project.truck.height_mm,
            gap=args.gap if args.gap is not None else project.truck.gap_mm,
            scale=args.scale,
            seed=args.seed,
        )
    else:
        if not args.input:
            raise SystemExit("Either --input or --project is required.")
        input_paths = tuple(Path(path) for path in args.input)
        quantities = tuple(args.quantity) if args.quantity else tuple(1 for _ in input_paths)
        if len(quantities) != len(input_paths):
            raise SystemExit("--quantity must provide exactly one value per --input file.")
        request = PackingRequest(
            input_path=input_paths[0],
            input_paths=input_paths,
            input_quantities=quantities,
            out_dir=args.out,
            max_l=args.maxL,
            max_w=args.maxW,
            max_h=args.maxH,
            gap=args.gap,
            scale=args.scale,
            seed=args.seed,
        )

    result = run_packing_job(request, with_console=True)
    stream = sys.stdout if result.exit_code == 0 and result_is_successful_fit(result.result_data) else sys.stderr
    _print_text(stream, format_result_summary(result.result_data))
    _print_text(stream, f"Artifacts written to: {result.out_dir}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
