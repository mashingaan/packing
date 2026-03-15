from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from packing_mvp.step_extract import extract_parts_from_step
from packing_mvp.utils import Part, build_rigid_group_copy_parts

PackingMode = Literal[
    "solids",
    "single_root_shape",
    "flat_assembly_footprint",
    "multi_root_shapes",
]
RequestedPackingMode = Literal[
    "solids",
    "single_root_shape",
    "flat_assembly_footprint",
]
OrientationPolicy = Literal[
    "default",
    "assembly_axes_parallel_to_box_axes",
    "flat_assembly_footprint",
]


class StrategyRequest(Protocol):
    input_paths: tuple[Path, ...]
    flat_only: bool
    treat_input_as_single_item: bool
    copies: int
    planar_rotation_step_deg: float
    scale: float


@dataclass(frozen=True)
class ResolvedPackingStrategy:
    packing_mode: PackingMode
    treat_input_as_single_item: bool
    flat_only: bool
    orientation_policy: OrientationPolicy
    longest_to_length: bool
    shortest_to_height: bool
    planar_rotation_step_deg: float
    description: str

    def extract_parts(
        self,
        *,
        input_path: Path,
        scale: float,
        logger: Any | None = None,
    ) -> tuple[list[Part], dict[str, Any]]:
        return extract_parts_from_step(
            input_path=input_path,
            scale=scale,
            treat_input_as_single_item=self.treat_input_as_single_item,
            orientation_policy=self.orientation_policy,
            logger=logger,
        )

    def expand_parts(
        self,
        parts: list[Part],
        *,
        copies: int,
    ) -> list[Part]:
        if copies == 1 or not self.treat_input_as_single_item:
            return list(parts)
        if len(parts) != 1:
            raise RuntimeError(
                f"Expected exactly one rigid item before copy expansion, got {len(parts)}."
            )
        return build_rigid_group_copy_parts(parts[0], copies)
