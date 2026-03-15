from __future__ import annotations

from packing_mvp.strategies.base import ResolvedPackingStrategy, StrategyRequest


def build_strategy(request: StrategyRequest) -> ResolvedPackingStrategy:
    return ResolvedPackingStrategy(
        packing_mode="flat_assembly_footprint",
        treat_input_as_single_item=True,
        flat_only=True,
        orientation_policy="flat_assembly_footprint",
        longest_to_length=True,
        shortest_to_height=True,
        planar_rotation_step_deg=0.0,
        description=(
            "Treat the whole STEP as one flat rigid assembly, keep axes parallel to the container, "
            "and drive packing from the canonical XY footprint."
        ),
    )
