from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from packing_mvp.catalog import CatalogItem
from packing_mvp.packer import DoesNotFitError, PackOutcome, TruckPackOutcome
from packing_mvp.utils import Part, Placement, ceil_mm


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


def sort_placements_for_display(placements: Iterable[Placement]) -> list[Placement]:
    return sorted(
        placements,
        key=lambda placement: (
            round(placement.x, 6),
            round(placement.y, 6),
            round(placement.z, 6),
            placement.part.display_name or placement.part.part_id,
            placement.part.source_part_id or placement.part.part_id,
            placement.part_id,
        ),
    )


def build_success_result(
    input_paths: Sequence[Path],
    constraints: dict[str, Any],
    outcome: PackOutcome,
    units: dict[str, Any],
) -> dict[str, Any]:
    ordered_placements = sort_placements_for_display(outcome.placements)
    fit_verdict = validate_constraints(outcome, constraints)
    if not fit_verdict["fits"]:
        raise DoesNotFitError(format_constraint_failure_message(fit_verdict))
    packed_volume = sum(placement.dx * placement.dy * placement.dz for placement in outcome.placements)
    packed_count = len(outcome.placements)
    return {
        "status": "ok",
        "success": True,
        "input": _build_input_payload(input_paths),
        "truck": _truck_payload(constraints),
        "constraints": constraints,
        "fits": True,
        "does_not_fit": False,
        "violations": [],
        "limit_exceeded": None,
        "placed_items": [
            _placement_payload(placement, place_no=index)
            for index, placement in enumerate(ordered_placements, start=1)
        ],
        "unplaced_items": [],
        "recommended_dims_mm": {
            "L": outcome.recommended_dims[0],
            "W": outcome.recommended_dims[1],
            "H": outcome.recommended_dims[2],
        },
        "used_extents_mm": fit_verdict["used_extents_mm"],
        "packed_count": packed_count,
        "unpacked_count": 0,
        "fill_ratio": round(outcome.fill_ratio_bbox, 6),
        "stats": {
            "n_parts": packed_count,
            "packed": packed_count,
            "unpacked": 0,
            "fill_ratio_bbox": round(outcome.fill_ratio_bbox, 6),
            "packed_volume_mm3": round(packed_volume, 3),
        },
        "units": {
            "scale": units.get("scale"),
            "manual_scale": units.get("manual_scale"),
            "auto_scale_applied": units.get("auto_scale_applied", False),
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
    fit_verdict = validate_constraints(used_extents, constraints)
    return {
        "status": "failed",
        "success": False,
        "error": message,
        "input": _build_input_payload(input_paths),
        "truck": _truck_payload(constraints),
        "constraints": constraints,
        "fits": False,
        "does_not_fit": bool(does_not_fit or resolved_unpacked_count > 0 or fit_verdict["does_not_fit"]),
        "violations": fit_verdict["violations"],
        "limit_exceeded": fit_verdict["limit_exceeded"],
        "placed_items": [],
        "unplaced_items": [],
        "recommended_dims_mm": {
            "L": fit_verdict["used_extents_mm"]["L"],
            "W": fit_verdict["used_extents_mm"]["W"],
            "H": fit_verdict["used_extents_mm"]["H"],
        },
        "used_extents_mm": fit_verdict["used_extents_mm"],
        "packed_count": resolved_packed_count,
        "unpacked_count": resolved_unpacked_count,
        "fill_ratio": 0.0,
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


def build_truck_packing_result(
    *,
    input_paths: Sequence[Path],
    catalog_items: Sequence[CatalogItem],
    constraints: dict[str, Any],
    outcome: TruckPackOutcome | None,
    units: dict[str, Any] | None = None,
    export_mode: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    units = units or {
        "scale": None,
        "manual_scale": None,
        "auto_scale_applied": False,
        "auto_scale_factor": None,
    }
    used_extents = outcome.used_extents if outcome is not None else None
    fit_verdict = validate_constraints(used_extents, constraints)
    ordered_placements = sort_placements_for_display(outcome.placements if outcome else [])
    placed_items = [
        _placement_payload(placement, place_no=index)
        for index, placement in enumerate(ordered_placements, start=1)
    ]
    unplaced_items = _unplaced_payload(outcome.unplaced_parts if outcome else [], catalog_items)
    packed_count = len(placed_items)
    unpacked_count = sum(item["quantity"] for item in unplaced_items)
    total_items = packed_count + unpacked_count
    success = error is None and unpacked_count == 0 and fit_verdict["fits"]
    error_text = error
    if error_text is None and not success:
        if fit_verdict["violations"]:
            error_text = format_constraint_failure_message(fit_verdict)
        elif unplaced_items:
            error_text = _format_unplaced_summary(unplaced_items)
        else:
            error_text = "Расчёт укладки не вернул корректный результат."

    return {
        "status": "ok" if success else "failed",
        "success": success,
        "error": None if success else error_text,
        "input": _build_input_payload(input_paths),
        "truck": _truck_payload(constraints),
        "constraints": constraints,
        "catalog": [item.to_dict() for item in catalog_items],
        "packing_mode": "truck_loading_v2",
        "fits": success,
        "does_not_fit": not success,
        "violations": fit_verdict["violations"],
        "limit_exceeded": fit_verdict["limit_exceeded"],
        "placed_items": placed_items,
        "unplaced_items": unplaced_items,
        "recommended_dims_mm": {
            "L": fit_verdict["used_extents_mm"]["L"],
            "W": fit_verdict["used_extents_mm"]["W"],
            "H": fit_verdict["used_extents_mm"]["H"],
        },
        "used_extents_mm": fit_verdict["used_extents_mm"],
        "packed_count": packed_count,
        "unpacked_count": unpacked_count,
        "fill_ratio": round(outcome.fill_ratio_truck, 6) if outcome is not None else 0.0,
        "export_mode": export_mode,
        "stats": {
            "n_parts": total_items,
            "packed": packed_count,
            "unpacked": unpacked_count,
            "fill_ratio_bbox": round(outcome.fill_ratio_bbox, 6) if outcome is not None else 0.0,
            "fill_ratio_truck": round(outcome.fill_ratio_truck, 6) if outcome is not None else 0.0,
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


def validate_constraints(
    result: PackOutcome | TruckPackOutcome | tuple[float, float, float] | None,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    used_extents = _coerce_used_extents(result)
    actual_extents = _actual_used_extents_payload(used_extents=used_extents)
    violations = _collect_constraint_violations(constraints=constraints, actual_extents=actual_extents)
    return {
        "fits": used_extents is not None and not violations,
        "does_not_fit": bool(violations),
        "violations": violations,
        "limit_exceeded": violations[0] if violations else None,
        "used_extents_mm": _used_extents_payload(used_extents=used_extents, actual_extents=actual_extents),
    }


def format_constraint_failure_message(fit_verdict: dict[str, Any]) -> str:
    violations = list(fit_verdict.get("violations") or [])
    if not violations:
        return "Превышены ограничения кузова."
    if len(violations) == 1:
        return _format_constraint_violation_message(violations[0])
    return "; ".join(_format_constraint_violation_message(violation) for violation in violations)


def _format_constraint_violation_message(violation: dict[str, Any]) -> str:
    axis_names = {
        "L": "длине",
        "W": "ширине",
        "H": "высоте",
    }
    axis = str(violation.get("axis") or "")
    axis_name = axis_names.get(axis, axis)
    actual = int(violation.get("actual") or 0)
    maximum = int(violation.get("max") or 0)
    excess = int(violation.get("excess") or (actual - maximum))
    return f"Превышение по {axis_name} кузова: {actual} мм при пределе {maximum} мм, запас превышен на {excess} мм."


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


def _truck_payload(constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        "length_mm": constraints.get("maxL"),
        "width_mm": constraints.get("maxW"),
        "height_mm": constraints.get("maxH"),
        "gap_mm": constraints.get("gap"),
    }


def _placement_payload(placement: Placement, *, place_no: int | None = None) -> dict[str, Any]:
    metadata = dict(placement.part.metadata)
    return {
        "place_no": place_no,
        "instance_id": placement.part_id,
        "item_id": placement.part.source_part_id or placement.part_id,
        "name": placement.part.display_name or placement.part_id,
        "source_path": placement.part.source_path,
        "source_kind": metadata.get("source_kind") or ("manual" if not placement.part.source_path else "step"),
        "copy_index": placement.copy_index,
        "rotation": placement.rot,
        "position_mm": {
            "x": round(placement.x, 3),
            "y": round(placement.y, 3),
            "z": round(placement.z, 3),
        },
        "dimensions_mm": {
            "L": round(placement.dx, 3),
            "W": round(placement.dy, 3),
            "H": round(placement.dz, 3),
        },
    }


def _unplaced_payload(unplaced_parts: Iterable[Part], catalog_items: Sequence[CatalogItem]) -> list[dict[str, Any]]:
    by_item_id = {item.item_id: item for item in catalog_items}
    counts = Counter(part.source_part_id or part.part_id for part in unplaced_parts)
    payload: list[dict[str, Any]] = []
    for item_id, quantity in sorted(counts.items()):
        item = by_item_id.get(item_id)
        payload.append(
            {
                "item_id": item_id,
                "name": (item.display_name if item is not None else item_id),
                "source_path": (item.source_path if item is not None else None),
                "quantity": int(quantity),
            }
        )
    return payload


def _format_unplaced_summary(unplaced_items: Sequence[dict[str, Any]]) -> str:
    if not unplaced_items:
        return "Не все грузовые места помещаются в кузов."
    summary = ", ".join(f"{item['name']} x{item['quantity']}" for item in unplaced_items)
    return f"Не все грузовые места помещаются в кузов. Неразмещённые: {summary}."


def _coerce_used_extents(
    result: PackOutcome | TruckPackOutcome | tuple[float, float, float] | None,
) -> tuple[float, float, float] | None:
    if result is None:
        return None
    if isinstance(result, (PackOutcome, TruckPackOutcome)):
        return result.used_extents
    return result


def _used_extents_payload(
    *,
    used_extents: tuple[float, float, float] | None,
    actual_extents: dict[str, int | None],
) -> dict[str, Any]:
    if used_extents is None:
        return {
            "L": actual_extents["L"],
            "W": actual_extents["W"],
            "H": actual_extents["H"],
            "maxX": None,
            "maxY": None,
            "maxZ": None,
        }
    return {
        "L": actual_extents["L"],
        "W": actual_extents["W"],
        "H": actual_extents["H"],
        "maxX": ceil_mm(used_extents[0]),
        "maxY": ceil_mm(used_extents[1]),
        "maxZ": ceil_mm(used_extents[2]),
    }


def _actual_used_extents_payload(
    *,
    used_extents: tuple[float, float, float] | None,
) -> dict[str, int | None]:
    if used_extents is None:
        return {
            "L": None,
            "W": None,
            "H": None,
        }
    return {
        "L": ceil_mm(used_extents[0]),
        "W": ceil_mm(used_extents[1]),
        "H": ceil_mm(used_extents[2]),
    }


def _collect_constraint_violations(
    *,
    constraints: dict[str, Any],
    actual_extents: dict[str, int | None],
) -> list[dict[str, int | str]]:
    maximums = {
        "L": constraints.get("maxL"),
        "W": constraints.get("maxW"),
        "H": constraints.get("maxH"),
    }
    violations: list[dict[str, int | str]] = []
    for axis in ("L", "W", "H"):
        actual = actual_extents[axis]
        if actual is None:
            continue
        maximum = maximums[axis]
        if not isinstance(maximum, (int, float)):
            continue
        allowed = ceil_mm(float(maximum))
        if actual > allowed:
            violations.append(
                {
                    "axis": axis,
                    "max": allowed,
                    "actual": actual,
                    "excess": actual - allowed,
                }
            )
    return violations
