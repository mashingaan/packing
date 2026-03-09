from __future__ import annotations

from typing import Any

SUCCESS_BANNER = "success"
NO_FIT_BANNER = "no_fit"
ERROR_BANNER = "error"


def get_result_banner(*, exit_code: int, result_data: dict[str, Any]) -> str:
    if exit_code == 0 and result_data.get("status") == "ok" and not result_data.get("does_not_fit"):
        return SUCCESS_BANNER
    if result_data.get("does_not_fit") or result_data.get("limit_exceeded"):
        return NO_FIT_BANNER

    error_text = str(result_data.get("error") or "").lower()
    if (
        "do not fit" in error_text
        or "does not fit" in error_text
        or "packing failed" in error_text
        or "feasible packing" in error_text
        or "width/height" in error_text
        or "не помещ" in error_text
    ):
        return NO_FIT_BANNER
    return ERROR_BANNER


def format_result_summary(result_data: dict[str, Any]) -> str:
    stats = result_data.get("stats") or {}
    n_parts = _as_int(stats.get("n_parts"))

    if result_data.get("status") == "ok" and not result_data.get("does_not_fit"):
        dims = result_data.get("recommended_dims_mm") or {}
        constraints = result_data.get("constraints") or {}
        recommended_length = _as_float(dims.get("L"))
        recommended_width = _as_float(dims.get("W"))
        recommended_height = _as_float(dims.get("H"))
        reference_length = _as_float(constraints.get("maxL"))
        flat_only = bool(constraints.get("flat_only"))

        lines = ["Все детали помещаются"]
        if (
            recommended_length is not None
            and recommended_width is not None
            and recommended_height is not None
        ):
            lines.append(
                "Размеры ящика: "
                f"{_format_mm(recommended_length)} x {_format_mm(recommended_width)} x "
                f"{_format_mm(recommended_height)} мм"
            )
        elif recommended_length is not None:
            lines.append(f"Рекомендуемая длина: {_format_mm(recommended_length)} мм")
        if recommended_length is not None:
            if flat_only:
                lines.append(
                    f"{_format_mm(recommended_length)} мм относится только к длине; "
                    "детали укладываются только плашмя, когда высота равна "
                    "минимальному исходному габариту"
                )
            else:
                lines.append(
                    f"{_format_mm(recommended_length)} мм относится только к длине; "
                    "детали могут быть повернуты на 90° и уложены по ширине/высоте"
                )
        if recommended_length is not None and reference_length and reference_length > 0:
            usage_percent = round(recommended_length / reference_length * 100)
            lines.append(f"Использовано: {usage_percent}% длины")
        lines.append(f"Деталей: {n_parts}")
        return "\n".join(lines)

    error_text = str(result_data.get("error") or "Неизвестная ошибка")
    lines = [
        "Не удалось уложить детали",
        f"Причина: {error_text}",
    ]
    limit_exceeded = result_data.get("limit_exceeded") or {}
    if limit_exceeded:
        lines.append(
            "Превышен лимит: "
            f"{limit_exceeded.get('axis')} = {_as_int(limit_exceeded.get('actual'))} / "
            f"{_as_int(limit_exceeded.get('max'))} мм, "
            f"+{_as_int(limit_exceeded.get('excess'))} мм"
        )
    lines.append(f"Деталей: {n_parts}")
    return "\n".join(lines)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    return 0


def _format_mm(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"
