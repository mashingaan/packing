from __future__ import annotations

from packing_mvp.strategies.base import (
    PackingMode,
    RequestedPackingMode,
    ResolvedPackingStrategy,
    StrategyRequest,
)
from packing_mvp.strategies.flat_assembly_footprint import build_strategy as build_flat_assembly_footprint_strategy
from packing_mvp.strategies.single_root_shape import build_strategy as build_single_root_shape_strategy
from packing_mvp.strategies.solids import build_strategy as build_solids_strategy

USER_PACKING_MODES: tuple[RequestedPackingMode, ...] = (
    "solids",
    "single_root_shape",
    "flat_assembly_footprint",
)


def resolve_packing_strategy(request: StrategyRequest) -> ResolvedPackingStrategy:
    if len(request.input_paths) > 1:
        return ResolvedPackingStrategy(
            packing_mode="multi_root_shapes",
            treat_input_as_single_item=True,
            flat_only=False,
            orientation_policy="default",
            longest_to_length=False,
            shortest_to_height=False,
            planar_rotation_step_deg=0.0,
            description="Treat each selected STEP file as one rigid root shape.",
        )

    requested_mode = _requested_mode(request)
    if requested_mode == "flat_assembly_footprint":
        return build_flat_assembly_footprint_strategy(request)
    if requested_mode == "single_root_shape":
        return build_single_root_shape_strategy(request)
    return build_solids_strategy(request)


def _requested_mode(request: StrategyRequest) -> PackingMode:
    requested_mode = getattr(request, "packing_mode", None)
    if requested_mode in USER_PACKING_MODES:
        return requested_mode
    if request.treat_input_as_single_item and request.flat_only:
        return "flat_assembly_footprint"
    if request.treat_input_as_single_item:
        return "single_root_shape"
    return "solids"
