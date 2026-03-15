from __future__ import annotations

from packing_mvp.strategies.base import ResolvedPackingStrategy, StrategyRequest


def build_strategy(request: StrategyRequest) -> ResolvedPackingStrategy:
    return ResolvedPackingStrategy(
        packing_mode="single_root_shape",
        treat_input_as_single_item=True,
        flat_only=bool(request.flat_only),
        orientation_policy="default",
        longest_to_length=False,
        shortest_to_height=False,
        planar_rotation_step_deg=(
            float(request.planar_rotation_step_deg) if request.flat_only else 0.0
        ),
        description="Treat the whole STEP as one rigid root shape and pack using aggregate bbox dimensions.",
    )
