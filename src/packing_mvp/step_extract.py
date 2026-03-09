from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from packing_mvp.utils import Part, SourceSolid, combine_bboxes, dims_from_bbox


def extract_parts_from_step(
    input_path: Path,
    scale: float = 1.0,
    treat_input_as_single_item: bool = False,
    logger: Any | None = None,
) -> tuple[list[Part], dict[str, Any]]:
    try:
        import gmsh  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "gmsh is not installed. Install dependencies with 'python -m pip install -e .'"
        ) from exc

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"STEP file not found: {input_path}")

    if logger:
        logger.info("Opening STEP file: %s", input_path)

    auto_scale_applied = False
    auto_scale_factor = 1.0
    initialized = False

    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.clear()
        gmsh.model.add("step_extract")
        imported = gmsh.model.occ.importShapes(
            str(input_path),
            highestDimOnly=True,
            format="step",
        )
        gmsh.model.occ.synchronize()

        solids = sorted((dim, tag) for dim, tag in imported if dim == 3)
        if not solids:
            solids = sorted(gmsh.model.getEntities(3), key=lambda item: item[1])
        if not solids:
            raise RuntimeError("No solids found in STEP file.")

        raw_boxes: list[tuple[int, tuple[float, float, float, float, float, float]]] = []
        raw_max_dim = 0.0
        for _, tag in solids:
            bbox = gmsh.model.getBoundingBox(3, tag)
            dims = (
                max(0.0, bbox[3] - bbox[0]),
                max(0.0, bbox[4] - bbox[1]),
                max(0.0, bbox[5] - bbox[2]),
            )
            raw_max_dim = max(raw_max_dim, *dims)
            raw_boxes.append((tag, bbox))

        if raw_max_dim < 20.0:
            auto_scale_applied = True
            auto_scale_factor = 1000.0
            if logger:
                logger.info(
                    "auto scale applied: raw max dimension %.6f < 20, multiplying by 1000",
                    raw_max_dim,
                )

        total_scale = scale * auto_scale_factor
        scaled_solids = [
            SourceSolid(
                tag=tag,
                bbox_min=(
                    bbox[0] * total_scale,
                    bbox[1] * total_scale,
                    bbox[2] * total_scale,
                ),
                bbox_max=(
                    bbox[3] * total_scale,
                    bbox[4] * total_scale,
                    bbox[5] * total_scale,
                ),
            )
            for tag, bbox in raw_boxes
        ]
        parts = build_parts_from_scaled_solids(
            scaled_solids,
            treat_input_as_single_item=treat_input_as_single_item,
        )

        if logger:
            if treat_input_as_single_item:
                part = parts[0]
                logger.info(
                    "Extracted rigid group %s with %d solids dims_mm=(%.3f, %.3f, %.3f)",
                    part.part_id,
                    len(part.source_solids),
                    part.dims[0],
                    part.dims[1],
                    part.dims[2],
                )
            else:
                for part in parts:
                    logger.debug(
                        "Extracted %s (tag=%s) dims_mm=(%.3f, %.3f, %.3f) volume=%.3f",
                        part.part_id,
                        part.solid_tag,
                        part.dims[0],
                        part.dims[1],
                        part.dims[2],
                        part.volume,
                    )

        if logger:
            if treat_input_as_single_item:
                logger.info(
                    "Extracted %d source solids into %d rigid group",
                    len(scaled_solids),
                    len(parts),
                )
            else:
                logger.info("Extracted %d solids from STEP", len(parts))

        return parts, {
            "scale": total_scale,
            "manual_scale": scale,
            "auto_scale_applied": auto_scale_applied,
            "auto_scale_factor": auto_scale_factor,
            "raw_max_dim": raw_max_dim,
        }
    except Exception as exc:
        if logger:
            logger.exception("Failed to read STEP file")
        raise RuntimeError(f"Failed to read STEP file '{input_path}': {exc}") from exc
    finally:
        if initialized:
            try:
                gmsh.finalize()
            except Exception:
                pass


def extract_parts_from_step_files(
    input_paths: Sequence[Path],
    scale: float = 1.0,
    logger: Any | None = None,
) -> tuple[list[Part], dict[str, Any]]:
    normalized_input_paths = tuple(Path(path) for path in input_paths)
    if not normalized_input_paths:
        raise RuntimeError("No STEP files were provided.")

    parts: list[Part] = []
    source_units: list[dict[str, Any]] = []
    for index, input_path in enumerate(normalized_input_paths, start=1):
        extracted_parts, units = extract_parts_from_step(
            input_path=input_path,
            scale=scale,
            treat_input_as_single_item=True,
            logger=logger,
        )
        if len(extracted_parts) != 1:
            raise RuntimeError(
                f"Expected one grouped item for STEP file '{input_path}', got {len(extracted_parts)}."
            )

        extracted_part = extracted_parts[0]
        parts.append(
            Part(
                part_id=f"file_{index:03d}",
                solid_tag=None,
                dims=extracted_part.dims,
                volume=extracted_part.volume,
                bbox_min=extracted_part.bbox_min,
                bbox_max=extracted_part.bbox_max,
                mode="rigid_group",
                source_solids=extracted_part.source_solids,
            )
        )
        source_units.append(
            {
                "path": str(input_path),
                "scale": units.get("scale"),
                "manual_scale": units.get("manual_scale"),
                "auto_scale_applied": units.get("auto_scale_applied", False),
                "auto_scale_factor": units.get("auto_scale_factor"),
                "raw_max_dim": units.get("raw_max_dim"),
            }
        )
        if logger:
            logger.info(
                "Prepared packed item file_%03d from %s with %d solids",
                index,
                input_path,
                len(extracted_part.source_solids),
            )

    unique_scales = {entry.get("scale") for entry in source_units}
    unique_auto_factors = {entry.get("auto_scale_factor") for entry in source_units}
    return parts, {
        "scale": unique_scales.pop() if len(unique_scales) == 1 else None,
        "manual_scale": scale,
        "auto_scale_applied": any(entry.get("auto_scale_applied", False) for entry in source_units),
        "auto_scale_factor": unique_auto_factors.pop() if len(unique_auto_factors) == 1 else None,
        "source_units": source_units,
    }


def build_parts_from_scaled_solids(
    scaled_solids: Sequence[SourceSolid],
    *,
    treat_input_as_single_item: bool = False,
) -> list[Part]:
    solids = tuple(scaled_solids)
    if not solids:
        raise RuntimeError("No solids found in STEP file.")

    if not treat_input_as_single_item:
        parts: list[Part] = []
        for index, solid in enumerate(solids, start=1):
            dims = solid.dims
            parts.append(
                Part(
                    part_id=f"part_{index:03d}",
                    solid_tag=solid.tag,
                    dims=dims,
                    volume=dims[0] * dims[1] * dims[2],
                    bbox_min=solid.bbox_min,
                    bbox_max=solid.bbox_max,
                    mode="solid",
                    source_solids=(solid,),
                )
            )
        return parts

    aggregate_bbox = combine_bboxes(_solid_bbox(solid) for solid in solids)
    bbox_min = aggregate_bbox[:3]
    bbox_max = aggregate_bbox[3:]
    dims = dims_from_bbox(aggregate_bbox)
    return [
        Part(
            part_id="assembly_0",
            solid_tag=None,
            dims=dims,
            volume=dims[0] * dims[1] * dims[2],
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            mode="rigid_group",
            source_solids=solids,
        )
    ]


def _solid_bbox(solid: SourceSolid) -> tuple[float, float, float, float, float, float]:
    return (
        solid.bbox_min[0],
        solid.bbox_min[1],
        solid.bbox_min[2],
        solid.bbox_max[0],
        solid.bbox_max[1],
        solid.bbox_max[2],
    )
