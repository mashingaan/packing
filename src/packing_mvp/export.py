from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence

from packing_mvp.packer import PackOutcome
from packing_mvp.utils import Placement, ceil_mm


def write_placements_csv(placements: list[Placement], path: Path) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        placement_modes = {placement.part.mode for placement in placements}
        if not placements or placement_modes == {"solid"}:
            _write_solid_placements_csv(writer, placements)
            return
        if placement_modes == {"rigid_group"}:
            _write_rigid_group_placements_csv(writer, placements)
            return
        raise RuntimeError("Mixed placement modes are not supported in placements.csv output.")


def build_success_result(
    input_paths: Sequence[Path],
    constraints: dict[str, Any],
    outcome: PackOutcome,
    units: dict[str, Any],
) -> dict[str, Any]:
    packed_volume = sum(
        placement.dx * placement.dy * placement.dz for placement in outcome.placements
    )
    packed_count = len(outcome.placements)
    unpacked_count = 0
    return {
        "status": "ok",
        "input": _build_input_payload(input_paths),
        "constraints": constraints,
        "treat_input_as_single_item": _treat_input_as_single_item(constraints),
        "flat_only": _flat_only(constraints),
        "copies": _copies(constraints),
        "planar_rotation_step_deg": _planar_rotation_step_deg(constraints),
        "packing_mode": _packing_mode(constraints),
        "does_not_fit": False,
        "limit_exceeded": None,
        "max_package_dims_mm": _max_package_dims(constraints),
        "recommended_dims_mm": {
            "L": outcome.recommended_dims[0],
            "W": outcome.recommended_dims[1],
            "H": outcome.recommended_dims[2],
        },
        "used_extents_mm": {
            "maxX": ceil_mm(outcome.used_extents[0]),
            "maxY": ceil_mm(outcome.used_extents[1]),
            "maxZ": ceil_mm(outcome.used_extents[2]),
        },
        "packed_count": packed_count,
        "unpacked_count": unpacked_count,
        "stats": {
            "n_parts": packed_count,
            "packed": packed_count,
            "unpacked": unpacked_count,
            "fill_ratio_bbox": round(outcome.fill_ratio_bbox, 6),
            "packed_volume_mm3": round(packed_volume, 3),
        },
        "units": {
            "scale": units["scale"],
            "manual_scale": units.get("manual_scale"),
            "auto_scale_applied": units["auto_scale_applied"],
            "auto_scale_factor": units.get("auto_scale_factor"),
        },
    }


def build_failure_result(
    input_paths: Sequence[Path],
    constraints: dict[str, Any],
    message: str,
    units: dict[str, Any] | None = None,
    n_parts: int = 0,
    *,
    does_not_fit: bool = False,
    packed_count: int = 0,
    unpacked_count: int | None = None,
    used_extents: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    units = units or {
        "scale": None,
        "manual_scale": None,
        "auto_scale_applied": False,
        "auto_scale_factor": None,
    }
    resolved_packed_count = max(0, int(packed_count))
    resolved_unpacked_count = (
        max(0, int(unpacked_count))
        if unpacked_count is not None
        else max(0, int(n_parts) - resolved_packed_count)
    )
    limit_exceeded = _limit_exceeded_payload(
        constraints=constraints,
        used_extents=used_extents,
    )
    return {
        "status": "failed",
        "error": message,
        "input": _build_input_payload(input_paths),
        "constraints": constraints,
        "treat_input_as_single_item": _treat_input_as_single_item(constraints),
        "flat_only": _flat_only(constraints),
        "copies": _copies(constraints),
        "planar_rotation_step_deg": _planar_rotation_step_deg(constraints),
        "packing_mode": _packing_mode(constraints),
        "does_not_fit": bool(does_not_fit),
        "limit_exceeded": limit_exceeded,
        "max_package_dims_mm": _max_package_dims(constraints),
        "recommended_dims_mm": {
            "L": None,
            "W": None,
            "H": None,
        },
        "used_extents_mm": _used_extents_payload(used_extents),
        "packed_count": resolved_packed_count,
        "unpacked_count": resolved_unpacked_count,
        "stats": {
            "n_parts": n_parts,
            "packed": resolved_packed_count,
            "unpacked": resolved_unpacked_count,
            "fill_ratio_bbox": 0.0,
        },
        "units": {
            "scale": units.get("scale"),
            "manual_scale": units.get("manual_scale"),
            "auto_scale_applied": units.get("auto_scale_applied", False),
            "auto_scale_factor": units.get("auto_scale_factor"),
        },
    }


def write_result_json(data: dict[str, Any], path: Path) -> None:
    path = Path(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _write_solid_placements_csv(writer: csv.writer, placements: list[Placement]) -> None:
    writer.writerow(
        [
            "part_id",
            "solid_tag",
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
        ]
    )
    for placement in placements:
        writer.writerow(
            [
                placement.part_id,
                placement.solid_tag,
                _fmt(placement.dx),
                _fmt(placement.dy),
                _fmt(placement.dz),
                _fmt(placement.x),
                _fmt(placement.y),
                _fmt(placement.z),
                placement.rot,
                _fmt(placement.bbox_min[0]),
                _fmt(placement.bbox_min[1]),
                _fmt(placement.bbox_min[2]),
                _fmt(placement.bbox_max[0]),
                _fmt(placement.bbox_max[1]),
                _fmt(placement.bbox_max[2]),
            ]
        )


def _write_rigid_group_placements_csv(writer: csv.writer, placements: list[Placement]) -> None:
    writer.writerow(
        [
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
        ]
    )
    for placement in placements:
        source_tags = [solid.tag for solid in placement.part.source_solids]
        writer.writerow(
            [
                placement.part_id,
                placement.part.mode,
                placement.copy_index,
                len(source_tags),
                json.dumps(source_tags),
                _fmt(placement.dx),
                _fmt(placement.dy),
                _fmt(placement.dz),
                _fmt(placement.x),
                _fmt(placement.y),
                _fmt(placement.z),
                placement.rot,
                _fmt(placement.planar_angle_deg),
                _fmt(placement.bbox_min[0]),
                _fmt(placement.bbox_min[1]),
                _fmt(placement.bbox_min[2]),
                _fmt(placement.bbox_max[0]),
                _fmt(placement.bbox_max[1]),
                _fmt(placement.bbox_max[2]),
            ]
        )


def _build_input_payload(input_paths: Sequence[Path]) -> dict[str, Any]:
    normalized_paths = [str(Path(path)) for path in input_paths]
    payload: dict[str, Any] = {
        "files": normalized_paths,
        "count": len(normalized_paths),
    }
    if normalized_paths:
        payload["file"] = normalized_paths[0]
    return payload


def _treat_input_as_single_item(constraints: dict[str, Any]) -> bool:
    return bool(constraints.get("treat_input_as_single_item"))


def _flat_only(constraints: dict[str, Any]) -> bool:
    return bool(constraints.get("flat_only"))


def _packing_mode(constraints: dict[str, Any]) -> str:
    mode = str(constraints.get("packing_mode") or "")
    if mode == "solids":
        return "solids"
    if mode == "multi_root_shapes":
        return "multi_root_shapes"
    if mode in {"single_root_shape", "rigid_group"}:
        return "single_root_shape"
    return "single_root_shape" if _treat_input_as_single_item(constraints) else "solids"


def _max_package_dims(constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        "L": constraints.get("maxL"),
        "W": constraints.get("maxW"),
        "H": constraints.get("maxH"),
    }


def _copies(constraints: dict[str, Any]) -> int:
    value = constraints.get("copies")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    return 1


def _planar_rotation_step_deg(constraints: dict[str, Any]) -> float:
    value = constraints.get("planar_rotation_step_deg")
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _used_extents_payload(
    used_extents: tuple[float, float, float] | None,
) -> dict[str, Any]:
    if used_extents is None:
        return {
            "maxX": None,
            "maxY": None,
            "maxZ": None,
        }
    return {
        "maxX": ceil_mm(used_extents[0]),
        "maxY": ceil_mm(used_extents[1]),
        "maxZ": ceil_mm(used_extents[2]),
    }


def _limit_exceeded_payload(
    *,
    constraints: dict[str, Any],
    used_extents: tuple[float, float, float] | None,
) -> dict[str, Any] | None:
    if used_extents is None:
        return None

    gap_value = constraints.get("gap")
    gap = float(gap_value) if isinstance(gap_value, (int, float)) else 0.0
    actuals = {
        "L": ceil_mm(used_extents[0] + gap),
        "W": ceil_mm(used_extents[1] + gap),
        "H": ceil_mm(used_extents[2] + gap),
    }
    maximums = {
        "L": constraints.get("maxL"),
        "W": constraints.get("maxW"),
        "H": constraints.get("maxH"),
    }

    for axis in ("L", "W", "H"):
        maximum = maximums[axis]
        if not isinstance(maximum, (int, float)):
            continue
        allowed = ceil_mm(float(maximum))
        actual = actuals[axis]
        if actual > allowed:
            return {
                "axis": axis,
                "max": allowed,
                "actual": actual,
                "excess": actual - allowed,
            }
    return None
