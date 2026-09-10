"""Pydantic response models for our clean API.

These are deliberately *not* the portal's own shapes — field names are
normalised to snake_case, ambiguous portal fields are typed properly
(numeric strings -> float, dd/mm/yyyy strings -> datetime), and a couple of
fields are computed rather than passed through (e.g. `resolution`,
`hierarchy_complete`).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class InstallStatus(str, Enum):
    installed = "Installed"
    faulty = "Faulty"
    decommissioned = "Decommissioned"


class PhaseType(str, Enum):
    single = "single"
    three = "three"


class InstallType(str, Enum):
    ct_operated = "CT Operated"
    whole_current = "Whole Current"


class HierarchyRef(BaseModel):
    code: str
    name: str


class MeterHierarchy(BaseModel):
    """The network path from a meter up to its zone.

    Any level can legitimately be `None` — see PROTOCOL.md: ~5% of meters in
    the source data are missing one or more levels (empty string in the
    portal's own payload). We normalise "" to None rather than pretending
    the utility has no gaps.
    """

    zone: HierarchyRef | None = None
    circle: HierarchyRef | None = None
    division: HierarchyRef | None = None
    subdivision: HierarchyRef | None = None
    substation: HierarchyRef | None = None
    feeder: HierarchyRef | None = None
    dt: HierarchyRef | None = None


class GeoPoint(BaseModel):
    lat: float
    lng: float


class MeterSummary(BaseModel):
    """Row shape used in list/search results — cheap fields only."""

    meter_id: str
    serial_no: str
    make: str
    phase_type: PhaseType
    install_status: InstallStatus
    dt_code: str | None = None


class Meter(MeterSummary):
    """Full meter record, as reconstructed from the portal's bulk export."""

    install_type: InstallType
    build: str
    hierarchy: MeterHierarchy
    geo: GeoPoint | None = None
    hierarchy_complete: bool = Field(
        description="False if any level of `hierarchy` was missing in the source data."
    )


class PaginatedMeters(BaseModel):
    data: list[MeterSummary]
    total: int
    page: int
    page_size: int


class ConsumptionReading(BaseModel):
    timestamp: datetime = Field(
        description="Naive local timestamp as reported by the portal (no timezone given — see PROTOCOL.md)."
    )
    kwh: float = Field(description="Cumulative active-energy register reading, not an interval delta.")
    kvah: float = Field(description="Cumulative apparent-energy register reading, not an interval delta.")
    volt_r: float | None = Field(default=None, description="R-phase voltage at the time of the reading.")


class ConsumptionResolution(str, Enum):
    sub_hourly = "sub_hourly"
    daily = "daily"
    unknown = "unknown"


class ConsumptionSummary(BaseModel):
    reading_count: int
    resolution: ConsumptionResolution = Field(
        description=(
            "Inferred from the median gap between readings. The portal returns wildly "
            "different granularities per meter for no metadata-visible reason (see "
            "PROTOCOL.md) so callers should not assume a fixed interval."
        )
    )
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    kwh_consumed: float | None = Field(
        default=None, description="last.kwh - first.kwh over the returned window."
    )
    kvah_consumed: float | None = None
    avg_volt_r: float | None = None
    min_volt_r: float | None = None
    max_volt_r: float | None = None


class MeterConsumption(BaseModel):
    meter_id: str
    summary: ConsumptionSummary
    readings: list[ConsumptionReading]


class Transformer(BaseModel):
    """A distribution transformer (DT)."""

    code: str
    name: str
    feeder_code: str
    capacity_kva: float
    meter_count: int = 0
    status_breakdown: dict[str, int] = Field(default_factory=dict)


class PaginatedTransformers(BaseModel):
    data: list[Transformer]
    total: int
    page: int
    page_size: int


class HierarchyNode(BaseModel):
    code: str
    name: str
    level: str
    meter_count: int
    children: list["HierarchyNode"] = Field(default_factory=list)


class HierarchyDataQualityIssue(BaseModel):
    dt_code: str
    description: str


class HierarchyTree(BaseModel):
    generated_at: datetime
    total_meters: int
    zones: list[HierarchyNode]
    data_quality_issues: list[HierarchyDataQualityIssue] = Field(default_factory=list)


class NearbyMeter(BaseModel):
    meter: MeterSummary
    distance_km: float


class HealthStatus(BaseModel):
    status: str
    portal_reachable: bool
    session_active: bool
    meters_cache_age_seconds: float | None = None
    transformers_cache_age_seconds: float | None = None
