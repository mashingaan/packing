from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from packing_mvp.utils import (
    EPS,
    Part,
    Placement,
    canonical_rigid_assembly_orientation,
    canonical_flat_orientation,
    ceil_mm,
    compute_used_extents,
    dims_from_bbox,
    filter_orientations_flat_only,
    rigid_group_rotated_bbox,
    sample_planar_angles,
)


class PackingError(RuntimeError):
    """Raised when packing cannot be completed."""


class DoesNotFitError(PackingError):
    """Raised when the requested container constraints cannot contain the parts."""


@dataclass(frozen=True)
class PackOutcome:
    placements: list[Placement]
    used_extents: tuple[float, float, float]
    recommended_dims: tuple[int, int, int]
    container_dims: tuple[int, int, int]
    search_length: int
    fill_ratio_bbox: float


@dataclass(frozen=True)
class OrientationCandidate:
    rot: str
    dims: tuple[float, float, float]
    planar_angle_deg: float = 0.0


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
    if not parts:
        raise PackingError("No parts available for packing.")
    if max_w <= 0 or max_h <= 0:
        raise PackingError("Container width and height must be positive.")
    if gap < 0:
        raise PackingError("Gap must be non-negative.")

    _validate_cross_section(
        parts,
        max_w=max_w,
        max_h=max_h,
        gap=gap,
        flat_only=flat_only,
        planar_rotation_step_deg=planar_rotation_step_deg,
    )

    if max_l is not None:
        search_length = ceil_mm(max_l)
        placements = _attempt_pack(
            parts=parts,
            container_l=search_length,
            container_w=max_w,
            container_h=max_h,
            gap=gap,
            seed=seed,
            flat_only=flat_only,
            planar_rotation_step_deg=planar_rotation_step_deg,
            logger=logger,
        )
        if placements is None:
            raise DoesNotFitError(
                "Packing failed: rigid items do not fit into "
                f"L={search_length}, W={ceil_mm(max_w)}, H={ceil_mm(max_h)}."
            )
        if logger:
            logger.info("Packing succeeded with fixed length L=%s", search_length)
    else:
        lower, upper = _search_bounds(
            parts,
            gap,
            flat_only=flat_only,
            planar_rotation_step_deg=planar_rotation_step_deg,
        )
        if logger:
            logger.info("Searching minimal working length in range [%s, %s]", lower, upper)

        cache: dict[int, list[Placement] | None] = {}

        def attempt(length: int) -> list[Placement] | None:
            if length not in cache:
                cache[length] = _attempt_pack(
                    parts=parts,
                    container_l=length,
                    container_w=max_w,
                    container_h=max_h,
                    gap=gap,
                    seed=seed,
                    flat_only=flat_only,
                    planar_rotation_step_deg=planar_rotation_step_deg,
                    logger=logger,
                )
            return cache[length]

        high_result = attempt(upper)
        if high_result is None:
            raise DoesNotFitError(
                "Packing failed even with a generous search length. "
                "Check width/height limits, gap, or extracted part dimensions."
            )

        best_length = upper
        best_placements = high_result
        low = lower
        high = upper

        while low < high:
            mid = (low + high) // 2
            if logger:
                logger.debug("Trying candidate length L=%s", mid)
            current = attempt(mid)
            if current is None:
                low = mid + 1
            else:
                high = mid
                best_length = mid
                best_placements = current

        if best_placements is None or best_length != low:
            final = attempt(low)
            if final is None:
                raise PackingError("Binary search ended without a feasible packing.")
            best_placements = final
            best_length = low

        search_length = best_length
        placements = best_placements
        if logger:
            logger.info("Minimal working length found: L=%s", search_length)

    used_extents = compute_used_extents(placements)
    recommended_dims = (
        ceil_mm(used_extents[0] + gap),
        ceil_mm(used_extents[1] + gap),
        ceil_mm(used_extents[2] + gap),
    )
    container_dims = (
        search_length,
        ceil_mm(max_w),
        ceil_mm(max_h),
    )
    used_volume = sum(placement.dx * placement.dy * placement.dz for placement in placements)
    bbox_volume = max(
        (recommended_dims[0] * recommended_dims[1] * recommended_dims[2]),
        EPS,
    )
    fill_ratio = used_volume / bbox_volume

    return PackOutcome(
        placements=placements,
        used_extents=used_extents,
        recommended_dims=recommended_dims,
        container_dims=container_dims,
        search_length=search_length,
        fill_ratio_bbox=fill_ratio,
    )


def _validate_cross_section(
    parts: list[Part],
    max_w: float,
    max_h: float,
    gap: float,
    flat_only: bool,
    planar_rotation_step_deg: float,
) -> None:
    free_w = max_w - 2.0 * gap
    free_h = max_h - 2.0 * gap
    if free_w <= 0 or free_h <= 0:
        raise PackingError("Gap leaves no usable width/height inside the container.")

    for part in parts:
        orientations = _resolve_allowed_orientations(
            part,
            flat_only=flat_only,
            planar_rotation_step_deg=planar_rotation_step_deg,
        )
        if not any(
            candidate.dims[1] <= free_w + EPS and candidate.dims[2] <= free_h + EPS
            for candidate in orientations
        ):
            dims_str = ", ".join(f"{value:.3f}" for value in part.dims)
            if flat_only:
                raise DoesNotFitError(
                    f"Part {part.part_id} with dims ({dims_str}) does not fit container width/height in allowed flat orientations."
                )
            raise DoesNotFitError(
                f"Part {part.part_id} with dims ({dims_str}) does not fit container width/height in any rotation."
            )


def _search_bounds(
    parts: list[Part],
    gap: float,
    *,
    flat_only: bool,
    planar_rotation_step_deg: float,
) -> tuple[int, int]:
    min_lengths: list[float] = []
    max_lengths: list[float] = []
    for part in parts:
        orientations = _resolve_allowed_orientations(
            part,
            flat_only=flat_only,
            planar_rotation_step_deg=planar_rotation_step_deg,
        )
        min_lengths.append(min(candidate.dims[0] for candidate in orientations))
        max_lengths.append(max(candidate.dims[0] for candidate in orientations))

    lower = ceil_mm(max(min_lengths) + 2.0 * gap)
    upper = ceil_mm(sum(max_lengths) + gap * (len(parts) + 1))
    return lower, max(lower, upper)


def _attempt_pack(
    parts: list[Part],
    container_l: float,
    container_w: float,
    container_h: float,
    gap: float,
    seed: int,
    flat_only: bool,
    planar_rotation_step_deg: float,
    logger: Any | None = None,
) -> list[Placement] | None:
    ordered_parts = _ordered_parts(parts, seed)
    placements: list[Placement] = []
    candidate_points: list[tuple[float, float, float]] = [(gap, gap, gap)]
    current_extents = (0.0, 0.0, 0.0)

    for part in ordered_parts:
        orientations = _resolve_allowed_orientations(
            part,
            flat_only=flat_only,
            planar_rotation_step_deg=planar_rotation_step_deg,
        )
        best_choice: tuple[
            tuple[float, float, float, float, float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            str,
            float,
        ] | None = None

        for point in candidate_points:
            for candidate in orientations:
                rot_label = candidate.rot
                rotated_dims = candidate.dims
                if not _fits_in_container(
                    point=point,
                    dims=rotated_dims,
                    container_l=container_l,
                    container_w=container_w,
                    container_h=container_h,
                    gap=gap,
                ):
                    continue
                if _overlaps_with_gap(point=point, dims=rotated_dims, placements=placements, gap=gap):
                    continue

                score = _placement_score(
                    point=point,
                    dims=rotated_dims,
                    current_extents=current_extents,
                )
                if best_choice is None or score < best_choice[0]:
                    best_choice = (
                        score,
                        point,
                        rotated_dims,
                        rot_label,
                        candidate.planar_angle_deg,
                    )

        if best_choice is None:
            if logger:
                logger.debug("Could not place %s inside L=%s", part.part_id, container_l)
            return None

        _, point, rotated_dims, rot_label, planar_angle_deg = best_choice
        placement = Placement(
            part=part,
            x=point[0],
            y=point[1],
            z=point[2],
            dims=rotated_dims,
            rot=rot_label,
            planar_angle_deg=planar_angle_deg,
        )
        placements.append(placement)
        current_extents = (
            max(current_extents[0], placement.x + placement.dx),
            max(current_extents[1], placement.y + placement.dy),
            max(current_extents[2], placement.z + placement.dz),
        )
        if logger:
            logger.debug(
                "Placed %s at (%.3f, %.3f, %.3f) dims=(%.3f, %.3f, %.3f) rot=%s angle=%.3f",
                placement.part_id,
                placement.x,
                placement.y,
                placement.z,
                placement.dx,
                placement.dy,
                placement.dz,
                placement.rot,
                placement.planar_angle_deg,
            )

        candidate_points.extend(
            [
                (placement.x + placement.dx + gap, placement.y, placement.z),
                (placement.x, placement.y + placement.dy + gap, placement.z),
                (placement.x, placement.y, placement.z + placement.dz + gap),
            ]
        )
        candidate_points = _prune_candidate_points(
            candidate_points,
            placements=placements,
            container_l=container_l,
            container_w=container_w,
            container_h=container_h,
            gap=gap,
        )

    return placements


def _resolve_allowed_orientations(
    part: Part,
    *,
    flat_only: bool,
    planar_rotation_step_deg: float,
) -> list[OrientationCandidate]:
    if (
        part.mode == "rigid_group"
        and flat_only
        and part.orientation_policy == "assembly_axes_parallel_to_box_axes"
    ):
        base_rot, _ = canonical_rigid_assembly_orientation(part.dims)
        return [
            OrientationCandidate(
                rot=base_rot,
                dims=dims_from_bbox(rigid_group_rotated_bbox(part.source_solids, base_rot)),
                planar_angle_deg=0.0,
            )
        ]

    if part.mode == "rigid_group" and flat_only:
        base_rot, _ = canonical_flat_orientation(part.dims)
        return [
            OrientationCandidate(
                rot=base_rot,
                dims=dims_from_bbox(
                    rigid_group_rotated_bbox(
                        part.source_solids,
                        base_rot,
                        planar_angle_deg,
                    )
                ),
                planar_angle_deg=planar_angle_deg,
            )
            for planar_angle_deg in sample_planar_angles(planar_rotation_step_deg)
        ]

    orientations = filter_orientations_flat_only(part.dims, flat_only=flat_only)
    if not orientations and flat_only:
        raise PackingError(f"No flat orientations available for part {part.part_id} with flat_only enabled")
    return [
        OrientationCandidate(
            rot=label,
            dims=rotated_dims,
            planar_angle_deg=0.0,
        )
        for label, rotated_dims in orientations
    ]


def _ordered_parts(parts: list[Part], seed: int) -> list[Part]:
    rng = random.Random(seed)
    decorated = [(part, rng.random()) for part in parts]
    decorated.sort(
        key=lambda item: (
            -item[0].volume,
            -max(item[0].dims),
            -sum(item[0].dims),
            item[1],
            item[0].part_id,
        )
    )
    return [item[0] for item in decorated]


def _fits_in_container(
    point: tuple[float, float, float],
    dims: tuple[float, float, float],
    container_l: float,
    container_w: float,
    container_h: float,
    gap: float,
) -> bool:
    x, y, z = point
    dx, dy, dz = dims
    return (
        x >= gap - EPS
        and y >= gap - EPS
        and z >= gap - EPS
        and x + dx <= container_l - gap + EPS
        and y + dy <= container_w - gap + EPS
        and z + dz <= container_h - gap + EPS
    )


def _overlaps_with_gap(
    point: tuple[float, float, float],
    dims: tuple[float, float, float],
    placements: list[Placement],
    gap: float,
) -> bool:
    x, y, z = point
    dx, dy, dz = dims
    for other in placements:
        separated = (
            x + dx + gap <= other.x + EPS
            or other.x + other.dx + gap <= x + EPS
            or y + dy + gap <= other.y + EPS
            or other.y + other.dy + gap <= y + EPS
            or z + dz + gap <= other.z + EPS
            or other.z + other.dz + gap <= z + EPS
        )
        if not separated:
            return True
    return False


def _placement_score(
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
        round(max_x, 6),
        round(max_z, 6),
        round(max_y, 6),
        round(z, 6),
        round(y, 6),
        round(x, 6),
        round(dx * dy * dz, 6),
    )


def _prune_candidate_points(
    points: list[tuple[float, float, float]],
    placements: list[Placement],
    container_l: float,
    container_w: float,
    container_h: float,
    gap: float,
) -> list[tuple[float, float, float]]:
    filtered: list[tuple[float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()

    for point in sorted(points, key=lambda item: (item[0], item[2], item[1])):
        if (
            point[0] > container_l - gap + EPS
            or point[1] > container_w - gap + EPS
            or point[2] > container_h - gap + EPS
        ):
            continue

        key = tuple(int(round(axis * 1000.0)) for axis in point)
        if key in seen:
            continue
        if _point_is_blocked(point, placements, gap):
            continue
        seen.add(key)
        filtered.append(point)

    pruned: list[tuple[float, float, float]] = []
    for point in filtered:
        dominated = False
        for kept in pruned:
            if (
                kept[0] <= point[0] + EPS
                and kept[1] <= point[1] + EPS
                and kept[2] <= point[2] + EPS
            ):
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
    placements: list[Placement],
    gap: float,
) -> bool:
    x, y, z = point
    for placement in placements:
        if (
            placement.x - EPS < x < placement.x + placement.dx + gap - EPS
            and placement.y - EPS < y < placement.y + placement.dy + gap - EPS
            and placement.z - EPS < z < placement.z + placement.dz + gap - EPS
        ):
            return True
    return False
