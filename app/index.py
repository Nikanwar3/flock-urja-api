"""The local query layer.

The portal can only list meters (paged, filtered by a single free-text
`q`) or list DTs. It cannot answer "give me every faulty three-phase meter
in Circle 3" or "what's near this point" in one call. Since the whole
dataset is ~400 meters and ~40 transformers, we hold a normalised copy in
memory (refreshed on a TTL — see cache.py / main.py) and answer richer
queries against that copy instead of the portal.

This is the "local index / query layer" extension: it trades staleness
(bounded by the cache TTL) for query power the source system doesn't have.
At this scale (hundreds of rows) a linear scan per query is entirely
fine — see README "What I'd improve" for where that stops being true.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from app.models import (
    GeoPoint,
    HierarchyDataQualityIssue,
    HierarchyNode,
    HierarchyRef,
    HierarchyTree,
    Meter,
    MeterHierarchy,
    MeterSummary,
    NearbyMeter,
    Transformer,
)

_HIERARCHY_LEVELS = ["zone", "circle", "division", "subdivision", "substation", "feeder"]


def _ref(node: dict | None) -> HierarchyRef | None:
    if not node:
        return None
    code, name = node.get("code"), node.get("name")
    # The portal represents "missing" as an empty string rather than
    # omitting the key — normalise both to None (see PROTOCOL.md).
    if not code or not name:
        return None
    return HierarchyRef(code=code, name=name)


def normalize_meter(raw: dict) -> Meter:
    h = raw.get("hierarchy") or {}
    hierarchy = MeterHierarchy(**{level: _ref(h.get(level)) for level in [*_HIERARCHY_LEVELS, "dt"]})
    complete = all(getattr(hierarchy, level) is not None for level in [*_HIERARCHY_LEVELS, "dt"])

    geo = None
    raw_geo = raw.get("geo")
    if raw_geo and raw_geo.get("lat") is not None and raw_geo.get("lng") is not None:
        geo = GeoPoint(lat=raw_geo["lat"], lng=raw_geo["lng"])

    return Meter(
        meter_id=raw["meterId"],
        serial_no=raw["serialNo"],
        make=raw["make"],
        phase_type=raw["phaseType"],
        install_status=raw["installStatus"],
        dt_code=raw.get("dtCode") or None,
        install_type=raw["installType"],
        build=raw["build"],
        hierarchy=hierarchy,
        geo=geo,
        hierarchy_complete=complete,
    )


def to_summary(meter: Meter) -> MeterSummary:
    return MeterSummary(
        meter_id=meter.meter_id,
        serial_no=meter.serial_no,
        make=meter.make,
        phase_type=meter.phase_type,
        install_status=meter.install_status,
        dt_code=meter.dt_code,
    )


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class MeterIndex:
    """Normalised, queryable snapshot of the portal's meter dataset."""

    def __init__(self, raw_meters: list[dict]):
        self.meters: list[Meter] = [normalize_meter(m) for m in raw_meters]
        self._by_id: dict[str, Meter] = {m.meter_id: m for m in self.meters}

    def __len__(self) -> int:
        return len(self.meters)

    def get(self, meter_id: str) -> Meter | None:
        return self._by_id.get(meter_id)

    def search(
        self,
        *,
        q: str | None = None,
        install_status: str | None = None,
        phase_type: str | None = None,
        make: str | None = None,
        install_type: str | None = None,
        dt_code: str | None = None,
        zone: str | None = None,
        circle: str | None = None,
        division: str | None = None,
        subdivision: str | None = None,
        substation: str | None = None,
        feeder: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Meter], int]:
        results = self.meters

        if q:
            needle = q.lower()
            results = [m for m in results if needle in m.meter_id.lower() or needle in m.serial_no.lower()]
        if install_status:
            results = [m for m in results if m.install_status.value == install_status]
        if phase_type:
            results = [m for m in results if m.phase_type.value == phase_type]
        if make:
            results = [m for m in results if m.make.lower() == make.lower()]
        if install_type:
            results = [m for m in results if m.install_type.value == install_type]
        if dt_code:
            results = [m for m in results if m.dt_code == dt_code]
        for level, value in (
            ("zone", zone),
            ("circle", circle),
            ("division", division),
            ("subdivision", subdivision),
            ("substation", substation),
            ("feeder", feeder),
        ):
            if value:
                results = [m for m in results if getattr(m.hierarchy, level) and getattr(m.hierarchy, level).code == value]

        total = len(results)
        start = (page - 1) * page_size
        return results[start : start + page_size], total

    def nearby(self, lat: float, lng: float, radius_km: float | None, limit: int) -> list[NearbyMeter]:
        scored = []
        for m in self.meters:
            if m.geo is None:
                continue
            distance = _haversine_km(lat, lng, m.geo.lat, m.geo.lng)
            if radius_km is None or distance <= radius_km:
                scored.append((distance, m))
        scored.sort(key=lambda pair: pair[0])
        if limit:
            scored = scored[:limit]
        return [NearbyMeter(meter=to_summary(m), distance_km=round(d, 3)) for d, m in scored]


def build_transformers(raw_dts: list[dict], meter_index: MeterIndex) -> list[Transformer]:
    status_counts: dict[str, Counter] = defaultdict(Counter)
    for m in meter_index.meters:
        if m.dt_code:
            status_counts[m.dt_code][m.install_status.value] += 1

    out = []
    for dt in raw_dts:
        counts = status_counts.get(dt["code"], Counter())
        out.append(
            Transformer(
                code=dt["code"],
                name=dt["name"],
                feeder_code=dt["feederCode"],
                capacity_kva=dt["capacityKva"],
                meter_count=sum(counts.values()),
                status_breakdown=dict(counts),
            )
        )
    return out


def _majority_ref(refs: list[HierarchyRef | None]) -> HierarchyRef | None:
    present = [r for r in refs if r is not None]
    if not present:
        return None
    counts = Counter((r.code, r.name) for r in present)
    (code, name), _ = counts.most_common(1)[0]
    return HierarchyRef(code=code, name=name)


def build_hierarchy_tree(meter_index: MeterIndex) -> HierarchyTree:
    """Reconstruct the zone -> ... -> DT tree from per-meter hierarchy data.

    Real-world wrinkle (see PROTOCOL.md): ~5% of meters are missing one or
    more hierarchy levels, and a handful of DTs have meters that disagree
    on the upstream path *because* some of those meters are missing a
    level, not because the utility genuinely has two paths to one DT. We
    resolve each DT to the majority (most common, non-missing) value at
    each level and record the disagreement as a data-quality issue rather
    than silently picking one and hiding the discrepancy.
    """
    meters_by_dt: dict[str, list[Meter]] = defaultdict(list)
    for m in meter_index.meters:
        dt_code = m.hierarchy.dt.code if m.hierarchy.dt else m.dt_code
        if dt_code:
            meters_by_dt[dt_code].append(m)

    issues: list[HierarchyDataQualityIssue] = []
    dt_paths: dict[str, dict[str, HierarchyRef | None]] = {}

    for dt_code, dt_meters in meters_by_dt.items():
        path: dict[str, HierarchyRef | None] = {}
        for level in _HIERARCHY_LEVELS:
            refs = [getattr(m.hierarchy, level) for m in dt_meters]
            path[level] = _majority_ref(refs)
            distinct_codes = {r.code for r in refs if r is not None}
            missing_count = sum(1 for r in refs if r is None)
            if len(distinct_codes) > 1 or missing_count:
                bits = []
                if len(distinct_codes) > 1:
                    bits.append(f"disagreeing values {sorted(distinct_codes)}")
                if missing_count:
                    bits.append(f"{missing_count}/{len(dt_meters)} meter(s) missing this level")
                issues.append(
                    HierarchyDataQualityIssue(
                        dt_code=dt_code,
                        description=f"{level}: " + "; ".join(bits),
                    )
                )
        path["dt"] = _majority_ref([m.hierarchy.dt for m in dt_meters])
        dt_paths[dt_code] = path

    # Nested-dict tree, then convert to HierarchyNode bottom-up so parent
    # meter_count is always the sum of its children.
    root: dict = {}
    for dt_code, path in dt_paths.items():
        node = root
        for level in _HIERARCHY_LEVELS:
            ref = path[level]
            key = ref.code if ref else f"unknown-{level}"
            name = ref.name if ref else f"(unknown {level})"
            node = node.setdefault(key, {"name": name, "level": level, "children": {}})["children"]
        dt_ref = path["dt"]
        key = dt_ref.code if dt_ref else dt_code
        name = dt_ref.name if dt_ref else dt_code
        node[key] = {"name": name, "level": "dt", "children": {}, "meter_count": len(meters_by_dt[dt_code])}

    def to_node(code: str, data: dict) -> HierarchyNode:
        children = sorted((to_node(k, v) for k, v in data["children"].items()), key=lambda n: n.code)
        meter_count = data.get("meter_count")
        if meter_count is None:
            meter_count = sum(c.meter_count for c in children)
        return HierarchyNode(code=code, name=data["name"], level=data["level"], meter_count=meter_count, children=children)

    zones = sorted((to_node(code, data) for code, data in root.items()), key=lambda n: n.code)

    return HierarchyTree(
        generated_at=datetime.now(timezone.utc),
        total_meters=len(meter_index),
        zones=zones,
        data_quality_issues=issues,
    )
