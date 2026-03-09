from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from packing_mvp.utils import ensure_directory


def merge_step_files(
    input_paths: Sequence[Path],
    output_path: Path,
    *,
    logger: Any | None = None,
) -> Path:
    try:
        import gmsh  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "gmsh is not installed. Install dependencies with 'python -m pip install -e .'"
        ) from exc

    normalized_inputs = [Path(path) for path in input_paths]
    if not normalized_inputs:
        raise RuntimeError("No STEP files were provided for merge.")

    for input_path in normalized_inputs:
        if not input_path.exists():
            raise FileNotFoundError(f"STEP file not found: {input_path}")

    output_path = Path(output_path)
    ensure_directory(output_path.parent)

    initialized = False
    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.clear()
        gmsh.model.add("merged_step")

        for input_path in normalized_inputs:
            _log_info(logger, "Merging STEP source: %s", input_path)
            gmsh.model.occ.importShapes(
                str(input_path),
                highestDimOnly=True,
                format="step",
            )
            gmsh.model.occ.synchronize()

        solids = gmsh.model.getEntities(3)
        if not solids:
            raise RuntimeError("No solids found in selected STEP files.")

        gmsh.write(str(output_path))
        _log_info(
            logger,
            "Merged %d STEP file(s) into %s",
            len(normalized_inputs),
            output_path,
        )
        return output_path
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        if initialized:
            try:
                gmsh.finalize()
            except Exception:
                pass


def _log_info(logger: Any | None, message: str, *args: object) -> None:
    if logger is not None:
        logger.info(message, *args)
