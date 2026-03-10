from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import traceback
from typing import Any, Callable, Literal

from packing_mvp.export import (
    build_failure_result,
    build_success_result,
    format_constraint_failure_message,
    validate_constraints,
    write_placements_csv,
    write_result_json,
)
from packing_mvp.packer import DoesNotFitError, PackingError, pack_parts
from packing_mvp.step_export import PackingMode, export_arranged_step
from packing_mvp.step_extract import (
    extract_parts_from_step,
    extract_parts_from_step_files,
)
from packing_mvp.step_merge import merge_step_files
from packing_mvp.utils import (
    EPS,
    Placement,
    Part,
    build_logger,
    build_rigid_group_copy_parts,
    ceil_mm,
    close_logger,
    ensure_directory,
)
from packing_mvp.viz import render_preview_gif, render_previews

StatusCallback = Callable[[str], None]
WorkerEvent = tuple[str, object]


@dataclass(frozen=True)
class PackingRequest:
    input_path: Path
    out_dir: Path
    max_w: float
    max_h: float
    gap: float
    max_l: float | None = None
    scale: float = 1.0
    seed: int = 42
    step_units: Literal["packed", "source"] = "packed"
    flat_only: bool = False
    treat_input_as_single_item: bool = False
    copies: int = 1
    planar_rotation_step_deg: float = 0.0
    input_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        primary_input = Path(self.input_path)
        normalized_inputs = tuple(Path(path) for path in (self.input_paths or (primary_input,)))
        if not normalized_inputs:
            normalized_inputs = (primary_input,)
        object.__setattr__(self, "input_path", normalized_inputs[0])
        object.__setattr__(self, "input_paths", normalized_inputs)
        if self.copies < 1:
            raise ValueError("copies must be at least 1.")
        if self.planar_rotation_step_deg < 0:
            raise ValueError("planar_rotation_step_deg must be non-negative.")


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
    preloaded_parts: list[Part] | None = None,
    preloaded_units: dict[str, Any] | None = None,
) -> PackingRunResult:
    if (preloaded_parts is None) != (preloaded_units is None):
        raise ValueError("preloaded_parts and preloaded_units must be provided together.")

    artifacts = _prepare_artifacts(request)
    constraints = _build_constraints(request)
    packing_mode = _packing_mode(request)
    logger = build_logger(artifacts.log_path, with_console=with_console)
    parts: list[Part] = list(preloaded_parts or [])
    units = None
    outcome = None

    try:
        _log_request(logger, request)
        _validate_request_modes(request)

        with TemporaryDirectory(prefix="packing-mvp-") as temp_dir:
            job_input_path: Path | None = None

            if preloaded_parts is None or preloaded_units is None:
                _notify(status_callback, "Чтение STEP-файла...")
                if _uses_multi_file_items(request):
                    parts, units = extract_parts_from_step_files(
                        input_paths=request.input_paths,
                        scale=request.scale,
                        logger=logger,
                    )
                else:
                    job_input_path = _resolve_job_input_path(
                        request=request,
                        temp_dir=Path(temp_dir),
                        logger=logger,
                        status_callback=status_callback,
                    )
                    parts, units = extract_parts_from_step(
                        input_path=job_input_path,
                        scale=request.scale,
                        treat_input_as_single_item=request.treat_input_as_single_item,
                        logger=logger,
                    )
            else:
                units = dict(preloaded_units)
                logger.info("Using preloaded STEP data: %d items", len(parts))

            parts = _expand_requested_copies(parts, request=request)

            _notify(status_callback, "Укладка деталей...")
            outcome = pack_parts(
                parts=parts,
                max_w=request.max_w,
                max_h=request.max_h,
                max_l=request.max_l,
                gap=request.gap,
                seed=request.seed,
                flat_only=request.flat_only,
                planar_rotation_step_deg=request.planar_rotation_step_deg,
                logger=logger,
            )
            _validate_outcome_within_request(
                outcome=outcome,
                request=request,
                constraints=constraints,
                logger=logger,
            )

            _notify(status_callback, "Сохранение таблицы размещения...")
            write_placements_csv(outcome.placements, artifacts.placements_path)

            _notify(status_callback, "Exporting arranged STEP...")
            if packing_mode == "multi_root_shapes":
                export_arranged_step(
                    request.input_paths[0],
                    artifacts.placements_path,
                    artifacts.arranged_step_path,
                    scale=1.0,
                    units_mode=request.step_units,
                    packing_mode=packing_mode,
                    input_steps=request.input_paths,
                    item_scales=_item_scales_from_units(units),
                    logger=logger,
                )
            else:
                if job_input_path is None:
                    job_input_path = _resolve_job_input_path(
                        request=request,
                        temp_dir=Path(temp_dir),
                        logger=logger,
                        status_callback=status_callback,
                    )
                export_arranged_step(
                    job_input_path,
                    artifacts.placements_path,
                    artifacts.arranged_step_path,
                    scale=float(units.get("scale") or 1.0),
                    units_mode=request.step_units,
                    packing_mode=packing_mode,
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

            result = build_success_result(
                input_paths=request.input_paths,
                constraints=constraints,
                outcome=outcome,
                units=units,
            )
            write_result_json(result, artifacts.result_path)
            logger.info("Packing finished successfully")
            logger.info("Artifacts written to %s", artifacts.out_dir)
            _notify(status_callback, "Готово")
            return PackingRunResult(
                exit_code=0,
                out_dir=artifacts.out_dir,
                result_path=artifacts.result_path,
                placements_path=artifacts.placements_path,
                log_path=artifacts.log_path,
                preview_top_path=artifacts.preview_top_path if artifacts.preview_top_path.exists() else None,
                preview_side_path=artifacts.preview_side_path if artifacts.preview_side_path.exists() else None,
                preview_gif_path=preview_gif_path,
                result_data=result,
            )
    except DoesNotFitError as exc:
        return _build_failure_run_result(
            artifacts=artifacts,
            constraints=constraints,
            request=request,
            logger=logger,
            message=str(exc),
            exit_code=2,
            units=units,
            n_parts=len(parts),
            status_callback=status_callback,
            does_not_fit=True,
            packed_count=(len(outcome.placements) if outcome is not None else 0),
            unpacked_count=(max(0, len(parts) - len(outcome.placements)) if outcome is not None else len(parts)),
            used_extents=(outcome.used_extents if outcome is not None else None),
        )
    except (FileNotFoundError, RuntimeError, PackingError) as exc:
        return _build_failure_run_result(
            artifacts=artifacts,
            constraints=constraints,
            request=request,
            logger=logger,
            message=str(exc),
            exit_code=2,
            units=units,
            n_parts=len(parts),
            status_callback=status_callback,
            does_not_fit=False,
            packed_count=(len(outcome.placements) if outcome is not None else 0),
            unpacked_count=(0 if outcome is not None else len(parts)),
            used_extents=(outcome.used_extents if outcome is not None else None),
        )
    except Exception as exc:
        logger.exception("Unexpected error")
        return _build_failure_run_result(
            artifacts=artifacts,
            constraints=constraints,
            request=request,
            logger=logger,
            message=f"Unexpected error: {exc}",
            exit_code=3,
            units=units,
            n_parts=len(parts),
            status_callback=status_callback,
            does_not_fit=False,
            packed_count=(len(outcome.placements) if outcome is not None else 0),
            unpacked_count=(0 if outcome is not None else len(parts)),
            used_extents=(outcome.used_extents if outcome is not None else None),
        )
    finally:
        close_logger(logger)


def run_packing_job_in_subprocess(
    request: PackingRequest,
    event_queue: Any,
) -> None:
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
                message=f"Background worker failed: {exc}",
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
    constraints = _build_constraints(request)
    logger = build_logger(artifacts.log_path, with_console=with_console)

    try:
        _log_request(logger, request)
        return _build_failure_run_result(
            artifacts=artifacts,
            constraints=constraints,
            request=request,
            logger=logger,
            message=message,
            exit_code=2,
            units=units,
            n_parts=n_parts,
            status_callback=status_callback,
            does_not_fit=False,
            packed_count=0,
            unpacked_count=n_parts,
            used_extents=None,
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


def _build_constraints(request: PackingRequest) -> dict[str, Any]:
    return {
        "maxW": request.max_w,
        "maxH": request.max_h,
        "maxL": request.max_l,
        "gap": request.gap,
        "seed": request.seed,
        "flat_only": request.flat_only,
        "treat_input_as_single_item": request.treat_input_as_single_item,
        "copies": request.copies,
        "planar_rotation_step_deg": request.planar_rotation_step_deg,
        "packing_mode": _packing_mode(request),
    }


def _log_request(logger: Any, request: PackingRequest) -> None:
    logger.info("Starting packer")
    logger.info("Input count=%s", len(request.input_paths))
    for index, input_path in enumerate(request.input_paths, start=1):
        logger.info("Input[%d]=%s", index, input_path)
    logger.info(
        "Constraints: maxW=%s maxH=%s maxL=%s gap=%s scale=%s seed=%s stepUnits=%s flatOnly=%s treatInputAsSingleItem=%s copies=%s planarRotationStepDeg=%s",
        request.max_w,
        request.max_h,
        request.max_l,
        request.gap,
        request.scale,
        request.seed,
        request.step_units,
        request.flat_only,
        request.treat_input_as_single_item,
        request.copies,
        request.planar_rotation_step_deg,
    )
    if request.flat_only:
        logger.info("Flat-only orientation filtering enabled: part height must equal the minimal original dimension.")
    if request.treat_input_as_single_item:
        logger.info("Rigid-group extraction enabled: the full input STEP will be packed as one item.")
    if request.copies > 1:
        logger.info(
            "Rigid-group copy replication enabled: %d copies of the same input model will be packed.",
            request.copies,
        )
    if request.planar_rotation_step_deg > 0:
        logger.info(
            "Experimental planar rotation enabled: rigid items will sample in-plane angles every %s degrees.",
            request.planar_rotation_step_deg,
        )
    if _uses_multi_file_items(request):
        logger.info("Multi-file item mode enabled: each selected STEP file will be packed as one item.")


def _build_failure_run_result(
    *,
    artifacts: PackingArtifacts,
    constraints: dict[str, Any],
    request: PackingRequest,
    logger: Any,
    message: str,
    exit_code: int,
    units: dict[str, Any] | None,
    n_parts: int,
    status_callback: StatusCallback | None,
    does_not_fit: bool,
    packed_count: int,
    unpacked_count: int,
    used_extents: tuple[float, float, float] | None,
) -> PackingRunResult:
    logger.error(message)
    if does_not_fit:
        logger.info("Final verdict: DOES NOT FIT")
    _cleanup_failed_artifacts(artifacts=artifacts, does_not_fit=does_not_fit)
    result = build_failure_result(
        input_paths=request.input_paths,
        constraints=constraints,
        message=message,
        units=units,
        n_parts=n_parts,
        does_not_fit=does_not_fit,
        packed_count=packed_count,
        unpacked_count=unpacked_count,
        used_extents=used_extents,
    )
    write_result_json(result, artifacts.result_path)
    logger.info("Failure result written to %s", artifacts.result_path)
    _notify(status_callback, f"Ошибка: {message}")
    return PackingRunResult(
        exit_code=exit_code,
        out_dir=artifacts.out_dir,
        result_path=artifacts.result_path,
        placements_path=artifacts.placements_path,
        log_path=artifacts.log_path,
        preview_top_path=artifacts.preview_top_path if artifacts.preview_top_path.exists() else None,
        preview_side_path=artifacts.preview_side_path if artifacts.preview_side_path.exists() else None,
        preview_gif_path=artifacts.preview_gif_path if artifacts.preview_gif_path.exists() else None,
        result_data=result,
    )


def _notify(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback is not None:
        status_callback(message)


def _cleanup_failed_artifacts(*, artifacts: PackingArtifacts, does_not_fit: bool) -> None:
    artifacts.arranged_step_path.unlink(missing_ok=True)
    artifacts.preview_top_path.unlink(missing_ok=True)
    artifacts.preview_side_path.unlink(missing_ok=True)
    artifacts.preview_gif_path.unlink(missing_ok=True)
    if does_not_fit:
        artifacts.placements_path.unlink(missing_ok=True)


def _packing_mode(request: PackingRequest) -> PackingMode:
    if _uses_multi_file_items(request):
        return "multi_root_shapes"
    return "single_root_shape" if request.treat_input_as_single_item else "solids"


def _uses_multi_file_items(request: PackingRequest) -> bool:
    return len(request.input_paths) > 1


def _resolve_job_input_path(
    *,
    request: PackingRequest,
    temp_dir: Path,
    logger: Any,
    status_callback: StatusCallback | None,
) -> Path:
    if len(request.input_paths) == 1:
        return request.input_paths[0]

    merged_input_path = temp_dir / "combined_input.step"
    _notify(status_callback, "Подготовка STEP-файлов...")
    merge_step_files(
        request.input_paths,
        merged_input_path,
        logger=logger,
    )
    logger.info(
        "Prepared merged STEP source from %d files: %s",
        len(request.input_paths),
        merged_input_path,
    )
    return merged_input_path


def _item_scales_from_units(units: dict[str, Any] | None) -> tuple[float, ...]:
    source_units = list((units or {}).get("source_units") or [])
    if not source_units:
        return ()
    return tuple(float(item.get("scale") or 1.0) for item in source_units)


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


def _validate_request_modes(request: PackingRequest) -> None:
    if request.copies > 1 and not request.treat_input_as_single_item:
        raise RuntimeError("--copies requires --treat-input-as-single-item.")
    if request.copies > 1 and _uses_multi_file_items(request):
        raise RuntimeError("--copies is not supported when multiple input STEP files are provided.")
    if request.planar_rotation_step_deg > 0 and not request.treat_input_as_single_item:
        raise RuntimeError("--planar-rotation-step-deg requires --treat-input-as-single-item.")
    if request.planar_rotation_step_deg > 0 and not request.flat_only:
        raise RuntimeError("--planar-rotation-step-deg requires --flat-only.")


def _expand_requested_copies(
    parts: list[Part],
    *,
    request: PackingRequest,
) -> list[Part]:
    if request.copies == 1 or not request.treat_input_as_single_item:
        return list(parts)
    if len(parts) != 1:
        raise RuntimeError(
            f"Expected exactly one rigid item before copy expansion, got {len(parts)}."
        )
    return build_rigid_group_copy_parts(parts[0], request.copies)


def _validate_outcome_within_request(
    *,
    outcome: Any,
    request: PackingRequest,
    constraints: dict[str, Any],
    logger: Any,
) -> dict[str, Any]:
    placements = list(outcome.placements)
    fit_verdict = validate_constraints(outcome, constraints)
    _log_fit_verdict(logger=logger, constraints=constraints, fit_verdict=fit_verdict)
    if not fit_verdict["fits"]:
        raise DoesNotFitError(_fit_verdict_message(fit_verdict))

    actual_length = int(fit_verdict["used_extents_mm"]["L"])
    actual_width = int(fit_verdict["used_extents_mm"]["W"])
    actual_height = int(fit_verdict["used_extents_mm"]["H"])
    allowed_length = ceil_mm(request.max_l) if request.max_l is not None else None
    allowed_width = ceil_mm(request.max_w)
    allowed_height = ceil_mm(request.max_h)

    for placement in placements:
        if placement.x < request.gap - EPS or placement.y < request.gap - EPS or placement.z < request.gap - EPS:
            raise RuntimeError(f"Placement {placement.part_id} violates the minimum wall gap.")
        if request.max_l is not None and placement.x + placement.dx > request.max_l - request.gap + EPS:
            raise DoesNotFitError(_limit_exceeded_message("L", actual_length, int(allowed_length)))
        if placement.y + placement.dy > request.max_w - request.gap + EPS:
            raise DoesNotFitError(_limit_exceeded_message("W", actual_width, allowed_width))
        if placement.z + placement.dz > request.max_h - request.gap + EPS:
            raise DoesNotFitError(_limit_exceeded_message("H", actual_height, allowed_height))
        if request.flat_only and abs(placement.dz - min(placement.part.dims)) > EPS:
            raise RuntimeError(f"Placement {placement.part_id} violates the flat-only constraint.")
    return fit_verdict


def _log_fit_verdict(
    *,
    logger: Any,
    constraints: dict[str, Any],
    fit_verdict: dict[str, Any],
) -> None:
    active_constraints: list[str] = []
    for axis, key in (("L", "maxL"), ("W", "maxW"), ("H", "maxH")):
        maximum = constraints.get(key)
        if isinstance(maximum, (int, float)):
            active_constraints.append(f"{axis}<={ceil_mm(float(maximum))}")
    logger.info("Active constraints: %s", ", ".join(active_constraints) if active_constraints else "none")

    actual_extents = fit_verdict["used_extents_mm"]
    if all(actual_extents.get(axis) is not None for axis in ("L", "W", "H")):
        logger.info(
            "Actual packed extents: L=%s, W=%s, H=%s",
            actual_extents["L"],
            actual_extents["W"],
            actual_extents["H"],
        )

    for violation in fit_verdict["violations"]:
        logger.error(
            "Constraint violation: %s exceeds by %s mm (actual=%s, max=%s)",
            violation["axis"],
            violation["excess"],
            violation["actual"],
            violation["max"],
        )

    logger.info("Final verdict: %s", "FITS" if fit_verdict["fits"] else "DOES NOT FIT")


def _fit_verdict_message(fit_verdict: dict[str, Any]) -> str:
    return format_constraint_failure_message(fit_verdict)
