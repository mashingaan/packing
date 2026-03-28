from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packing_mvp.utils import EPS, Part, Placement, ceil_mm, compute_used_extents, z_rotation_orientations


class PackingError(RuntimeError):
    """Raised when packing cannot be completed."""


class DoesNotFitError(PackingError):
    """Raised when the requested truck cannot contain all items."""


@dataclass(frozen=True)
class PackOutcome:
    placements: list[Placement]
    used_extents: tuple[float, float, float]
    recommended_dims: tuple[int, int, int]
    container_dims: tuple[int, int, int]
    search_length: int
    fill_ratio_bbox: float


@dataclass(frozen=True)
class TruckPackOutcome:
    placements: list[Placement]
    unplaced_parts: list[Part]
    used_extents: tuple[float, float, float]
    container_dims: tuple[int, int, int]
    fill_ratio_bbox: float
    fill_ratio_truck: float

    @property
    def success(self) -> bool:
        return not self.unplaced_parts


@dataclass(frozen=True)
class OrientationCandidate:
    rot: str
    dims: tuple[float, float, float]
    planar_angle_deg: float = 0.0


def pack_items_in_truck(
    parts: list[Part],
    *,
    truck_l: float,
    truck_w: float,
    truck_h: float,
    gap: float,
    logger: Any | None = None,
) -> TruckPackOutcome:
    if not parts:
        raise PackingError("No items available for packing.")
    if truck_l <= 0 or truck_w <= 0 or truck_h <= 0:
        raise PackingError("Truck dimensions must be positive.")
    if gap < 0:
        raise PackingError("Gap must be non-negative.")

    _validate_items(parts, truck_w=truck_w, truck_h=truck_h)

    placements: list[Placement] = []
    unplaced_parts: list[Part] = []
    candidate_points: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
    current_extents = (0.0, 0.0, 0.0)

    for part in _ordered_parts(parts):
        best_choice: tuple[
            tuple[float, float, float, float, float, float, float],
            tuple[float, float, float],
            OrientationCandidate,
        ] | None = None

        for point in candidate_points:
            for candidate in _resolve_allowed_orientations(part):
                if not _fits_in_container(
                    point=point,
                    dims=candidate.dims,
                    container_l=truck_l,
                    container_w=truck_w,
                    container_h=truck_h,
                ):
                    continue
                if _overlaps_with_gap(point=point, dims=candidate.dims, placements=placements, gap=gap):
                    continue

                score = _placement_score(point=point, dims=candidate.dims, current_extents=current_extents)
                if best_choice is None or score < best_choice[0]:
                    best_choice = (score, point, candidate)

        if best_choice is None:
            unplaced_parts.append(part)
            if logger:
                logger.info("No free slot found for %s (%s).", part.part_id, part.display_name)
            continue

        _, point, candidate = best_choice
        placement = Placement(
            part=part,
            x=point[0],
            y=point[1],
            z=point[2],
            dims=candidate.dims,
            rot=candidate.rot,
            planar_angle_deg=0.0,
        )
        placements.append(placement)
        current_extents = (
            max(current_extents[0], placement.x + placement.dx),
            max(current_extents[1], placement.y + placement.dy),
            max(current_extents[2], placement.z + placement.dz),
        )
        candidate_points.extend(
            [
                (placement.x + placement.dx + gap, placement.y, placement.z),
                (placement.x, placement.y + placement.dy + gap, placement.z),
                (placement.x, placement.y, placement.z + placement.dz),
            ]
        )
        candidate_points = _prune_candidate_points(
            candidate_points,
            placements=placements,
            container_l=truck_l,
            container_w=truck_w,
            container_h=truck_h,
            gap=gap,
        )
        if logger:
            logger.debug(
                "Placed %s at (%.1f, %.1f, %.1f) dims=(%.1f, %.1f, %.1f) rot=%s",
                placement.part_id,
                placement.x,
                placement.y,
                placement.z,
                placement.dx,
                placement.dy,
                placement.dz,
                placement.rot,
            )

    used_extents = compute_used_extents(placements)
    used_volume = sum(placement.dx * placement.dy * placement.dz for placement in placements)
    bbox_volume = max(used_extents[0] * used_extents[1] * used_extents[2], EPS)
    truck_volume = max(truck_l * truck_w * truck_h, EPS)
    return TruckPackOutcome(
        placements=placements,
        unplaced_parts=unplaced_parts,
        used_extents=used_extents,
        container_dims=(ceil_mm(truck_l), ceil_mm(truck_w), ceil_mm(truck_h)),
        fill_ratio_bbox=used_volume / bbox_volume,
        fill_ratio_truck=used_volume / truck_volume,
    )


def pack_parts(
    parts: list[Part],
    max_w: float,
    max_h: float,
    gap: float,
    max_l: float | None = None,
    seed: int = 42,
    flat_only: bool = False,
    planar_rotation_step_deg: float = 0.0,
    logger: Any | None = None,
) -> PackOutcome:
    del seed, flat_only, planar_rotation_step_deg

    if max_l is None:
        lower = ceil_mm(max(max(candidate.dims[0] for candidate in _resolve_allowed_orientations(part)) for part in parts))
        upper = ceil_mm(sum(max(candidate.dims[0] for candidate in _resolve_allowed_orientations(part)) for part in parts) + max(0.0, gap) * max(0, len(parts) - 1))
        if lower > upper:
            upper = lower

        best: TruckPackOutcome | None = None
        best_length = upper
        low = lower
        high = upper
        while low <= high:
            mid = (low + high) // 2
            current = pack_items_in_truck(
                parts,
                truck_l=float(mid),
                truck_w=max_w,
                truck_h=max_h,
                gap=gap,
                logger=logger,
            )
            if current.success:
                best = current
                best_length = mid
                high = mid - 1
            else:
                low = mid + 1

        if best is None:
            raise DoesNotFitError(_format_unplaced_message(parts))
        outcome = best
        search_length = best_length
    else:
        search_length = ceil_mm(max_l)
        outcome = pack_items_in_truck(
            parts,
            truck_l=max_l,
            truck_w=max_w,
            truck_h=max_h,
            gap=gap,
            logger=logger,
        )
        if outcome.unplaced_parts:
            raise DoesNotFitError(_format_unplaced_message(outcome.unplaced_parts))

    used_extents = outcome.used_extents
    recommended_dims = (
        ceil_mm(used_extents[0]),
        ceil_mm(used_extents[1]),
        ceil_mm(used_extents[2]),
    )
    return PackOutcome(
        placements=outcome.placements,
        used_extents=used_extents,
        recommended_dims=recommended_dims,
        container_dims=(search_length, ceil_mm(max_w), ceil_mm(max_h)),
        search_length=search_length,
        fill_ratio_bbox=outcome.fill_ratio_bbox,
    )


def _validate_items(parts: list[Part], *, truck_w: float, truck_h: float) -> None:
    for part in parts:
        orientations = _resolve_allowed_orientations(part)
        if not any(candidate.dims[1] <= truck_w + EPS and candidate.dims[2] <= truck_h + EPS for candidate in orientations):
            raise DoesNotFitError(
                f"Item {part.part_id} with dimensions {tuple(round(value, 3) for value in part.dims)} "
                "does not fit truck width/height in the allowed standing orientations."
            )


def _resolve_allowed_orientations(
    part: Part,
    *,
    flat_only: bool = False,
    planar_rotation_step_deg: float = 0.0,
) -> list[OrientationCandidate]:
    del flat_only, planar_rotation_step_deg
    return [
        OrientationCandidate(rot=label, dims=rotated_dims, planar_angle_deg=0.0)
        for label, rotated_dims in z_rotation_orientations(part.dims)
    ]


def _ordered_parts(parts: list[Part]) -> list[Part]:
    return sorted(
        parts,
        key=lambda part: (
            -(part.dims[0] * part.dims[1]),
            -part.volume,
            -part.dims[2],
            part.source_part_id or part.part_id,
            part.part_id,
        ),
    )


def _fits_in_container(
    *,
    point: tuple[float, float, float],
    dims: tuple[float, float, float],
    container_l: float,
    container_w: float,
    container_h: float,
) -> bool:
    x, y, z = point
    dx, dy, dz = dims
    return (
        x >= -EPS
        and y >= -EPS
        and z >= -EPS
        and x + dx <= container_l + EPS
        and y + dy <= container_w + EPS
        and z + dz <= container_h + EPS
    )


def _overlaps_with_gap(
    *,
    point: tuple[float, float, float],
    dims: tuple[float, float, float],
    placements: list[Placement],
    gap: float,
) -> bool:
    x, y, z = point
    dx, dy, dz = dims
    for other in placements:
        separated_x = x + dx + gap <= other.x + EPS or other.x + other.dx + gap <= x + EPS
        separated_y = y + dy + gap <= other.y + EPS or other.y + other.dy + gap <= y + EPS
        separated_z = z + dz <= other.z + EPS or other.z + other.dz <= z + EPS
        if not (separated_x or separated_y or separated_z):
            return True
    return False


def _placement_score(
    *,
    point: tuple[float, float, float],
    dims: tuple[float, float, float],
    current_extents: tuple[float, float, float],
) -> tuple[float, float, float, float, float, float, float]:
    x, y, z = point
    dx, dy, dz = dims
    max_x = max(current_extents[0], x + dx)
    max_y = max(current_extents[1], y + dy)
    max_z = max(current_extents[2], z + dz)
    return (
        round(z, 6),
        round(x, 6),
        round(y, 6),
        round(max_x, 6),
        round(max_z, 6),
        round(max_y, 6),
        round(-(dx * dy), 6),
    )


def _prune_candidate_points(
    points: list[tuple[float, float, float]],
    *,
    placements: list[Placement],
    container_l: float,
    container_w: float,
    container_h: float,
    gap: float,
) -> list[tuple[float, float, float]]:
    filtered: list[tuple[float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()

    for point in sorted(points, key=lambda item: (item[2], item[0], item[1])):
        if (
            point[0] > container_l + EPS
            or point[1] > container_w + EPS
            or point[2] > container_h + EPS
        ):
            continue
        key = tuple(int(round(axis * 1000.0)) for axis in point)
        if key in seen:
            continue
        if _point_is_blocked(point, placements=placements, gap=gap):
            continue
        seen.add(key)
        filtered.append(point)

    pruned: list[tuple[float, float, float]] = []
    for point in filtered:
        dominated = False
        for kept in pruned:
            if kept[0] <= point[0] + EPS and kept[1] <= point[1] + EPS and kept[2] <= point[2] + EPS:
                dominated = True
                break
        if not dominated:
            pruned = [
                kept
                for kept in pruned
                if not (
                    point[0] <= kept[0] + EPS
                    and point[1] <= kept[1] + EPS
                    and point[2] <= kept[2] + EPS
                )
            ]
            pruned.append(point)
    return pruned


def _point_is_blocked(
    point: tuple[float, float, float],
    *,
    placements: list[Placement],
    gap: float,
) -> bool:
    x, y, z = point
    for placement in placements:
        if (
            placement.x - EPS < x < placement.x + placement.dx + gap - EPS
            and placement.y - EPS < y < placement.y + placement.dy + gap - EPS
            and placement.z - EPS < z < placement.z + placement.dz - EPS
        ):
            return True
    return False


def _format_unplaced_message(parts: list[Part]) -> str:
    if not parts:
        return "Не все грузовые места помещаются в кузов."
    names = ", ".join(part.display_name or part.part_id for part in parts[:5])
    if len(parts) > 5:
        names += f", and {len(parts) - 5} more"
    return f"Не все грузовые места помещаются в кузов. Неразмещённые: {names}."
