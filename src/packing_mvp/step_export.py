from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from packing_mvp.gmsh_runtime import initialize_gmsh
from packing_mvp.strategies.base import PackingMode
from packing_mvp.utils import (
    EPS,
    Placement,
    RigidRotation,
    ensure_directory,
    orientation_to_rigid_rotation,
)

StepUnitsMode = Literal["packed", "source"]

_SOLID_PLACEMENT_COLUMNS = (
    "part_id",
    "solid_tag",
    "dx",
    "dy",
    "dz",
    "x",
    "y",
    "z",
    "bbox_minx",
    "bbox_miny",
    "bbox_minz",
    "bbox_maxx",
    "bbox_maxy",
    "bbox_maxz",
)

_RIGID_GROUP_PLACEMENT_COLUMNS = (
    "item_id",
    "mode",
    "copy_index",
    "source_count",
    "source_tags",
    "dx",
    "dy",
    "dz",
    "x",
    "y",
    "z",
    "rot",
    "planar_angle_deg",
    "bbox_minx",
    "bbox_miny",
    "bbox_minz",
    "bbox_maxx",
    "bbox_maxy",
    "bbox_maxz",
)

_RIGID_GROUP_REQUIRED_COLUMNS = (
    "item_id",
    "mode",
    "source_count",
    "source_tags",
    "dx",
    "dy",
    "dz",
    "x",
    "y",
    "z",
    "rot",
    "bbox_minx",
    "bbox_miny",
    "bbox_minz",
    "bbox_maxx",
    "bbox_maxy",
    "bbox_maxz",
)

_VALID_ROTATIONS = {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}


@dataclass(frozen=True)
class PlacementRecord:
    row_number: int
    item_id: str
    mode: Literal["solid", "rigid_group"]
    solid_tag: int | None
    copy_index: int
    source_count: int
    source_tags: tuple[int, ...]
    dx: float
    dy: float
    dz: float
    x: float
    y: float
    z: float
    rot: str
    planar_angle_deg: float
    bbox_minx: float
    bbox_miny: float
    bbox_minz: float
    bbox_maxx: float
    bbox_maxy: float
    bbox_maxz: float

    @property
    def part_id(self) -> str:
        return self.item_id


@dataclass(frozen=True)
class _OcpModules:
    BRep_Builder: Any
    BRepBndLib: Any
    BRepBuilderAPI_Transform: Any
    Bnd_Box: Any
    IFSelect_RetDone: Any
    STEPControl_AsIs: Any
    STEPControl_Reader: Any
    STEPControl_Writer: Any
    TopoDS_Compound: Any
    gp_Ax1: Any
    gp_Dir: Any
    gp_Pnt: Any
    gp_Trsf: Any
    gp_Vec: Any


def load_placements_csv(path: Path) -> list[PlacementRecord]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Placements CSV not found: {path}")

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError(f"Placements CSV has no header row: {path}")

        normalized_fieldnames = [_normalize_header(name) for name in reader.fieldnames]
        rigid_group_schema = _is_rigid_group_schema(normalized_fieldnames)
        required_columns = (
            _RIGID_GROUP_REQUIRED_COLUMNS if rigid_group_schema else _SOLID_PLACEMENT_COLUMNS
        )
        missing = [name for name in required_columns if name not in normalized_fieldnames]
        if missing:
            missing_text = ", ".join(missing)
            raise RuntimeError(f"Placements CSV is missing required columns: {missing_text}")

        placements: list[PlacementRecord] = []
        for row_number, raw_row in enumerate(reader, start=2):
            row = {_normalize_header(key): value for key, value in raw_row.items() if key is not None}
            rot = (row.get("rot") or "").strip() or "XYZ"
            if rot not in _VALID_ROTATIONS:
                raise RuntimeError(
                    f"Placements CSV row {row_number}: unsupported rotation '{rot}'."
                )

            if rigid_group_schema:
                item_id = (row.get("item_id") or "").strip()
                if not item_id:
                    raise RuntimeError(f"Placements CSV row {row_number}: missing item_id.")

                mode = (row.get("mode") or "").strip() or "rigid_group"
                if mode != "rigid_group":
                    raise RuntimeError(
                        f"Placements CSV row {row_number}: unsupported rigid-group mode '{mode}'."
                    )

                source_count = _parse_int(row, "source_count", row_number)
                source_tags = _parse_source_tags(row, "source_tags", row_number)
                if source_count != len(source_tags):
                    raise RuntimeError(
                        f"Placements CSV row {row_number}: source_count={source_count} does not "
                        f"match source_tags size {len(source_tags)}."
                    )

                placements.append(
                    PlacementRecord(
                        row_number=row_number,
                        item_id=item_id,
                        mode="rigid_group",
                        solid_tag=None,
                        copy_index=_parse_optional_int(row, "copy_index", 0, row_number),
                        source_count=source_count,
                        source_tags=source_tags,
                        dx=_parse_float(row, "dx", row_number),
                        dy=_parse_float(row, "dy", row_number),
                        dz=_parse_float(row, "dz", row_number),
                        x=_parse_float(row, "x", row_number),
                        y=_parse_float(row, "y", row_number),
                        z=_parse_float(row, "z", row_number),
                        rot=rot,
                        planar_angle_deg=_parse_optional_float(
                            row,
                            "planar_angle_deg",
                            0.0,
                            row_number,
                        ),
                        bbox_minx=_parse_float(row, "bbox_minx", row_number),
                        bbox_miny=_parse_float(row, "bbox_miny", row_number),
                        bbox_minz=_parse_float(row, "bbox_minz", row_number),
                        bbox_maxx=_parse_float(row, "bbox_maxx", row_number),
                        bbox_maxy=_parse_float(row, "bbox_maxy", row_number),
                        bbox_maxz=_parse_float(row, "bbox_maxz", row_number),
                    )
                )
                continue

            part_id = (row.get("part_id") or "").strip()
            if not part_id:
                raise RuntimeError(f"Placements CSV row {row_number}: missing part_id.")

            solid_tag = _parse_int(row, "solid_tag", row_number)
            placements.append(
                PlacementRecord(
                    row_number=row_number,
                    item_id=part_id,
                    mode="solid",
                    solid_tag=solid_tag,
                    copy_index=0,
                    source_count=1,
                    source_tags=(solid_tag,),
                    dx=_parse_float(row, "dx", row_number),
                    dy=_parse_float(row, "dy", row_number),
                    dz=_parse_float(row, "dz", row_number),
                    x=_parse_float(row, "x", row_number),
                    y=_parse_float(row, "y", row_number),
                    z=_parse_float(row, "z", row_number),
                    rot=rot,
                    planar_angle_deg=0.0,
                    bbox_minx=_parse_float(row, "bbox_minx", row_number),
                    bbox_miny=_parse_float(row, "bbox_miny", row_number),
                    bbox_minz=_parse_float(row, "bbox_minz", row_number),
                    bbox_maxx=_parse_float(row, "bbox_maxx", row_number),
                    bbox_maxy=_parse_float(row, "bbox_maxy", row_number),
                    bbox_maxz=_parse_float(row, "bbox_maxz", row_number),
                )
            )

    if not placements:
        raise RuntimeError(f"No placements found in CSV: {path}")
    return placements


def build_permutation_affine_matrix(rotation_label: str) -> list[float]:
    rotation = orientation_to_rigid_rotation(rotation_label)
    matrix4 = (
        rotation.matrix[0][0],
        rotation.matrix[0][1],
        rotation.matrix[0][2],
        0.0,
        rotation.matrix[1][0],
        rotation.matrix[1][1],
        rotation.matrix[1][2],
        0.0,
        rotation.matrix[2][0],
        rotation.matrix[2][1],
        rotation.matrix[2][2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )
    return list(matrix4)


def export_arranged_step(
    input_step: Path,
    placements_csv: Path,
    output_step: Path,
    *,
    scale: float = 1.0,
    units_mode: StepUnitsMode = "packed",
    packing_mode: PackingMode | Literal["rigid_group"] = "solids",
    input_steps: list[Path] | tuple[Path, ...] | None = None,
    item_scales: list[float] | tuple[float, ...] | None = None,
    logger: Any | None = None,
) -> None:
    input_step = Path(input_step)
    placements_csv = Path(placements_csv)
    output_step = Path(output_step)

    if not input_step.exists():
        raise FileNotFoundError(f"STEP file not found: {input_step}")
    if scale <= 0:
        raise RuntimeError(f"Scale must be positive, got {scale}.")
    if units_mode not in ("packed", "source"):
        raise RuntimeError(f"Unsupported STEP units mode: {units_mode}")

    normalized_mode = _normalize_packing_mode(packing_mode)
    placements = load_placements_csv(placements_csv)
    ensure_directory(output_step.parent)

    try:
        _log_info(logger, "Exporting arranged STEP...")
        _log_info(logger, "Loaded %d placements from CSV", len(placements))

        if normalized_mode == "solids":
            _export_arranged_step_solids(
                input_step=input_step,
                placements=placements,
                output_step=output_step,
                scale=scale,
                units_mode=units_mode,
                logger=logger,
            )
            return

        if normalized_mode == "multi_root_shapes":
            _export_arranged_step_multi_root_shapes(
                input_steps=tuple(Path(path) for path in (input_steps or ())),
                item_scales=tuple(float(value) for value in (item_scales or ())),
                placements=placements,
                output_step=output_step,
                units_mode=units_mode,
                logger=logger,
            )
            return

        _export_arranged_step_single_root_shape(
            input_step=input_step,
            placements=placements,
            output_step=output_step,
            scale=scale,
            units_mode=units_mode,
            logger=logger,
        )
    except Exception:
        output_step.unlink(missing_ok=True)
        raise


def export_packed_scene(
    placements: list[Placement],
    output_step: Path,
    *,
    logger: Any | None = None,
) -> str:
    output_step = Path(output_step)
    ensure_directory(output_step.parent)
    if not placements:
        raise RuntimeError("No placed items are available for STEP export.")

    try:
        ocp = _load_ocp_modules()
        transformed_shapes: list[Any] = []
        for index, placement in enumerate(placements, start=1):
            source_path_text = placement.part.source_path
            if not source_path_text:
                raise RuntimeError(f"Placement {placement.part_id} has no source STEP path.")
            source_path = Path(source_path_text)
            if not source_path.exists():
                raise FileNotFoundError(f"STEP file not found for placement export: {source_path}")
            root_shape = _read_root_shape(input_step=source_path, ocp=ocp)
            transformed_shapes.append(
                _transform_root_shape_for_placement(
                    ocp=ocp,
                    root_shape=root_shape,
                    placement=_placement_record_from_placement(index, placement),
                    scale=1.0,
                    units_mode="packed",
                    logger=logger,
                )
            )
        combined_shape = _combine_shapes_into_compound(ocp=ocp, shapes=transformed_shapes)
        _write_root_shape(ocp=ocp, shape=combined_shape, output_step=output_step)
        _log_info(logger, "Wrote packed STEP scene using transformed source models to %s", output_step)
        return "source_models"
    except Exception as exc:
        _log_warning(logger, "Falling back to box proxy STEP export: %s", exc)
        _export_box_proxy_scene(placements=placements, output_step=output_step)
        _log_info(logger, "Wrote packed STEP scene using box proxies to %s", output_step)
        return "box_proxies"


def _export_arranged_step_solids(
    *,
    input_step: Path,
    placements: list[PlacementRecord],
    output_step: Path,
    scale: float,
    units_mode: StepUnitsMode,
    logger: Any | None,
) -> None:
    try:
        import gmsh  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "gmsh is not installed. Install dependencies with 'python -m pip install -e .'"
        ) from exc

    initialized = False
    try:
        initialize_gmsh(gmsh)
        initialized = True
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.clear()
        gmsh.model.add("arranged_step")

        imported = gmsh.model.occ.importShapes(
            str(input_step),
            highestDimOnly=True,
            format="step",
        )
        gmsh.model.occ.synchronize()

        solids = sorted((dim, tag) for dim, tag in imported if dim == 3)
        if not solids:
            solids = sorted(gmsh.model.getEntities(3), key=lambda item: item[1])
        if not solids:
            raise RuntimeError(f"No solids found in STEP file: {input_step}")

        _log_info(logger, "Loaded %d solids from source STEP", len(solids))
        _export_solids(
            gmsh=gmsh,
            placements=placements,
            solids=solids,
            scale=scale,
            units_mode=units_mode,
            logger=logger,
        )

        gmsh.model.occ.remove(solids, recursive=True)
        gmsh.model.occ.synchronize()
        gmsh.write(str(output_step))
        _log_info(logger, "Wrote arranged STEP to %s", output_step)
    finally:
        if initialized:
            try:
                gmsh.finalize()
            except Exception:
                pass


def _export_arranged_step_single_root_shape(
    *,
    input_step: Path,
    placements: list[PlacementRecord],
    output_step: Path,
    scale: float,
    units_mode: StepUnitsMode,
    logger: Any | None,
) -> None:
    ocp = _load_ocp_modules()
    rigid_group_placements = _resolve_single_root_shape_placements(placements)
    root_shape = _read_root_shape(input_step=input_step, ocp=ocp)
    transformed_shapes = [
        _transform_root_shape_for_placement(
            ocp=ocp,
            root_shape=root_shape,
            placement=placement,
            scale=scale,
            units_mode=units_mode,
            logger=logger,
        )
        for placement in rigid_group_placements
    ]

    output_shape = (
        transformed_shapes[0]
        if len(transformed_shapes) == 1
        else _combine_shapes_into_compound(ocp=ocp, shapes=transformed_shapes)
    )
    _write_root_shape(ocp=ocp, shape=output_shape, output_step=output_step)
    if len(transformed_shapes) == 1:
        _log_info(
            logger,
            "Wrote arranged STEP as one transformed root shape to %s",
            output_step,
        )
    else:
        _log_info(
            logger,
            "Wrote arranged STEP as %d transformed root-shape copies to %s",
            len(transformed_shapes),
            output_step,
        )


def _export_arranged_step_multi_root_shapes(
    *,
    input_steps: tuple[Path, ...],
    item_scales: tuple[float, ...],
    placements: list[PlacementRecord],
    output_step: Path,
    units_mode: StepUnitsMode,
    logger: Any | None,
) -> None:
    if not input_steps:
        raise RuntimeError("Multi-root-shape export requires input_steps.")
    if len(placements) != len(input_steps):
        raise RuntimeError(
            f"Multi-root-shape export expects {len(input_steps)} placements, got {len(placements)}."
        )

    resolved_item_scales = item_scales or tuple(1.0 for _ in input_steps)
    if len(resolved_item_scales) != len(input_steps):
        raise RuntimeError(
            "Multi-root-shape export requires one scale value per input STEP file."
        )

    ocp = _load_ocp_modules()
    mapped = _map_multi_root_placements_to_inputs(
        placements=placements,
        input_steps=input_steps,
        item_scales=resolved_item_scales,
    )
    transformed_shapes: list[Any] = []
    for placement, input_step, item_scale in mapped:
        root_shape = _read_root_shape(input_step=input_step, ocp=ocp)
        transformed_shapes.append(
            _transform_root_shape_for_placement(
                ocp=ocp,
                root_shape=root_shape,
                placement=placement,
                scale=item_scale,
                units_mode=units_mode,
                logger=logger,
            )
        )

    combined_shape = _combine_shapes_into_compound(ocp=ocp, shapes=transformed_shapes)
    _write_root_shape(ocp=ocp, shape=combined_shape, output_step=output_step)
    _log_info(
        logger,
        "Wrote arranged STEP from %d transformed root shapes to %s",
        len(transformed_shapes),
        output_step,
    )


def _export_solids(
    *,
    gmsh: Any,
    placements: list[PlacementRecord],
    solids: list[tuple[int, int]],
    scale: float,
    units_mode: StepUnitsMode,
    logger: Any | None,
) -> None:
    solid_placements = [placement for placement in placements if placement.mode == "solid"]
    if len(solid_placements) != len(placements):
        raise RuntimeError("Solid export expects only solid placement rows.")
    if len(solids) != len(solid_placements):
        _log_warning(
            logger,
            "Placement count (%d) does not match source solid count (%d).",
            len(solid_placements),
            len(solids),
        )

    mapped = _map_placements_to_solids(placements=solid_placements, solids=solids, logger=logger)
    for placement, source_dim_tag in mapped:
        rotation = _resolve_rigid_rotation(placement.rot, logger=logger)
        copied_solid = _copy_single_solid(gmsh=gmsh, source_dim_tag=source_dim_tag, placement=placement)
        _scale_if_needed(gmsh=gmsh, copied_solids=[copied_solid], scale=scale, units_mode=units_mode)
        _apply_gmsh_rigid_rotation(
            gmsh=gmsh,
            dimtags=[copied_solid],
            rotation=rotation,
        )

        bbox = gmsh.model.occ.getBoundingBox(copied_solid[0], copied_solid[1])
        target_min = _target_bbox_min(placement=placement, scale=scale, units_mode=units_mode)
        delta = (
            target_min[0] - bbox[0],
            target_min[1] - bbox[1],
            target_min[2] - bbox[2],
        )
        gmsh.model.occ.translate([copied_solid], delta[0], delta[1], delta[2])


def _transform_root_shape_for_placement(
    *,
    ocp: _OcpModules,
    root_shape: Any,
    placement: PlacementRecord,
    scale: float,
    units_mode: StepUnitsMode,
    logger: Any | None,
) -> Any:
    transformed_shape = root_shape
    if units_mode == "packed" and abs(scale - 1.0) > EPS:
        transformed_shape = _transform_shape(
            ocp=ocp,
            shape=transformed_shape,
            trsf=_build_scale_trsf(ocp=ocp, scale=scale),
        )

    rotation = _resolve_rigid_rotation(placement.rot, logger=logger)
    transformed_shape = _transform_shape(
        ocp=ocp,
        shape=transformed_shape,
        trsf=_build_rotation_trsf(ocp=ocp, rotation=rotation),
    )
    if abs(placement.planar_angle_deg) > EPS:
        transformed_shape = _transform_shape(
            ocp=ocp,
            shape=transformed_shape,
            trsf=_build_planar_rotation_trsf(
                ocp=ocp,
                angle_deg=placement.planar_angle_deg,
            ),
        )

    rotated_bbox = _shape_bbox(ocp=ocp, shape=transformed_shape)
    target_min = _target_bbox_min(
        placement=placement,
        scale=scale,
        units_mode=units_mode,
    )
    delta = (
        target_min[0] - rotated_bbox[0],
        target_min[1] - rotated_bbox[1],
        target_min[2] - rotated_bbox[2],
    )
    return _transform_shape(
        ocp=ocp,
        shape=transformed_shape,
        trsf=_build_translation_trsf(ocp=ocp, delta=delta),
    )


def _resolve_rigid_rotation(rotation_label: str, *, logger: Any | None) -> RigidRotation:
    rotation = orientation_to_rigid_rotation(rotation_label)
    _log_info(
        logger,
        "Using rigid rotation %s steps=%s matrix=%s orthonormal=yes det=%.6f",
        rotation.label,
        list(rotation.steps),
        rotation.matrix,
        rotation.determinant,
    )
    return rotation


def _apply_gmsh_rigid_rotation(
    *,
    gmsh: Any,
    dimtags: list[tuple[int, int]],
    rotation: RigidRotation,
) -> None:
    for axis, quarter_turns in rotation.steps:
        axis_vector = _axis_vector(axis)
        gmsh.model.occ.rotate(
            dimtags,
            0.0,
            0.0,
            0.0,
            axis_vector[0],
            axis_vector[1],
            axis_vector[2],
            float(quarter_turns) * (math.pi / 2.0),
        )


def _axis_vector(axis: str) -> tuple[float, float, float]:
    if axis == "x":
        return (1.0, 0.0, 0.0)
    if axis == "y":
        return (0.0, 1.0, 0.0)
    if axis == "z":
        return (0.0, 0.0, 1.0)
    raise ValueError(f"Unsupported rotation axis: {axis}")


def _copy_single_solid(
    *,
    gmsh: Any,
    source_dim_tag: tuple[int, int],
    placement: PlacementRecord,
) -> tuple[int, int]:
    copied = gmsh.model.occ.copy([source_dim_tag])
    copied_solids = [(dim, tag) for dim, tag in copied if dim == 3]
    if len(copied_solids) != 1:
        raise RuntimeError(
            f"Failed to copy solid for placement row {placement.row_number} ({placement.part_id})."
        )
    return copied_solids[0]


def _scale_if_needed(
    *,
    gmsh: Any,
    copied_solids: list[tuple[int, int]],
    scale: float,
    units_mode: StepUnitsMode,
) -> None:
    if units_mode == "packed" and abs(scale - 1.0) > EPS:
        gmsh.model.occ.dilate(copied_solids, 0.0, 0.0, 0.0, scale, scale, scale)


def _map_placements_to_solids(
    *,
    placements: list[PlacementRecord],
    solids: list[tuple[int, int]],
    logger: Any | None,
) -> list[tuple[PlacementRecord, tuple[int, int]]]:
    solids_by_tag = {tag: (dim, tag) for dim, tag in solids}
    part_id_to_solid = {
        f"part_{index:03d}": (dim, tag)
        for index, (dim, tag) in enumerate(solids, start=1)
    }
    mapped: list[tuple[PlacementRecord, tuple[int, int]]] = []
    used_tags: set[int] = set()
    used_fallback = False

    for index, placement in enumerate(placements):
        if placement.solid_tag is None:
            raise RuntimeError(
                f"Solid export row {placement.row_number} ({placement.part_id}) is missing solid_tag."
            )

        match = None
        direct_match = solids_by_tag.get(placement.solid_tag)
        if direct_match is not None and direct_match[1] not in used_tags:
            match = direct_match
        else:
            part_match = part_id_to_solid.get(placement.part_id)
            if part_match is not None and part_match[1] not in used_tags:
                match = part_match
                used_fallback = True
            elif index < len(solids) and solids[index][1] not in used_tags:
                match = solids[index]
                used_fallback = True

        if match is None:
            raise RuntimeError(
                "Could not map placement row "
                f"{placement.row_number} (part_id={placement.part_id}, solid_tag={placement.solid_tag}) "
                "to a source solid."
            )
        if match[1] in used_tags:
            raise RuntimeError(
                "Placement mapping produced a duplicate source solid for "
                f"row {placement.row_number} (part_id={placement.part_id})."
            )

        used_tags.add(match[1])
        mapped.append((placement, match))

    if used_fallback:
        _log_info(logger, "Mapped placements to solids by solid_tag with fallback by part_id/order")
    else:
        _log_info(logger, "Mapped placements to solids by solid_tag")

    return mapped


def _resolve_single_root_shape_placements(
    placements: list[PlacementRecord],
) -> list[PlacementRecord]:
    rigid_group_placements = [placement for placement in placements if placement.mode == "rigid_group"]
    if len(rigid_group_placements) != len(placements):
        raise RuntimeError("Single-root-shape export expects only rigid-group placement rows.")
    if not rigid_group_placements:
        raise RuntimeError("Single-root-shape export expects at least one rigid-group placement row.")
    return rigid_group_placements


def _map_multi_root_placements_to_inputs(
    *,
    placements: list[PlacementRecord],
    input_steps: tuple[Path, ...],
    item_scales: tuple[float, ...],
) -> list[tuple[PlacementRecord, Path, float]]:
    rigid_group_placements = [placement for placement in placements if placement.mode == "rigid_group"]
    if len(rigid_group_placements) != len(placements):
        raise RuntimeError("Multi-root-shape export expects only rigid-group placement rows.")

    path_by_item_id = {
        f"file_{index:03d}": (Path(input_path), float(item_scales[index - 1]))
        for index, input_path in enumerate(input_steps, start=1)
    }
    mapped: list[tuple[PlacementRecord, Path, float]] = []
    used_item_ids: set[str] = set()
    for index, placement in enumerate(rigid_group_placements):
        match = path_by_item_id.get(placement.item_id)
        if match is None:
            if index >= len(input_steps):
                raise RuntimeError(
                    f"Could not map rigid-group placement row {placement.row_number} ({placement.item_id}) to an input STEP file."
                )
            match = (Path(input_steps[index]), float(item_scales[index]))
        if placement.item_id in used_item_ids:
            raise RuntimeError(
                f"Duplicate rigid-group placement item_id encountered: {placement.item_id}."
            )
        used_item_ids.add(placement.item_id)
        mapped.append((placement, match[0], match[1]))
    return mapped


def _load_ocp_modules() -> _OcpModules:
    try:
        from OCP.BRep import BRep_Builder
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.Bnd import Bnd_Box
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
        from OCP.TopoDS import TopoDS_Compound
        from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    except ImportError as exc:
        raise RuntimeError(
            "cadquery-ocp is required for single-root-shape STEP export. "
            "Install dependencies with 'python -m pip install -e .'"
        ) from exc

    return _OcpModules(
        BRep_Builder=BRep_Builder,
        BRepBndLib=BRepBndLib,
        BRepBuilderAPI_Transform=BRepBuilderAPI_Transform,
        Bnd_Box=Bnd_Box,
        IFSelect_RetDone=IFSelect_RetDone,
        STEPControl_AsIs=STEPControl_AsIs,
        STEPControl_Reader=STEPControl_Reader,
        STEPControl_Writer=STEPControl_Writer,
        TopoDS_Compound=TopoDS_Compound,
        gp_Ax1=gp_Ax1,
        gp_Dir=gp_Dir,
        gp_Pnt=gp_Pnt,
        gp_Trsf=gp_Trsf,
        gp_Vec=gp_Vec,
    )


def _read_root_shape(*, input_step: Path, ocp: _OcpModules) -> Any:
    reader = ocp.STEPControl_Reader()
    status = reader.ReadFile(str(input_step))
    if status != ocp.IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file for root-shape export: {input_step}")

    reader.TransferRoots()
    root_shape = reader.OneShape()
    transferred_shape_count = _reader_shape_count(reader)
    transferred_shapes = (
        _collect_transferred_shapes(reader, transferred_shape_count)
        if transferred_shape_count > 0
        else []
    )
    if transferred_shape_count > 1 and transferred_shapes:
        root_shape = _combine_shapes_into_compound(ocp=ocp, shapes=transferred_shapes)
    elif _shape_is_null(root_shape) and transferred_shapes:
        root_shape = _combine_shapes_into_compound(ocp=ocp, shapes=transferred_shapes)
    if _shape_is_null(root_shape):
        raise RuntimeError(f"STEP file did not produce a root shape: {input_step}")
    return root_shape


def _reader_shape_count(reader: Any) -> int:
    method = getattr(reader, "NbShapes", None)
    if callable(method):
        try:
            value = int(method())
        except Exception:
            return 0
        return max(0, value)
    return 0


def _collect_transferred_shapes(reader: Any, shape_count: int) -> list[Any]:
    shape_method = getattr(reader, "Shape", None)
    if not callable(shape_method):
        return []

    for start_index in (1, 0):
        shapes: list[Any] = []
        for offset in range(shape_count):
            try:
                shape = shape_method(start_index + offset)
            except Exception:
                shapes = []
                break
            if _shape_is_null(shape):
                continue
            shapes.append(shape)
        if shapes:
            return shapes
    return []


def _combine_shapes_into_compound(*, ocp: _OcpModules, shapes: list[Any]) -> Any:
    if len(shapes) == 1:
        return shapes[0]

    compound = ocp.TopoDS_Compound()
    builder = ocp.BRep_Builder()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    if _shape_is_null(compound):
        raise RuntimeError("Failed to combine STEP roots into one compound shape.")
    return compound


def _shape_bbox(*, ocp: _OcpModules, shape: Any) -> tuple[float, float, float, float, float, float]:
    box = ocp.Bnd_Box()
    _add_shape_to_bbox(ocp=ocp, shape=shape, box=box)

    if hasattr(box, "Get"):
        bounds = box.Get()
        if isinstance(bounds, (tuple, list)) and len(bounds) == 6:
            return tuple(float(value) for value in bounds)

    raise RuntimeError("Unable to read bounding box from transformed root shape.")


def _add_shape_to_bbox(*, ocp: _OcpModules, shape: Any, box: Any) -> None:
    for method_name in ("AddOptimal_s", "Add_s", "Add"):
        method = getattr(ocp.BRepBndLib, method_name, None)
        if method is None:
            continue
        for args in ((shape, box), (shape, box, False), (shape, box, False, False)):
            try:
                method(*args)
                return
            except TypeError:
                continue
    raise RuntimeError("OCP BRepBndLib does not expose a compatible Add method.")


def _build_scale_trsf(*, ocp: _OcpModules, scale: float) -> Any:
    trsf = ocp.gp_Trsf()
    trsf.SetScale(ocp.gp_Pnt(0.0, 0.0, 0.0), float(scale))
    return trsf


def _build_rotation_trsf(*, ocp: _OcpModules, rotation: RigidRotation) -> Any:
    trsf = ocp.gp_Trsf()
    for axis, quarter_turns in rotation.steps:
        step_trsf = ocp.gp_Trsf()
        axis_vector = _axis_vector(axis)
        step_trsf.SetRotation(
            ocp.gp_Ax1(
                ocp.gp_Pnt(0.0, 0.0, 0.0),
                ocp.gp_Dir(axis_vector[0], axis_vector[1], axis_vector[2]),
            ),
            float(quarter_turns) * (math.pi / 2.0),
        )
        trsf.PreMultiply(step_trsf)
    return trsf


def _build_planar_rotation_trsf(*, ocp: _OcpModules, angle_deg: float) -> Any:
    trsf = ocp.gp_Trsf()
    trsf.SetRotation(
        ocp.gp_Ax1(
            ocp.gp_Pnt(0.0, 0.0, 0.0),
            ocp.gp_Dir(0.0, 0.0, 1.0),
        ),
        math.radians(float(angle_deg)),
    )
    return trsf


def _build_translation_trsf(*, ocp: _OcpModules, delta: tuple[float, float, float]) -> Any:
    trsf = ocp.gp_Trsf()
    trsf.SetTranslation(ocp.gp_Vec(float(delta[0]), float(delta[1]), float(delta[2])))
    return trsf


def _transform_shape(*, ocp: _OcpModules, shape: Any, trsf: Any) -> Any:
    try:
        builder = ocp.BRepBuilderAPI_Transform(shape, trsf, True)
    except TypeError:
        builder = ocp.BRepBuilderAPI_Transform(shape, trsf)

    if hasattr(builder, "Build"):
        builder.Build()
    transformed_shape = builder.Shape()
    if _shape_is_null(transformed_shape):
        raise RuntimeError("Failed to transform the root shape.")
    return transformed_shape


def _write_root_shape(*, ocp: _OcpModules, shape: Any, output_step: Path) -> None:
    writer = ocp.STEPControl_Writer()
    transfer_status = writer.Transfer(shape, ocp.STEPControl_AsIs)
    if transfer_status not in (None, ocp.IFSelect_RetDone):
        raise RuntimeError("Failed to transfer the transformed root shape into STEP writer.")

    write_status = writer.Write(str(output_step))
    if write_status not in (None, ocp.IFSelect_RetDone):
        raise RuntimeError(f"Failed to write arranged STEP to {output_step}")


def _shape_is_null(shape: Any) -> bool:
    if shape is None:
        return True
    is_null = getattr(shape, "IsNull", None)
    if callable(is_null):
        return bool(is_null())
    return False


def _normalize_packing_mode(packing_mode: str) -> PackingMode:
    if packing_mode == "solids":
        return "solids"
    if packing_mode == "flat_assembly_footprint":
        return "flat_assembly_footprint"
    if packing_mode in {"single_root_shape", "rigid_group"}:
        return "single_root_shape"
    if packing_mode == "multi_root_shapes":
        return "multi_root_shapes"
    raise RuntimeError(f"Unsupported packing mode: {packing_mode}")


def _placement_record_from_placement(index: int, placement: Placement) -> PlacementRecord:
    source_tags = tuple(solid.tag for solid in placement.part.source_solids) or (index,)
    return PlacementRecord(
        row_number=index,
        item_id=placement.part_id,
        mode="rigid_group",
        solid_tag=None,
        copy_index=placement.copy_index,
        source_count=len(source_tags),
        source_tags=source_tags,
        dx=placement.dx,
        dy=placement.dy,
        dz=placement.dz,
        x=placement.x,
        y=placement.y,
        z=placement.z,
        rot=placement.rot,
        planar_angle_deg=placement.planar_angle_deg,
        bbox_minx=placement.bbox_min[0],
        bbox_miny=placement.bbox_min[1],
        bbox_minz=placement.bbox_min[2],
        bbox_maxx=placement.bbox_max[0],
        bbox_maxy=placement.bbox_max[1],
        bbox_maxz=placement.bbox_max[2],
    )


def _export_box_proxy_scene(*, placements: list[Placement], output_step: Path) -> None:
    try:
        import gmsh  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "gmsh is required for box-proxy STEP export. Install dependencies with 'python -m pip install -e .'"
        ) from exc

    initialized = False
    try:
        initialize_gmsh(gmsh)
        initialized = True
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.clear()
        gmsh.model.add("packed_scene")
        for placement in placements:
            gmsh.model.occ.addBox(
                float(placement.x),
                float(placement.y),
                float(placement.z),
                float(placement.dx),
                float(placement.dy),
                float(placement.dz),
            )
        gmsh.model.occ.synchronize()
        gmsh.write(str(output_step))
    finally:
        if initialized:
            try:
                gmsh.finalize()
            except Exception:
                pass


def _target_bbox_min(
    *,
    placement: PlacementRecord,
    scale: float,
    units_mode: StepUnitsMode,
) -> tuple[float, float, float]:
    if units_mode == "packed":
        return (placement.x, placement.y, placement.z)
    return (
        placement.x / scale,
        placement.y / scale,
        placement.z / scale,
    )


def _parse_float(row: dict[str, str | None], column: str, row_number: int) -> float:
    value = (row.get(column) or "").strip()
    if not value:
        raise RuntimeError(f"Placements CSV row {row_number}: missing value for '{column}'.")
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Placements CSV row {row_number}: invalid number in '{column}': {value!r}."
        ) from exc


def _parse_optional_float(
    row: dict[str, str | None],
    column: str,
    default: float,
    row_number: int,
) -> float:
    value = (row.get(column) or "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Placements CSV row {row_number}: invalid number in '{column}': {value!r}."
        ) from exc


def _parse_int(row: dict[str, str | None], column: str, row_number: int) -> int:
    value = (row.get(column) or "").strip()
    if not value:
        raise RuntimeError(f"Placements CSV row {row_number}: missing value for '{column}'.")
    try:
        parsed = int(value)
    except ValueError:
        try:
            parsed_float = float(value)
        except ValueError as exc:
            raise RuntimeError(
                f"Placements CSV row {row_number}: invalid integer in '{column}': {value!r}."
            ) from exc
        if not parsed_float.is_integer():
            raise RuntimeError(
                f"Placements CSV row {row_number}: invalid integer in '{column}': {value!r}."
            )
        parsed = int(parsed_float)
    return parsed


def _parse_optional_int(
    row: dict[str, str | None],
    column: str,
    default: int,
    row_number: int,
) -> int:
    value = (row.get(column) or "").strip()
    if not value:
        return default
    return _parse_int(row, column, row_number)


def _parse_source_tags(
    row: dict[str, str | None],
    column: str,
    row_number: int,
) -> tuple[int, ...]:
    value = (row.get(column) or "").strip()
    if not value:
        raise RuntimeError(f"Placements CSV row {row_number}: missing value for '{column}'.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Placements CSV row {row_number}: invalid JSON in '{column}': {value!r}."
        ) from exc
    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError(
            f"Placements CSV row {row_number}: '{column}' must be a non-empty JSON array."
        )

    tags: list[int] = []
    for item in parsed:
        if isinstance(item, bool):
            raise RuntimeError(
                f"Placements CSV row {row_number}: '{column}' contains invalid tag value {item!r}."
            )
        if isinstance(item, int):
            tags.append(item)
            continue
        if isinstance(item, float) and item.is_integer():
            tags.append(int(item))
            continue
        raise RuntimeError(
            f"Placements CSV row {row_number}: '{column}' contains invalid tag value {item!r}."
        )
    return tuple(tags)


def _is_rigid_group_schema(fieldnames: list[str]) -> bool:
    fieldname_set = set(fieldnames)
    return (
        "item_id" in fieldname_set
        or "source_tags" in fieldname_set
        or "source_count" in fieldname_set
        or "mode" in fieldname_set
    )


def _normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    return value.lstrip("\ufeff").strip()


def _log_info(logger: Any | None, message: str, *args: Any) -> None:
    if logger is not None:
        logger.info(message, *args)


def _log_warning(logger: Any | None, message: str, *args: Any) -> None:
    if logger is not None:
        logger.warning(message, *args)
