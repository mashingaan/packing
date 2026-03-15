from __future__ import annotations

from packing_mvp.strategies.base import ResolvedPackingStrategy, StrategyRequest


def build_strategy(request: StrategyRequest) -> ResolvedPackingStrategy:
    return ResolvedPackingStrategy(
        packing_mode="solids",
        treat_input_as_single_item=False,
        flat_only=bool(request.flat_only),
        orientation_policy="default",
        longest_to_length=False,
        shortest_to_height=False,
        planar_rotation_step_deg=0.0,
        description="Split STEP into solids and pack each solid independently with bbox-based logic.",
    )
