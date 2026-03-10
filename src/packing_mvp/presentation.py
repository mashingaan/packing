from __future__ import annotations

from typing import Any

SUCCESS_BANNER = "success"
NO_FIT_BANNER = "no_fit"
ERROR_BANNER = "error"


def result_is_successful_fit(result_data: dict[str, Any]) -> bool:
    fits = result_data.get("fits")
    if isinstance(fits, bool):
        return result_data.get("status") == "ok" and fits
    return (
        result_data.get("status") == "ok"
        and not result_data.get("does_not_fit")
        and not _result_violations(result_data)
    )


def result_is_constraint_failure(result_data: dict[str, Any]) -> bool:
    if result_data.get("does_not_fit"):
        return True
    if _result_violations(result_data):
        return True

    fits = result_data.get("fits")
    if result_data.get("status") == "ok" and fits is False:
        return True

    error_text = str(result_data.get("error") or "").lower()
    return (
        "do not fit" in error_text
        or "does not fit" in error_text
        or "packing failed" in error_text
        or "feasible packing" in error_text
        or "width/height" in error_text
        or "не помещ" in error_text
    )


def get_result_banner(*, exit_code: int, result_data: dict[str, Any]) -> str:
    if exit_code == 0 and result_is_successful_fit(result_data):
        return SUCCESS_BANNER
    if result_is_constraint_failure(result_data):
        return NO_FIT_BANNER
    return ERROR_BANNER


def format_result_summary(result_data: dict[str, Any]) -> str:
    stats = result_data.get("stats") or {}
    n_parts = _as_int(stats.get("n_parts"))

    if result_is_successful_fit(result_data):
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
                    "детали укладываются только плашмя, когда высота равна минимальному исходному габариту"
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

    error_text = str(result_data.get("error") or "").strip()
    if not error_text and result_is_constraint_failure(result_data):
        error_text = _constraint_failure_text(result_data)
    if not error_text:
        error_text = "Неизвестная ошибка"

    lines = [
        "Не удалось уложить детали",
        f"Причина: {error_text}",
    ]
    violations = _result_violations(result_data)
    if violations:
        for violation in violations:
            lines.append(
                "Превышен лимит: "
                f"{violation.get('axis')} = {_as_int(violation.get('actual'))} / "
                f"{_as_int(violation.get('max'))} мм, "
                f"+{_as_int(violation.get('excess'))} мм"
            )
    lines.append(f"Деталей: {n_parts}")
    return "\n".join(lines)


def _result_violations(result_data: dict[str, Any]) -> list[dict[str, Any]]:
    violations = result_data.get("violations")
    if isinstance(violations, list):
        return [item for item in violations if isinstance(item, dict)]

    limit_exceeded = result_data.get("limit_exceeded")
    if isinstance(limit_exceeded, dict) and limit_exceeded:
        return [limit_exceeded]
    return []


def _constraint_failure_text(result_data: dict[str, Any]) -> str:
    violations = _result_violations(result_data)
    if not violations:
        return "Не помещается"
    return "; ".join(_format_violation_text(violation) for violation in violations)


def _format_violation_text(violation: dict[str, Any]) -> str:
    axis_names = {
        "L": "длина",
        "W": "ширина",
        "H": "высота",
    }
    axis = str(violation.get("axis") or "")
    axis_name = axis_names.get(axis, axis)
    actual = _as_int(violation.get("actual"))
    maximum = _as_int(violation.get("max"))
    excess = _as_int(violation.get("excess"))
    return (
        f"Не помещается: расчетная {axis_name} {actual} мм "
        f"превышает допустимые {maximum} мм на {excess} мм"
    )


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
