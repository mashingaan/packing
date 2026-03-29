from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from packing_mvp.utils import Part, SourceSolid

DEFAULT_TRUCK_LENGTH_MM = 13400.0
DEFAULT_TRUCK_WIDTH_MM = 2350.0
DEFAULT_TRUCK_HEIGHT_MM = 2400.0
DEFAULT_GAP_MM = 50.0


@dataclass(frozen=True)
class TruckConfig:
    length_mm: float = DEFAULT_TRUCK_LENGTH_MM
    width_mm: float = DEFAULT_TRUCK_WIDTH_MM
    height_mm: float = DEFAULT_TRUCK_HEIGHT_MM
    gap_mm: float = DEFAULT_GAP_MM

    def __post_init__(self) -> None:
        for field_name in ("length_mm", "width_mm", "height_mm"):
            value = float(getattr(self, field_name))
            if value <= 0:
                raise ValueError(f"{field_name} must be positive.")
            object.__setattr__(self, field_name, value)
        gap_value = float(self.gap_mm)
        if gap_value < 0:
            raise ValueError("gap_mm must be non-negative.")
        object.__setattr__(self, "gap_mm", gap_value)

    @property
    def dims_mm(self) -> tuple[float, float, float]:
        return (self.length_mm, self.width_mm, self.height_mm)

    def to_dict(self) -> dict[str, float]:
        return {
            "length_mm": self.length_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "gap_mm": self.gap_mm,
        }


@dataclass(frozen=True)
class CatalogItem:
    item_id: str
    filename: str
    source_path: str
    detected_dims_mm: tuple[float, float, float]
    dimensions_mm: tuple[float, float, float]
    source_kind: Literal["step", "manual"] = "step"
    quantity: int = 1
    manual_override: bool = False
    source_scale: float = 1.0
    manual_scale: float = 1.0
    auto_scale_applied: bool = False
    auto_scale_factor: float | None = None
    raw_max_dim: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "detected_dims_mm", _normalize_dims(self.detected_dims_mm))
        object.__setattr__(self, "dimensions_mm", _normalize_dims(self.dimensions_mm))
        if self.quantity < 1:
            raise ValueError("quantity must be at least 1.")
        if not self.item_id:
            raise ValueError("item_id is required.")
        if self.source_kind not in {"step", "manual"}:
            raise ValueError(f"Unsupported source_kind: {self.source_kind}")
        if not self.filename:
            object.__setattr__(self, "filename", Path(self.source_path).name)

    @property
    def path(self) -> Path:
        return Path(self.source_path)

    @property
    def dims_mm(self) -> tuple[float, float, float]:
        return self.dimensions_mm

    @property
    def display_name(self) -> str:
        return self.filename or self.path.name or self.item_id

    @property
    def is_manual(self) -> bool:
        return self.source_kind == "manual"

    def with_name(self, name: str) -> "CatalogItem":
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("filename is required.")
        return CatalogItem(
            item_id=self.item_id,
            filename=normalized_name,
            source_path=self.source_path,
            source_kind=self.source_kind,
            detected_dims_mm=self.detected_dims_mm,
            dimensions_mm=self.dimensions_mm,
            quantity=self.quantity,
            manual_override=self.manual_override,
            source_scale=self.source_scale,
            manual_scale=self.manual_scale,
            auto_scale_applied=self.auto_scale_applied,
            auto_scale_factor=self.auto_scale_factor,
            raw_max_dim=self.raw_max_dim,
        )

    def with_dimensions(self, dims_mm: Iterable[float]) -> "CatalogItem":
        normalized = _normalize_dims(tuple(dims_mm))
        return CatalogItem(
            item_id=self.item_id,
            filename=self.filename,
            source_path=self.source_path,
            source_kind=self.source_kind,
            detected_dims_mm=self.detected_dims_mm,
            dimensions_mm=normalized,
            quantity=self.quantity,
            manual_override=normalized != self.detected_dims_mm,
            source_scale=self.source_scale,
            manual_scale=self.manual_scale,
            auto_scale_applied=self.auto_scale_applied,
            auto_scale_factor=self.auto_scale_factor,
            raw_max_dim=self.raw_max_dim,
        )

    def with_quantity(self, quantity: int) -> "CatalogItem":
        return CatalogItem(
            item_id=self.item_id,
            filename=self.filename,
            source_path=self.source_path,
            source_kind=self.source_kind,
            detected_dims_mm=self.detected_dims_mm,
            dimensions_mm=self.dimensions_mm,
            quantity=int(quantity),
            manual_override=self.manual_override,
            source_scale=self.source_scale,
            manual_scale=self.manual_scale,
            auto_scale_applied=self.auto_scale_applied,
            auto_scale_factor=self.auto_scale_factor,
            raw_max_dim=self.raw_max_dim,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "filename": self.filename,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "detected_dims_mm": list(self.detected_dims_mm),
            "dimensions_mm": list(self.dimensions_mm),
            "quantity": self.quantity,
            "manual_override": self.manual_override,
            "source_scale": self.source_scale,
            "manual_scale": self.manual_scale,
            "auto_scale_applied": self.auto_scale_applied,
            "auto_scale_factor": self.auto_scale_factor,
            "raw_max_dim": self.raw_max_dim,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogItem":
        source_path = str(data.get("source_path") or "")
        return cls(
            item_id=str(data.get("item_id") or ""),
            filename=str(data.get("filename") or ""),
            source_path=source_path,
            source_kind=str(data.get("source_kind") or ("manual" if not source_path else "step")),
            detected_dims_mm=_normalize_dims(data.get("detected_dims_mm") or (0.0, 0.0, 0.0)),
            dimensions_mm=_normalize_dims(data.get("dimensions_mm") or data.get("detected_dims_mm") or (0.0, 0.0, 0.0)),
            quantity=int(data.get("quantity") or 1),
            manual_override=bool(data.get("manual_override")),
            source_scale=float(data.get("source_scale") or 1.0),
            manual_scale=float(data.get("manual_scale") or 1.0),
            auto_scale_applied=bool(data.get("auto_scale_applied")),
            auto_scale_factor=(
                float(data["auto_scale_factor"])
                if data.get("auto_scale_factor") is not None
                else None
            ),
            raw_max_dim=float(data["raw_max_dim"]) if data.get("raw_max_dim") is not None else None,
        )

    @classmethod
    def from_manual_box(
        cls,
        *,
        item_id: str,
        name: str,
        dims_mm: Iterable[float],
        quantity: int = 1,
    ) -> "CatalogItem":
        normalized_dims = _normalize_dims(dims_mm)
        return cls(
            item_id=item_id,
            filename=str(name).strip(),
            source_path="",
            source_kind="manual",
            detected_dims_mm=normalized_dims,
            dimensions_mm=normalized_dims,
            quantity=quantity,
            manual_override=False,
            source_scale=1.0,
            manual_scale=1.0,
            auto_scale_applied=False,
            auto_scale_factor=None,
            raw_max_dim=max(normalized_dims),
        )


@dataclass(frozen=True)
class PackProject:
    items: tuple[CatalogItem, ...]
    truck: TruckConfig = TruckConfig()
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_version": 3,
            "truck": self.truck.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackProject":
        truck_data = data.get("truck") or {}
        items_data = data.get("items") or []
        return cls(
            items=tuple(CatalogItem.from_dict(item) for item in items_data),
            truck=TruckConfig(
                length_mm=float(truck_data.get("length_mm") or DEFAULT_TRUCK_LENGTH_MM),
                width_mm=float(truck_data.get("width_mm") or DEFAULT_TRUCK_WIDTH_MM),
                height_mm=float(truck_data.get("height_mm") or DEFAULT_TRUCK_HEIGHT_MM),
                gap_mm=float(truck_data.get("gap_mm") or DEFAULT_GAP_MM),
            ),
            result=data.get("result") if isinstance(data.get("result"), dict) else None,
        )


def catalog_item_to_parts(item: CatalogItem) -> list[Part]:
    parts: list[Part] = []
    dims = item.dimensions_mm
    bbox_min = (0.0, 0.0, 0.0)
    bbox_max = dims
    source_solid = SourceSolid(tag=_source_tag_for_item(item.item_id), bbox_min=bbox_min, bbox_max=bbox_max)
    volume = dims[0] * dims[1] * dims[2]
    for copy_index in range(item.quantity):
        part_id = f"{item.item_id}_copy_{copy_index + 1:03d}"
        parts.append(
            Part(
                part_id=part_id,
                solid_tag=None,
                dims=dims,
                volume=volume,
                bbox_min=bbox_min,
                bbox_max=bbox_max,
                mode="rigid_group",
                source_solids=(source_solid,),
                source_part_id=item.item_id,
                copy_index=copy_index,
                source_path=item.source_path,
                display_name=item.display_name,
                metadata=(
                    ("filename", item.filename),
                    ("manual_override", item.manual_override),
                    ("source_kind", item.source_kind),
                ),
            )
        )
    return parts


def build_parts_from_catalog(items: Iterable[CatalogItem]) -> list[Part]:
    parts: list[Part] = []
    for item in items:
        parts.extend(catalog_item_to_parts(item))
    return parts


def total_requested_items(items: Iterable[CatalogItem]) -> int:
    return sum(item.quantity for item in items)


def _normalize_dims(values: Iterable[float]) -> tuple[float, float, float]:
    dims = tuple(float(value) for value in values)
    if len(dims) != 3:
        raise ValueError("Three dimensions are required.")
    if any(value <= 0 for value in dims):
        raise ValueError("All dimensions must be positive.")
    return dims


def _source_tag_for_item(item_id: str) -> int:
    digits = "".join(ch for ch in item_id if ch.isdigit())
    return max(1, int(digits or "1"))
