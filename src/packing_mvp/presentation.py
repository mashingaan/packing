from __future__ import annotations

from typing import Any

SUCCESS_BANNER = "success"
NO_FIT_BANNER = "no_fit"
ERROR_BANNER = "error"


def result_is_successful_fit(result_data: dict[str, Any]) -> bool:
    if result_data.get("success") is True:
        return True
    fits = result_data.get("fits")
    if fits is True:
        return bool(result_data.get("status") == "ok")
    if fits is False:
        return False
    return (
        result_data.get("status") == "ok"
        and not result_data.get("does_not_fit")
        and not _result_violations(result_data)
        and not result_data.get("unplaced_items")
    )


def result_is_constraint_failure(result_data: dict[str, Any]) -> bool:
    if result_data.get("does_not_fit"):
        return True
    if result_data.get("fits") is False:
        return True
    if _result_violations(result_data):
        return True
    return bool(result_data.get("unplaced_items"))


def get_result_banner(*, exit_code: int, result_data: dict[str, Any]) -> str:
    if exit_code == 0 and result_is_successful_fit(result_data):
        return SUCCESS_BANNER
    if result_is_constraint_failure(result_data):
        return NO_FIT_BANNER
    return ERROR_BANNER


def format_result_summary(result_data: dict[str, Any]) -> str:
    stats = result_data.get("stats") or {}
    total_items = _as_int(stats.get("n_parts"))
    packed = _as_int(result_data.get("packed_count", stats.get("packed")))
    unpacked = _as_int(result_data.get("unpacked_count", stats.get("unpacked")))
    truck = result_data.get("truck") or {}
    used = result_data.get("used_extents_mm") or {}

    if result_is_successful_fit(result_data):
        lines = ["Все грузовые места размещены внутри кузова."]
        if all(used.get(axis) is not None for axis in ("L", "W", "H")):
            lines.append(
                "Использованные габариты кузова (мм): "
                f"{_as_int(used['L'])} x {_as_int(used['W'])} x {_as_int(used['H'])}"
            )
        if all(truck.get(axis) is not None for axis in ("length_mm", "width_mm", "height_mm")):
            lines.append(
                "Ограничения кузова (мм): "
                f"{_as_int(truck['length_mm'])} x {_as_int(truck['width_mm'])} x {_as_int(truck['height_mm'])}"
            )
        fill_ratio = result_data.get("fill_ratio")
        if isinstance(fill_ratio, (int, float)):
            lines.append(f"Заполнение кузова: {float(fill_ratio) * 100:.1f}%")
        lines.append(f"Размещено мест: {packed}")
        return "\n".join(lines)

    error_text = str(result_data.get("error") or "").strip()
    if not error_text and _result_violations(result_data):
        error_text = _constraint_failure_text(result_data)
    if not error_text:
        error_text = "Расчёт укладки завершился ошибкой."

    lines = [
        "Не все грузовые места помещаются в кузов.",
        f"Причина: {error_text}",
    ]
    if packed:
        lines.append(f"Размещено мест: {packed}")
    if unpacked:
        lines.append(f"Неразмещено мест: {unpacked}")
    unplaced_items = result_data.get("unplaced_items")
    if isinstance(unplaced_items, list) and unplaced_items:
        details = ", ".join(
            f"{item.get('name', item.get('item_id', 'item'))} x{_as_int(item.get('quantity'))}"
            for item in unplaced_items
            if isinstance(item, dict)
        )
        if details:
            lines.append(f"Список неразмещённых: {details}")
    violations = _result_violations(result_data)
    if violations:
        for violation in violations:
            lines.append(
                "Превышение габарита кузова: "
                f"{violation.get('axis')} = {_as_int(violation.get('actual'))} / "
                f"{_as_int(violation.get('max'))} mm, "
                f"+{_as_int(violation.get('excess'))} mm"
            )
    lines.append(f"Запрошено всего: {total_items}")
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
        return "Превышены ограничения кузова."
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
    return f"Габарит кузова по оси «{axis_name}»: {actual} мм вместо {maximum} мм, превышение {excess} мм"


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    return 0
