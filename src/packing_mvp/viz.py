from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import numpy as np

from packing_mvp.utils import Placement

_GIF_FRAME_DURATION_MS = 350
_GIF_FINAL_FRAME_DURATION_MS = 1600
_LEGEND_LIMIT = 20
_GIF_CANVAS_WIDTH = 1920
_GIF_CANVAS_HEIGHT = 960
_GIF_MARGIN_X = 40
_GIF_MARGIN_Y = 28
_GIF_PANEL_GAP = 36
_GIF_LEGEND_WIDTH = 360
_GIF_PANEL_TITLE_HEIGHT = 44
_GIF_PANEL_INSET_X = 28
_GIF_PANEL_INSET_Y = 20
_GIF_GRID_STEPS = 5


@dataclass(frozen=True)
class _ProjectionSpec:
    vertical_axis: str
    title: str
    container_x: float
    container_y: float
    extent_getter: Callable[[Placement], tuple[float, float, float, float]]


@dataclass(frozen=True)
class _GifFonts:
    title: Any
    axis: Any
    number: Any
    legend_title: Any
    legend_body: Any


@dataclass(frozen=True)
class _GifBox:
    left: int
    top: int
    width: int
    height: int


def render_previews(
    placements: list[Placement],
    out_dir: Path,
    container_dims: tuple[int, int, int],
    logger: Any | None = None,
) -> tuple[Path, Path]:
    plt, rectangle = _load_matplotlib()

    out_dir = Path(out_dir)
    top_path = out_dir / "preview_top.png"
    side_path = out_dir / "preview_side.png"
    colors = _build_colors(placements, plt)
    top_spec, side_spec = _build_projection_specs(container_dims)

    _render_projection_png(
        image_path=top_path,
        placements=placements,
        colors=colors,
        spec=top_spec,
        plt=plt,
        rectangle=rectangle,
    )
    _render_projection_png(
        image_path=side_path,
        placements=placements,
        colors=colors,
        spec=side_spec,
        plt=plt,
        rectangle=rectangle,
    )

    if logger:
        logger.info("Saved previews: %s, %s", top_path, side_path)

    return top_path, side_path


def render_preview_gif(
    placements: list[Placement],
    out_dir: Path,
    container_dims: tuple[int, int, int],
    logger: Any | None = None,
) -> Path:
    image_module, image_draw_module, image_font_module = _load_pillow()
    plt, _ = _load_matplotlib()

    out_dir = Path(out_dir)
    gif_path = out_dir / "preview.gif"
    specs = _build_projection_specs(container_dims)
    colors = _build_colors(placements, plt)
    fonts = _load_gif_fonts(image_font_module)

    rgba_frames = [
        _render_gif_frame(
            placements=placements[: frame_index + 1],
            colors=colors,
            specs=specs,
            image_module=image_module,
            image_draw_module=image_draw_module,
            fonts=fonts,
        )
        for frame_index in range(-1, len(placements))
    ]

    adaptive_palette = getattr(image_module, "ADAPTIVE", image_module.Palette.ADAPTIVE)
    palette_image = rgba_frames[-1].convert("RGB").convert("P", palette=adaptive_palette, colors=255)
    gif_frames = [frame.convert("RGB").quantize(palette=palette_image) for frame in rgba_frames]
    durations = [_GIF_FRAME_DURATION_MS] * len(gif_frames)
    durations[-1] = _GIF_FINAL_FRAME_DURATION_MS

    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
    )

    if logger:
        logger.info("Saved preview GIF: %s", gif_path)

    return gif_path


def _load_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    return plt, Rectangle


def _load_pillow():
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _build_projection_specs(
    container_dims: tuple[int, int, int],
) -> tuple[_ProjectionSpec, _ProjectionSpec]:
    return (
        _ProjectionSpec(
            vertical_axis="Y",
            title="Packing Preview Top (X-Y)",
            container_x=container_dims[0],
            container_y=container_dims[1],
            extent_getter=lambda item: (item.x, item.y, item.dx, item.dy),
        ),
        _ProjectionSpec(
            vertical_axis="Z",
            title="Packing Preview Side (X-Z)",
            container_x=container_dims[0],
            container_y=container_dims[2],
            extent_getter=lambda item: (item.x, item.z, item.dx, item.dz),
        ),
    )


def _build_colors(placements: list[Placement], plt: Any) -> np.ndarray:
    return plt.cm.tab20(np.linspace(0, 1, max(1, len(placements))))


def _render_projection_png(
    *,
    image_path: Path,
    placements: list[Placement],
    colors: np.ndarray,
    spec: _ProjectionSpec,
    plt: Any,
    rectangle: Any,
) -> None:
    fig, ax = plt.subplots(figsize=(14, 8), dpi=160)
    _draw_projection(
        ax=ax,
        placements=placements,
        colors=colors,
        spec=spec,
        rectangle=rectangle,
    )

    legend_text = _build_legend_text(placements)
    if legend_text:
        ax.text(
            1.02,
            1.0,
            legend_text,
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=8,
        )

    fig.tight_layout()
    fig.savefig(image_path, bbox_inches="tight")
    plt.close(fig)


def _render_gif_frame(
    *,
    placements: list[Placement],
    colors: np.ndarray,
    specs: tuple[_ProjectionSpec, _ProjectionSpec],
    image_module: Any,
    image_draw_module: Any,
    fonts: _GifFonts,
):
    image = image_module.new("RGBA", (_GIF_CANVAS_WIDTH, _GIF_CANVAS_HEIGHT), (255, 255, 255, 255))
    draw = image_draw_module.Draw(image, "RGBA")

    plot_area_width = _GIF_CANVAS_WIDTH - (2 * _GIF_MARGIN_X) - _GIF_LEGEND_WIDTH - _GIF_PANEL_GAP
    panel_width = plot_area_width // 2
    panel_height = _GIF_CANVAS_HEIGHT - (2 * _GIF_MARGIN_Y)
    legend_left = _GIF_MARGIN_X + plot_area_width + _GIF_PANEL_GAP
    panel_top = _GIF_MARGIN_Y

    left_panel = _GifBox(_GIF_MARGIN_X, panel_top, panel_width, panel_height)
    right_panel = _GifBox(_GIF_MARGIN_X + panel_width + _GIF_PANEL_GAP, panel_top, panel_width, panel_height)

    _draw_gif_projection(
        draw=draw,
        panel=left_panel,
        placements=placements,
        colors=colors,
        spec=specs[0],
        fonts=fonts,
    )
    _draw_gif_projection(
        draw=draw,
        panel=right_panel,
        placements=placements,
        colors=colors,
        spec=specs[1],
        fonts=fonts,
    )
    _draw_gif_legend(
        draw=draw,
        placements=placements,
        colors=colors,
        fonts=fonts,
        legend_left=legend_left,
        legend_top=panel_top,
        legend_width=_GIF_LEGEND_WIDTH,
        legend_height=panel_height,
    )

    return image


def _draw_gif_projection(
    *,
    draw: Any,
    panel: _GifBox,
    placements: list[Placement],
    colors: np.ndarray,
    spec: _ProjectionSpec,
    fonts: _GifFonts,
) -> None:
    panel_fill = (248, 249, 251, 255)
    panel_border = (212, 217, 223, 255)
    grid_color = (230, 234, 238, 255)
    container_border = (24, 33, 41, 255)

    panel_rect = (
        panel.left,
        panel.top,
        panel.left + panel.width,
        panel.top + panel.height,
    )
    draw.rounded_rectangle(panel_rect, radius=18, fill=panel_fill, outline=panel_border, width=2)

    title_y = panel.top + 10
    _draw_centered_text(
        draw=draw,
        center_x=panel.left + (panel.width // 2),
        top=title_y,
        text=spec.title,
        font=fonts.title,
        fill=(33, 42, 49, 255),
    )

    plot_box = _fit_plot_box(panel=panel, spec=spec)
    _draw_grid(draw=draw, box=plot_box, steps=_GIF_GRID_STEPS, color=grid_color)
    draw.rectangle(
        (
            plot_box.left,
            plot_box.top,
            plot_box.left + plot_box.width,
            plot_box.top + plot_box.height,
        ),
        outline=container_border,
        width=3,
    )

    for index, placement in enumerate(placements):
        px, py, pdx, pdy = spec.extent_getter(placement)
        rect = _placement_to_pixels(
            box=plot_box,
            container_x=spec.container_x,
            container_y=spec.container_y,
            x=px,
            y=py,
            dx=pdx,
            dy=pdy,
        )
        draw.rectangle(rect, fill=_gif_fill_color(colors[index]), outline=(20, 20, 20, 255), width=2)

        label = str(index + 1)
        label_bbox = draw.textbbox((0, 0), label, font=fonts.number, stroke_width=1)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        rect_width = rect[2] - rect[0]
        rect_height = rect[3] - rect[1]
        if label_width + 8 <= rect_width and label_height + 6 <= rect_height:
            _draw_centered_text(
                draw=draw,
                center_x=(rect[0] + rect[2]) // 2,
                top=((rect[1] + rect[3]) // 2) - (label_height // 2),
                text=label,
                font=fonts.number,
                fill=(20, 20, 20, 255),
                stroke_width=1,
                stroke_fill=(255, 255, 255, 255),
            )

    _draw_axis_text(draw=draw, panel=panel, plot_box=plot_box, spec=spec, fonts=fonts)


def _draw_axis_text(
    *,
    draw: Any,
    panel: _GifBox,
    plot_box: _GifBox,
    spec: _ProjectionSpec,
    fonts: _GifFonts,
) -> None:
    axis_fill = (87, 97, 107, 255)
    _draw_centered_text(
        draw=draw,
        center_x=plot_box.left + (plot_box.width // 2),
        top=plot_box.top + plot_box.height + 8,
        text="X (mm)",
        font=fonts.axis,
        fill=axis_fill,
    )
    draw.text(
        (panel.left + 8, plot_box.top - 4),
        f"{spec.vertical_axis} (mm)",
        font=fonts.axis,
        fill=axis_fill,
    )


def _draw_gif_legend(
    *,
    draw: Any,
    placements: list[Placement],
    colors: np.ndarray,
    fonts: _GifFonts,
    legend_left: int,
    legend_top: int,
    legend_width: int,
    legend_height: int,
) -> None:
    panel_rect = (
        legend_left,
        legend_top,
        legend_left + legend_width,
        legend_top + legend_height,
    )
    draw.rounded_rectangle(panel_rect, radius=18, fill=(250, 250, 252, 255), outline=(212, 217, 223, 255), width=2)
    draw.text((legend_left + 20, legend_top + 14), "Animation", font=fonts.legend_title, fill=(33, 42, 49, 255))

    line_y = legend_top + 52
    draw.text(
        (legend_left + 20, line_y),
        f"Placed parts: {len(placements)}",
        font=fonts.legend_body,
        fill=(87, 97, 107, 255),
    )
    line_y += 28

    if not placements:
        draw.text(
            (legend_left + 20, line_y),
            "Frames are built one part at a time.",
            font=fonts.legend_body,
            fill=(87, 97, 107, 255),
        )
        return

    for index, placement in enumerate(placements[:_LEGEND_LIMIT]):
        swatch_top = line_y + 3
        draw.rectangle(
            (legend_left + 20, swatch_top, legend_left + 36, swatch_top + 16),
            fill=_gif_fill_color(colors[index], alpha=255),
            outline=(20, 20, 20, 255),
            width=1,
        )
        draw.text(
            (legend_left + 46, line_y),
            f"{index + 1}: {placement.part_id} ({placement.rot})",
            font=fonts.legend_body,
            fill=(33, 42, 49, 255),
        )
        line_y += 24

    if len(placements) > _LEGEND_LIMIT:
        draw.text(
            (legend_left + 20, line_y + 4),
            f"... and {len(placements) - _LEGEND_LIMIT} more",
            font=fonts.legend_body,
            fill=(87, 97, 107, 255),
        )


def _load_gif_fonts(image_font_module: Any) -> _GifFonts:
    return _GifFonts(
        title=_load_font(image_font_module, 22),
        axis=_load_font(image_font_module, 18),
        number=_load_font(image_font_module, 18),
        legend_title=_load_font(image_font_module, 22),
        legend_body=_load_font(image_font_module, 18),
    )


def _load_font(image_font_module: Any, size: int):
    for font_name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return image_font_module.truetype(font_name, size=size)
        except OSError:
            continue
    return image_font_module.load_default()


def _fit_plot_box(*, panel: _GifBox, spec: _ProjectionSpec) -> _GifBox:
    available_left = panel.left + _GIF_PANEL_INSET_X
    available_top = panel.top + _GIF_PANEL_TITLE_HEIGHT + _GIF_PANEL_INSET_Y
    available_width = panel.width - (2 * _GIF_PANEL_INSET_X)
    available_height = panel.height - _GIF_PANEL_TITLE_HEIGHT - (2 * _GIF_PANEL_INSET_Y) - 36

    scale = min(
        available_width / max(spec.container_x, 1.0),
        available_height / max(spec.container_y, 1.0),
    )
    plot_width = max(1, int(round(spec.container_x * scale)))
    plot_height = max(1, int(round(spec.container_y * scale)))
    plot_left = available_left + max(0, (available_width - plot_width) // 2)
    plot_top = available_top + max(0, (available_height - plot_height) // 2)
    return _GifBox(plot_left, plot_top, plot_width, plot_height)


def _draw_grid(*, draw: Any, box: _GifBox, steps: int, color: tuple[int, int, int, int]) -> None:
    for step in range(1, steps):
        x = box.left + int(round(box.width * step / steps))
        draw.line((x, box.top, x, box.top + box.height), fill=color, width=1)
    for step in range(1, steps):
        y = box.top + int(round(box.height * step / steps))
        draw.line((box.left, y, box.left + box.width, y), fill=color, width=1)


def _placement_to_pixels(
    *,
    box: _GifBox,
    container_x: float,
    container_y: float,
    x: float,
    y: float,
    dx: float,
    dy: float,
) -> tuple[int, int, int, int]:
    scale_x = box.width / max(container_x, 1.0)
    scale_y = box.height / max(container_y, 1.0)

    left = box.left + int(round(x * scale_x))
    right = box.left + int(round((x + dx) * scale_x))
    top = box.top + int(round(box.height - ((y + dy) * scale_y)))
    bottom = box.top + int(round(box.height - (y * scale_y)))
    return (left, top, right, bottom)


def _gif_fill_color(color: np.ndarray, alpha: int = 214) -> tuple[int, int, int, int]:
    return (
        int(round(float(color[0]) * 255)),
        int(round(float(color[1]) * 255)),
        int(round(float(color[2]) * 255)),
        alpha,
    )


def _draw_centered_text(
    *,
    draw: Any,
    center_x: int,
    top: int,
    text: str,
    font: Any,
    fill: tuple[int, int, int, int],
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bbox[2] - bbox[0]
    x = center_x - (width // 2)
    draw.text(
        (x, top),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def _draw_projection(
    *,
    ax: Any,
    placements: list[Placement],
    colors: np.ndarray,
    spec: _ProjectionSpec,
    rectangle: Any,
) -> None:
    ax.add_patch(
        rectangle(
            (0, 0),
            spec.container_x,
            spec.container_y,
            fill=False,
            edgecolor="black",
            linewidth=1.5,
            linestyle="--",
        )
    )

    for index, placement in enumerate(placements):
        px, py, pdx, pdy = spec.extent_getter(placement)
        ax.add_patch(
            rectangle(
                (px, py),
                pdx,
                pdy,
                facecolor=colors[index],
                edgecolor="black",
                linewidth=0.8,
                alpha=0.75,
            )
        )
        ax.text(
            px + pdx / 2.0,
            py + pdy / 2.0,
            str(index + 1),
            ha="center",
            va="center",
            fontsize=8,
            color="black",
        )

    ax.set_xlim(0, spec.container_x)
    ax.set_ylim(0, spec.container_y)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel(f"{spec.vertical_axis} (mm)")
    ax.set_title(spec.title)
    ax.grid(True, linestyle=":", linewidth=0.5)
    ax.set_aspect("equal", adjustable="box")


def _build_legend_text(placements: list[Placement]) -> str:
    return "\n".join(
        f"{index + 1}: {placement.part_id} ({placement.rot})"
        for index, placement in enumerate(placements[:_LEGEND_LIMIT])
    )


def _figure_to_image(fig: Any, image_module: Any):
    with BytesIO() as buffer:
        fig.savefig(buffer, format="png", facecolor="white")
        buffer.seek(0)
        image = image_module.open(buffer).convert("RGBA")
        image.load()
        return image
