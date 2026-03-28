from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from pathlib import Path
from typing import Any, Iterable, Literal

EPS = 1e-6

RotationStep = tuple[str, int]

_ROTATION_SPECS: tuple[
    tuple[str, tuple[int, int, int], tuple[RotationStep, ...]],
    ...,
] = (
    ("XYZ", (0, 1, 2), ()),
    ("XZY", (0, 2, 1), (("x", 1),)),
    ("YXZ", (1, 0, 2), (("z", -1),)),
    ("YZX", (1, 2, 0), (("x", -1), ("y", -1))),
    ("ZXY", (2, 0, 1), (("x", 1), ("z", 1))),
    ("ZYX", (2, 1, 0), (("y", 1),)),
)


@dataclass(frozen=True)
class RigidRotation:
    label: str
    order: tuple[int, int, int]
    steps: tuple[RotationStep, ...]
    matrix: tuple[tuple[float, float, float], ...]
    determinant: float


def _axis_rotation_matrix(axis: str, quarter_turns: int) -> tuple[tuple[float, float, float], ...]:
    normalized_turns = quarter_turns % 4
    if axis == "x":
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
            ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
            ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
        )
        return matrices[normalized_turns]
    if axis == "y":
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
            ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
            ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
        )
        return matrices[normalized_turns]
    if axis == "z":
        matrices = (
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
            ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        )
        return matrices[normalized_turns]
    raise ValueError(f"Unsupported rotation axis: {axis}")


def _matrix_multiply(
    left: tuple[tuple[float, float, float], ...],
    right: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(
            sum(left[row_index][k] * right[k][column_index] for k in range(3))
            for column_index in range(3)
        )
        for row_index in range(3)
    )


def _matrix_transpose(
    matrix: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(matrix[row_index][column_index] for row_index in range(3))
        for column_index in range(3)
    )


def rotation_matrix_determinant(matrix: tuple[tuple[float, float, float], ...]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def rotation_matrix_is_orthonormal(
    matrix: tuple[tuple[float, float, float], ...],
    *,
    tol: float = EPS,
) -> bool:
    transpose = _matrix_transpose(matrix)
    product = _matrix_multiply(transpose, matrix)
    identity = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    for row_index in range(3):
        for column_index in range(3):
            if abs(product[row_index][column_index] - identity[row_index][column_index]) > tol:
                return False
    return True


def _rotation_order_from_matrix(
    matrix: tuple[tuple[float, float, float], ...],
) -> tuple[int, int, int]:
    return tuple(
        max(range(3), key=lambda index: abs(matrix[row_index][index]))
        for row_index in range(3)
    )


def _compose_rotation_steps(
    steps: tuple[RotationStep, ...],
) -> tuple[tuple[float, float, float], ...]:
    matrix = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    for axis, quarter_turns in steps:
        matrix = _matrix_multiply(_axis_rotation_matrix(axis, quarter_turns), matrix)
    return matrix


def _build_rigid_rotation(
    label: str,
    order: tuple[int, int, int],
    steps: tuple[RotationStep, ...],
) -> RigidRotation:
    matrix = _compose_rotation_steps(steps)
    if not rotation_matrix_is_orthonormal(matrix):
        raise ValueError(f"Orientation {label} does not produce an orthonormal rotation matrix.")

    determinant = rotation_matrix_determinant(matrix)
    if abs(determinant - 1.0) > EPS:
        raise ValueError(
            f"Orientation {label} must be a proper rigid rotation with determinant +1, got {determinant:.6f}."
        )

    actual_order = _rotation_order_from_matrix(matrix)
    if actual_order != order:
        raise ValueError(
            f"Orientation {label} maps to bbox order {actual_order}, expected {order}."
        )

    return RigidRotation(
        label=label,
        order=order,
        steps=steps,
        matrix=matrix,
        determinant=determinant,
    )


ROTATIONS: tuple[RigidRotation, ...] = tuple(
    _build_rigid_rotation(label, order, steps)
    for label, order, steps in _ROTATION_SPECS
)
ROTATION_ORDERS: tuple[tuple[str, tuple[int, int, int]], ...] = tuple(
    (rotation.label, rotation.order)
    for rotation in ROTATIONS
)
ROTATION_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    rotation.label: rotation.matrix for rotation in ROTATIONS
}


BBox = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class SourceSolid:
    tag: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]

    @property
    def dims(self) -> tuple[float, float, float]:
        return dims_from_bounds(self.bbox_min, self.bbox_max)


@dataclass(frozen=True)
class Part:
    part_id: str
    solid_tag: int | None
    dims: tuple[float, float, float]
    volume: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    mode: Literal["solid", "rigid_group"] = "solid"
    orientation_policy: Literal[
        "default",
        "assembly_axes_parallel_to_box_axes",
        "flat_assembly_footprint",
    ] = "default"
    source_solids: tuple[SourceSolid, ...] = ()
    source_part_id: str | None = None
    copy_index: int = 0
    source_path: str | None = None
    display_name: str | None = None
    metadata: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"solid", "rigid_group"}:
            raise ValueError(f"Unsupported part mode: {self.mode}")
        if self.orientation_policy not in {
            "default",
            "assembly_axes_parallel_to_box_axes",
            "flat_assembly_footprint",
        }:
            raise ValueError(f"Unsupported orientation policy: {self.orientation_policy}")
        if self.copy_index < 0:
            raise ValueError("copy_index must be non-negative.")

        normalized_sources = tuple(self.source_solids)
        if not normalized_sources and self.solid_tag is not None:
            normalized_sources = (
                SourceSolid(
                    tag=self.solid_tag,
                    bbox_min=self.bbox_min,
                    bbox_max=self.bbox_max,
                ),
            )

        if self.mode == "solid" and len(normalized_sources) != 1:
            raise ValueError("Solid parts must reference exactly one source solid.")
        if self.mode == "rigid_group" and not normalized_sources:
            raise ValueError("Rigid-group parts must reference at least one source solid.")

        if self.solid_tag is None and normalized_sources:
            object.__setattr__(self, "solid_tag", normalized_sources[0].tag)
        object.__setattr__(self, "source_solids", normalized_sources)
        if self.source_part_id is None:
            object.__setattr__(self, "source_part_id", self.part_id)
        if self.display_name is None:
            object.__setattr__(self, "display_name", self.part_id)


@dataclass(frozen=True)
class Placement:
    part: Part
    x: float
    y: float
    z: float
    dims: tuple[float, float, float]
    rot: str
    planar_angle_deg: float = 0.0

    @property
    def dx(self) -> float:
        return self.dims[0]

    @property
    def dy(self) -> float:
        return self.dims[1]

    @property
    def dz(self) -> float:
        return self.dims[2]

    @property
    def part_id(self) -> str:
        return self.part.part_id

    @property
    def solid_tag(self) -> int:
        return -1 if self.part.solid_tag is None else self.part.solid_tag

    @property
    def copy_index(self) -> int:
        return self.part.copy_index

    @property
    def bbox_min(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def bbox_max(self) -> tuple[float, float, float]:
        return (self.x + self.dx, self.y + self.dy, self.z + self.dz)


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ceil_mm(value: float) -> int:
    return int(math.ceil(value - EPS))


def dims_from_bounds(
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        max(0.0, bbox_max[0] - bbox_min[0]),
        max(0.0, bbox_max[1] - bbox_min[1]),
        max(0.0, bbox_max[2] - bbox_min[2]),
    )


def dims_from_bbox(bbox: BBox) -> tuple[float, float, float]:
    return (
        max(0.0, bbox[3] - bbox[0]),
        max(0.0, bbox[4] - bbox[1]),
        max(0.0, bbox[5] - bbox[2]),
    )


def combine_bboxes(bboxes: Iterable[BBox]) -> BBox:
    iterator = iter(bboxes)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("At least one bounding box is required.") from exc

    min_x, min_y, min_z, max_x, max_y, max_z = first
    for bbox in iterator:
        min_x = min(min_x, bbox[0])
        min_y = min(min_y, bbox[1])
        min_z = min(min_z, bbox[2])
        max_x = max(max_x, bbox[3])
        max_y = max(max_y, bbox[4])
        max_z = max(max_z, bbox[5])
    return (min_x, min_y, min_z, max_x, max_y, max_z)


def unique_rotations(dims: tuple[float, float, float]) -> list[tuple[str, tuple[float, float, float]]]:
    seen: set[tuple[int, int, int]] = set()
    result: list[tuple[str, tuple[float, float, float]]] = []
    for label, order in ROTATION_ORDERS:
        rotated = (dims[order[0]], dims[order[1]], dims[order[2]])
        key = tuple(int(round(axis * 1000.0)) for axis in rotated)
        if key in seen:
            continue
        seen.add(key)
        result.append((label, rotated))
    return result


def orientation_to_rigid_rotation(label: str) -> RigidRotation:
    for rotation in ROTATIONS:
        if rotation.label == label:
            return rotation
    raise ValueError(f"Unsupported rotation label: {label}")


def rotation_matrix(label: str) -> tuple[tuple[float, float, float], ...]:
    return orientation_to_rigid_rotation(label).matrix


def filter_orientations_flat_only(
    dims: tuple[float, float, float],
    flat_only: bool,
) -> list[tuple[str, tuple[float, float, float]]]:
    orientations = unique_rotations(dims)
    if not flat_only:
        return orientations

    min_dim = min(dims)
    return [
        (label, rotated_dims)
        for label, rotated_dims in orientations
        if abs(rotated_dims[2] - min_dim) < EPS
    ]


def z_rotation_orientations(
    dims: tuple[float, float, float],
) -> list[tuple[str, tuple[float, float, float]]]:
    orientations: list[tuple[str, tuple[float, float, float]]] = [("XYZ", dims)]
    rotated = (dims[1], dims[0], dims[2])
    if any(abs(rotated[index] - dims[index]) > EPS for index in range(3)):
        orientations.append(("YXZ", rotated))
    return orientations


def canonical_flat_orientation(
    dims: tuple[float, float, float],
) -> tuple[str, tuple[float, float, float]]:
    orientations = filter_orientations_flat_only(dims, flat_only=True)
    if not orientations:
        raise ValueError(f"No flat orientation is available for dims={dims!r}.")
    return orientations[0]


def canonical_rigid_assembly_orientation(
    dims: tuple[float, float, float],
) -> tuple[str, tuple[float, float, float]]:
    target_dims = tuple(sorted((float(axis) for axis in dims), reverse=True))
    for label, rotated_dims in unique_rotations(dims):
        if all(abs(rotated_dims[index] - target_dims[index]) <= EPS for index in range(3)):
            return label, rotated_dims
    raise ValueError(f"No canonical rigid assembly orientation is available for dims={dims!r}.")


def canonical_flat_assembly_orientation(
    dims: tuple[float, float, float],
) -> tuple[str, tuple[float, float, float]]:
    return canonical_rigid_assembly_orientation(dims)


def sample_planar_angles(step_deg: float) -> list[float]:
    if step_deg <= EPS:
        return [0.0]

    angles: list[float] = []
    index = 0
    while True:
        angle = round(index * float(step_deg), 6)
        if angle >= 360.0 - EPS:
            break
        angles.append(angle)
        index += 1
    return angles or [0.0]


def rigid_group_rotated_bbox(
    source_solids: Iterable[SourceSolid],
    rotation_label: str,
    planar_angle_deg: float = 0.0,
) -> BBox:
    solids = tuple(source_solids)
    if not solids:
        raise ValueError("Rigid-group rotation requires at least one source solid.")

    base_matrix = orientation_to_rigid_rotation(rotation_label).matrix
    transform_matrix = base_matrix
    if abs(planar_angle_deg) > EPS:
        transform_matrix = _matrix_multiply(
            _rotation_matrix_z(planar_angle_deg),
            base_matrix,
        )

    return combine_bboxes(
        _transform_bbox(_solid_to_bbox(solid), transform_matrix)
        for solid in solids
    )


def rigid_group_flat_assembly_footprint_dims(
    source_solids: Iterable[SourceSolid],
    dims: tuple[float, float, float],
) -> tuple[str, tuple[float, float, float]]:
    rotation_label, _ = canonical_flat_assembly_orientation(dims)
    matrix = orientation_to_rigid_rotation(rotation_label).matrix
    transformed_bboxes = [
        _transform_bbox(_solid_to_bbox(solid), matrix)
        for solid in source_solids
    ]
    if not transformed_bboxes:
        raise ValueError("Flat-assembly footprint requires at least one source solid.")

    min_x = min(bbox[0] for bbox in transformed_bboxes)
    min_y = min(bbox[1] for bbox in transformed_bboxes)
    min_z = min(bbox[2] for bbox in transformed_bboxes)
    max_x = max(bbox[3] for bbox in transformed_bboxes)
    max_y = max(bbox[4] for bbox in transformed_bboxes)
    max_z = max(bbox[5] for bbox in transformed_bboxes)
    return rotation_label, (max_x - min_x, max_y - min_y, max_z - min_z)


def build_rigid_group_copy_parts(part: Part, copies: int) -> list[Part]:
    if copies < 1:
        raise ValueError("copies must be at least 1.")
    if part.mode != "rigid_group":
        raise ValueError("Rigid-group copies can only be built from rigid-group parts.")

    source_part_id = part.source_part_id or part.part_id
    replicated: list[Part] = []
    for copy_index in range(copies):
        part_id = part.part_id if copies == 1 and copy_index == 0 else f"{source_part_id}_copy_{copy_index:03d}"
        replicated.append(
            Part(
                part_id=part_id,
                solid_tag=part.solid_tag,
                dims=part.dims,
                volume=part.volume,
                bbox_min=part.bbox_min,
                bbox_max=part.bbox_max,
                mode=part.mode,
                orientation_policy=part.orientation_policy,
                source_solids=part.source_solids,
                source_part_id=source_part_id,
                copy_index=copy_index,
            )
        )
    return replicated


def compute_used_extents(placements: Iterable[Placement]) -> tuple[float, float, float]:
    max_x = 0.0
    max_y = 0.0
    max_z = 0.0
    for placement in placements:
        max_x = max(max_x, placement.x + placement.dx)
        max_y = max(max_y, placement.y + placement.dy)
        max_z = max(max_z, placement.z + placement.dz)
    return (max_x, max_y, max_z)


def setup_logger(log_path: Path) -> logging.Logger:
    return build_logger(log_path, with_console=True)


def build_logger(log_path: Path, with_console: bool = True) -> logging.Logger:
    logger_name = f"packing_mvp.{log_path.resolve()}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(file_handler)

    if with_console:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
        logger.addHandler(stream_handler)

    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def _rotation_matrix_z(angle_deg: float) -> tuple[tuple[float, float, float], ...]:
    radians = math.radians(angle_deg)
    cos_angle = math.cos(radians)
    sin_angle = math.sin(radians)
    return (
        (cos_angle, -sin_angle, 0.0),
        (sin_angle, cos_angle, 0.0),
        (0.0, 0.0, 1.0),
    )


def _solid_to_bbox(solid: SourceSolid) -> BBox:
    return (
        solid.bbox_min[0],
        solid.bbox_min[1],
        solid.bbox_min[2],
        solid.bbox_max[0],
        solid.bbox_max[1],
        solid.bbox_max[2],
    )


def _transform_bbox(
    bbox: BBox,
    matrix: tuple[tuple[float, float, float], ...],
) -> BBox:
    transformed: list[tuple[float, float, float]] = []
    for x in (bbox[0], bbox[3]):
        for y in (bbox[1], bbox[4]):
            for z in (bbox[2], bbox[5]):
                transformed.append(
                    (
                        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
                        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
                        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
                    )
                )

    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    zs = [point[2] for point in transformed]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
