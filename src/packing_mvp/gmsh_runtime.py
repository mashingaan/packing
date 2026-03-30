from __future__ import annotations

from typing import Any


def initialize_gmsh(gmsh: Any) -> None:
    # Disable Gmsh signal handlers so its API can be used from GUI worker threads.
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
