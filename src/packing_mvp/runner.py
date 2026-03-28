from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import traceback
from typing import Any, Callable, Literal

from packing_mvp.catalog import (
    DEFAULT_GAP_MM,
    DEFAULT_TRUCK_HEIGHT_MM,
    DEFAULT_TRUCK_LENGTH_MM,
    DEFAULT_TRUCK_WIDTH_MM,
    CatalogItem,
    build_parts_from_catalog,
    total_requested_items,
)
from packing_mvp.export import (
    build_failure_result,
    build_truck_packing_result,
    write_placements_csv,
    write_result_json,
)
from packing_mvp.packer import PackingError, pack_items_in_truck, pack_parts
from packing_mvp.step_export import export_arranged_step, export_packed_scene
from packing_mvp.step_extract import extract_catalog_item, extract_parts_from_step_files
from packing_mvp.step_merge import merge_step_files
from packing_mvp.strategies import USER_PACKING_MODES
from packing_mvp.utils import Placement, build_logger, close_logger, ensure_directory
from packing_mvp.viz import render_preview_gif, render_previews

StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class PackingRequest:
    input_path: Path
    out_dir: Path
    max_w: float = DEFAULT_TRUCK_WIDTH_MM
    max_h: float = DEFAULT_TRUCK_HEIGHT_MM
    gap: float = DEFAULT_GAP_MM
    max_l: float | None = DEFAULT_TRUCK_LENGTH_MM
    scale: float = 1.0
    seed: int = 42
    step_units: Literal["packed", "source"] = "packed"
    packing_mode: str | None = None
    flat_only: bool = False
    treat_input_as_single_item: bool = False
    copies: int = 1
    planar_rotation_step_deg: float = 0.0
    input_paths: tuple[Path, ...] = ()
    input_quantities: tuple[int, ...] = ()
    catalog_items: tuple[CatalogItem, ...] = ()

    def __post_init__(self) -> None:
        primary_input = Path(self.input_path)
        normalized_inputs = tuple(Path(path) for path in (self.input_paths or (primary_input,)))
        if not normalized_inputs:
            normalized_inputs = (primary_input,)
        object.__setattr__(self, "input_path", normalized_inputs[0])
        object.__setattr__(self, "input_paths", normalized_inputs)
        if self.packing_mode is not None and self.packing_mode not in USER_PACKING_MODES:
            raise ValueError(f"Unsupported packing_mode: {self.packing_mode}")
        if self.copies < 1:
            raise ValueError("copies must be at least 1.")
        if self.planar_rotation_step_deg < 0:
            raise ValueError("planar_rotation_step_deg must be non-negative.")
        if self.max_l is not None and self.max_l <= 0:
            raise ValueError("max_l must be positive when provided.")
        if self.max_w <= 0 or self.max_h <= 0:
            raise ValueError("Truck width and height must be positive.")
        if self.gap < 0:
            raise ValueError("gap must be non-negative.")

        if self.input_quantities:
            normalized_quantities = tuple(int(value) for value in self.input_quantities)
        elif self.catalog_items:
            normalized_quantities = tuple(item.quantity for item in self.catalog_items)
        elif len(normalized_inputs) == 1:
            normalized_quantities = (int(self.copies),)
        else:
            normalized_quantities = tuple(1 for _ in normalized_inputs)

        if len(normalized_quantities) != len(normalized_inputs) and not self.catalog_items:
            raise ValueError("input_quantities must match input_paths length.")
        if any(quantity < 1 for quantity in normalized_quantities):
            raise ValueError("All item quantities must be at least 1.")
        object.__setattr__(self, "input_quantities", normalized_quantities)


@dataclass(frozen=True)
class PackingRunResult:
    exit_code: int
    out_dir: Path
    result_path: Path
    placements_path: Path
    log_path: Path
    preview_top_path: Path | None
    preview_side_path: Path | None
    result_data: dict[str, Any]
    preview_gif_path: Path | None = None


@dataclass(frozen=True)
class PackingArtifacts:
    out_dir: Path
    result_path: Path
    placements_path: Path
    arranged_step_path: Path
    log_path: Path
    preview_top_path: Path
    preview_side_path: Path
    preview_gif_path: Path


def make_default_output_dir(input_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return input_path.resolve().parent / f"PackingResult_{timestamp}"


def run_packing_job(
    request: PackingRequest,
    *,
    with_console: bool = True,
    status_callback: StatusCallback | None = None,
    preloaded_parts: list[Any] | None = None,
    preloaded_units: dict[str, Any] | None = None,
) -> PackingRunResult:
    artifacts = _prepare_artifacts(request)
    logger = build_logger(artifacts.log_path, with_console=with_console)
    units: dict[str, Any] = {
        "scale": request.scale,
        "manual_scale": request.scale,
        "auto_scale_applied": False,
        "auto_scale_factor": None,
    }

    try:
        catalog_items, units = _resolve_catalog_items(
            request=request,
            logger=logger,
            preloaded_parts=preloaded_parts,
            preloaded_units=preloaded_units,
        )
        constraints = _build_constraints(request)
        _log_request(logger=logger, request=request, catalog_items=catalog_items)

        _notify(status_callback, "Подготовка грузовых мест...")
        parts = build_parts_from_catalog(catalog_items)
        if not parts:
            raise PackingError("No truck items are available for packing.")

        _notify(status_callback, "Расчёт укладки грузовых мест в кузове...")
        outcome = pack_items_in_truck(
            parts=parts,
            truck_l=float(request.max_l or DEFAULT_TRUCK_LENGTH_MM),
            truck_w=float(request.max_w),
            truck_h=float(request.max_h),
            gap=float(request.gap),
            logger=logger,
        )

        if outcome.placements:
            _notify(status_callback, "Запись таблицы размещения...")
            write_placements_csv(outcome.placements, artifacts.placements_path)

            _notify(status_callback, "Экспорт STEP-сборки...")
            export_mode = export_packed_scene(
                outcome.placements,
                artifacts.arranged_step_path,
                logger=logger,
            )

            _notify(status_callback, "Построение превью...")
            render_previews(
                placements=outcome.placements,
                out_dir=artifacts.out_dir,
                container_dims=outcome.container_dims,
                logger=logger,
            )
            preview_gif_path = _render_preview_gif_best_effort(
                placements=outcome.placements,
                out_dir=artifacts.out_dir,
                container_dims=outcome.container_dims,
                output_path=artifacts.preview_gif_path,
                logger=logger,
            )
        else:
            export_mode = None
            preview_gif_path = None

        result_data = build_truck_packing_result(
            input_paths=request.input_paths,
            catalog_items=catalog_items,
            constraints=constraints,
            outcome=outcome,
            units=units,
            export_mode=export_mode,
        )
        write_result_json(result_data, artifacts.result_path)
        exit_code = 0 if result_data["success"] else 2
        logger.info(
            "Packing finished with status=%s packed=%s unpacked=%s",
            result_data["status"],
            result_data["packed_count"],
            result_data["unpacked_count"],
        )
        _notify(status_callback, "Готово")
        return PackingRunResult(
            exit_code=exit_code,
            out_dir=artifacts.out_dir,
            result_path=artifacts.result_path,
            placements_path=artifacts.placements_path,
            log_path=artifacts.log_path,
            preview_top_path=artifacts.preview_top_path if artifacts.preview_top_path.exists() else None,
            preview_side_path=artifacts.preview_side_path if artifacts.preview_side_path.exists() else None,
            preview_gif_path=preview_gif_path,
            result_data=result_data,
        )
    except Exception as exc:
        logger.exception("Packing job failed")
        result_data = build_failure_result(
            input_paths=request.input_paths,
            constraints=_build_constraints(request),
            message=str(exc),
            units=units,
            n_parts=0,
            does_not_fit=False,
            packed_count=0,
            unpacked_count=0,
            used_extents=None,
        )
        write_result_json(result_data, artifacts.result_path)
        _notify(status_callback, f"Ошибка: {exc}")
        return PackingRunResult(
            exit_code=2,
            out_dir=artifacts.out_dir,
            result_path=artifacts.result_path,
            placements_path=artifacts.placements_path,
            log_path=artifacts.log_path,
            preview_top_path=artifacts.preview_top_path if artifacts.preview_top_path.exists() else None,
            preview_side_path=artifacts.preview_side_path if artifacts.preview_side_path.exists() else None,
            preview_gif_path=artifacts.preview_gif_path if artifacts.preview_gif_path.exists() else None,
            result_data=result_data,
        )
    finally:
        close_logger(logger)


def run_packing_job_in_subprocess(request: PackingRequest, event_queue: Any) -> None:
    def emit(event_type: str, payload: object) -> None:
        event_queue.put((event_type, payload))

    try:
        result = run_packing_job(
            request,
            with_console=False,
            status_callback=lambda message: emit("status", message),
        )
    except BaseException as exc:
        try:
            result = create_failure_run_result(
                request,
                message=f"Сбой фонового процесса: {exc}",
                with_console=False,
            )
        except BaseException:
            try:
                emit("worker_error", traceback.format_exc())
            except BaseException:
                pass
            return

    try:
        emit("done", result)
    except BaseException:
        pass


def create_failure_run_result(
    request: PackingRequest,
    *,
    message: str,
    with_console: bool = True,
    status_callback: StatusCallback | None = None,
    units: dict[str, Any] | None = None,
    n_parts: int = 0,
) -> PackingRunResult:
    artifacts = _prepare_artifacts(request)
    logger = build_logger(artifacts.log_path, with_console=with_console)
    try:
        result_data = build_failure_result(
            input_paths=request.input_paths,
            constraints=_build_constraints(request),
            message=message,
            units=units,
            n_parts=n_parts,
            does_not_fit=False,
            packed_count=0,
            unpacked_count=n_parts,
            used_extents=None,
        )
        write_result_json(result_data, artifacts.result_path)
        _notify(status_callback, f"Ошибка: {message}")
        return PackingRunResult(
            exit_code=2,
            out_dir=artifacts.out_dir,
            result_path=artifacts.result_path,
            placements_path=artifacts.placements_path,
            log_path=artifacts.log_path,
            preview_top_path=None,
            preview_side_path=None,
            preview_gif_path=None,
            result_data=result_data,
        )
    finally:
        close_logger(logger)


def _prepare_artifacts(request: PackingRequest) -> PackingArtifacts:
    out_dir = ensure_directory(Path(request.out_dir))
    return PackingArtifacts(
        out_dir=out_dir,
        result_path=out_dir / "result.json",
        placements_path=out_dir / "placements.csv",
        arranged_step_path=out_dir / "arranged.step",
        log_path=out_dir / "packing.log",
        preview_top_path=out_dir / "preview_top.png",
        preview_side_path=out_dir / "preview_side.png",
        preview_gif_path=out_dir / "preview.gif",
    )


def _resolve_catalog_items(
    *,
    request: PackingRequest,
    logger: Any,
    preloaded_parts: list[Any] | None,
    preloaded_units: dict[str, Any] | None,
) -> tuple[list[CatalogItem], dict[str, Any]]:
    if request.catalog_items:
        items = list(request.catalog_items)
        units = {
            "scale": request.scale,
            "manual_scale": request.scale,
            "auto_scale_applied": any(item.auto_scale_applied for item in items),
            "auto_scale_factor": next(
                (item.auto_scale_factor for item in items if item.auto_scale_factor is not None),
                None,
            ),
        }
        return items, units

    if preloaded_parts is not None and preloaded_units is not None:
        items: list[CatalogItem] = []
        counts: dict[str, int] = {}
        for part in preloaded_parts:
            item_id = str(getattr(part, "source_part_id", None) or getattr(part, "part_id", "item"))
            counts[item_id] = counts.get(item_id, 0) + 1
            path = str(getattr(part, "source_path", "") or item_id)
            dims = tuple(float(value) for value in getattr(part, "dims", (0.0, 0.0, 0.0)))
            items.append(
                CatalogItem(
                    item_id=item_id,
                    filename=Path(path).name,
                    source_path=path,
                    detected_dims_mm=dims,
                    dimensions_mm=dims,
                    quantity=1,
                    manual_override=False,
                    source_scale=float(preloaded_units.get("scale") or 1.0),
                    manual_scale=float(preloaded_units.get("manual_scale") or 1.0),
                    auto_scale_applied=bool(preloaded_units.get("auto_scale_applied")),
                    auto_scale_factor=preloaded_units.get("auto_scale_factor"),
                    raw_max_dim=None,
                )
            )
        return items, dict(preloaded_units)

    items: list[CatalogItem] = []
    for index, input_path in enumerate(request.input_paths, start=1):
        quantity = request.input_quantities[index - 1]
        items.append(
            extract_catalog_item(
                input_path=input_path,
                item_id=f"item_{index:03d}",
                quantity=quantity,
                scale=request.scale,
                logger=logger,
            )
        )
    units = {
        "scale": request.scale,
        "manual_scale": request.scale,
        "auto_scale_applied": any(item.auto_scale_applied for item in items),
        "auto_scale_factor": next(
            (item.auto_scale_factor for item in items if item.auto_scale_factor is not None),
            None,
        ),
    }
    return items, units


def _build_constraints(request: PackingRequest) -> dict[str, Any]:
    return {
        "maxL": request.max_l,
        "maxW": request.max_w,
        "maxH": request.max_h,
        "gap": request.gap,
        "seed": request.seed,
    }


def _log_request(*, logger: Any, request: PackingRequest, catalog_items: list[CatalogItem]) -> None:
    logger.info("Starting truck packing job")
    logger.info("Truck: L=%s W=%s H=%s gap=%s", request.max_l, request.max_w, request.max_h, request.gap)
    logger.info("Loaded item types: %s", len(catalog_items))
    for item in catalog_items:
        logger.info(
            "Item %s source=%s dims_mm=%s quantity=%s manual_override=%s",
            item.item_id,
            item.source_path,
            tuple(round(value, 3) for value in item.dimensions_mm),
            item.quantity,
            item.manual_override,
        )
    logger.info("Total requested items: %s", total_requested_items(catalog_items))


def _notify(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback is not None:
        status_callback(message)


def _render_preview_gif_best_effort(
    *,
    placements: list[Placement],
    out_dir: Path,
    container_dims: tuple[int, int, int],
    output_path: Path,
    logger: Any,
) -> Path | None:
    try:
        return render_preview_gif(
            placements=placements,
            out_dir=out_dir,
            container_dims=container_dims,
            logger=logger,
        )
    except Exception as exc:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        logger.warning("Failed to build preview.gif: %s", exc)
        return None
