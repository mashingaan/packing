from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def open_3d_preview(parent: Any, result_data: dict[str, Any]) -> Any:
    placed_items = list(result_data.get("placed_items") or [])
    if not placed_items:
        raise RuntimeError("Нет размещённых грузовых мест для предпросмотра.")

    import tkinter as tk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    truck = result_data.get("truck") or {}
    truck_l = float(truck.get("length_mm") or 0.0)
    truck_w = float(truck.get("width_mm") or 0.0)
    truck_h = float(truck.get("height_mm") or 0.0)

    window = tk.Toplevel(parent)
    window.title("3D-предпросмотр кузова")
    window.geometry("1100x760")

    figure = Figure(figsize=(10, 7), dpi=100)
    axis = figure.add_subplot(111, projection="3d")

    _draw_truck_wireframe(axis, truck_l, truck_w, truck_h)
    for index, item in enumerate(placed_items):
        position = item.get("position_mm") or {}
        dims = item.get("dimensions_mm") or {}
        x = float(position.get("x") or 0.0)
        y = float(position.get("y") or 0.0)
        z = float(position.get("z") or 0.0)
        dx = float(dims.get("L") or 0.0)
        dy = float(dims.get("W") or 0.0)
        dz = float(dims.get("H") or 0.0)
        color = _palette(index)
        _draw_box(axis, x, y, z, dx, dy, dz, color=color, poly_cls=Poly3DCollection)
        axis.text(
            x + dx / 2.0,
            y + dy / 2.0,
            z + dz + max(20.0, dz * 0.02),
            str(item.get("place_no") or (index + 1)),
            color="#1f2933",
        )

    axis.set_xlabel("Длина (мм)")
    axis.set_ylabel("Ширина (мм)")
    axis.set_zlabel("Высота (мм)")
    axis.set_title("Схема загрузки кузова")
    axis.set_xlim(0, max(truck_l, 1.0))
    axis.set_ylim(0, max(truck_w, 1.0))
    axis.set_zlim(0, max(truck_h, 1.0))
    axis.set_box_aspect((max(truck_l, 1.0), max(truck_w, 1.0), max(truck_h, 1.0)))
    axis.grid(True, linestyle=":", linewidth=0.5)
    axis.view_init(elev=22, azim=-60)

    canvas = FigureCanvasTkAgg(figure, master=window)
    canvas.draw()
    toolbar = NavigationToolbar2Tk(canvas, window)
    toolbar.update()
    canvas.get_tk_widget().pack(fill="both", expand=True)
    return window


def _draw_truck_wireframe(axis: Any, length_mm: float, width_mm: float, height_mm: float) -> None:
    corners = [
        (0.0, 0.0, 0.0),
        (length_mm, 0.0, 0.0),
        (length_mm, width_mm, 0.0),
        (0.0, width_mm, 0.0),
        (0.0, 0.0, height_mm),
        (length_mm, 0.0, height_mm),
        (length_mm, width_mm, height_mm),
        (0.0, width_mm, height_mm),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    for start, end in edges:
        x_values = [corners[start][0], corners[end][0]]
        y_values = [corners[start][1], corners[end][1]]
        z_values = [corners[start][2], corners[end][2]]
        axis.plot(x_values, y_values, z_values, color="#54606b", linewidth=1.2, alpha=0.7)


def _draw_box(axis: Any, x: float, y: float, z: float, dx: float, dy: float, dz: float, *, color: str, poly_cls: Any) -> None:
    vertices = [
        (x, y, z),
        (x + dx, y, z),
        (x + dx, y + dy, z),
        (x, y + dy, z),
        (x, y, z + dz),
        (x + dx, y, z + dz),
        (x + dx, y + dy, z + dz),
        (x, y + dy, z + dz),
    ]
    faces = [
        [vertices[0], vertices[1], vertices[2], vertices[3]],
        [vertices[4], vertices[5], vertices[6], vertices[7]],
        [vertices[0], vertices[1], vertices[5], vertices[4]],
        [vertices[1], vertices[2], vertices[6], vertices[5]],
        [vertices[2], vertices[3], vertices[7], vertices[6]],
        [vertices[3], vertices[0], vertices[4], vertices[7]],
    ]
    poly = poly_cls(faces, facecolors=color, edgecolors="#1f2933", linewidths=0.7, alpha=0.45)
    axis.add_collection3d(poly)


def _palette(index: int) -> str:
    colors = [
        "#c26d3d",
        "#5b8c5a",
        "#4b6cb7",
        "#c94f4f",
        "#8d6cab",
        "#caa13d",
        "#3c9bb3",
        "#d16b86",
    ]
    return colors[index % len(colors)]
