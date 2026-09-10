"""Turning raw /portal/meters/{id}/energy readings into something useful.

The portal hands back a list of half-open register snapshots: `kwh`/`kvah`
are *cumulative* energy-meter register values (they only go up), not
per-interval usage, and every numeric field arrives as a string. This
module does the normalisation and the one bit of derived math (consumption
= last reading - first reading) that the portal itself doesn't provide.
"""
from __future__ import annotations

from datetime import datetime

from app.models import ConsumptionReading, ConsumptionResolution, ConsumptionSummary, MeterConsumption

_TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M"

# Observed cluster boundary between the two reading cadences the portal
# actually returns (~30 min vs ~24h apart) — see PROTOCOL.md "Consumption
# data" for how inconsistent this is across meters.
_SUB_HOURLY_THRESHOLD_SECONDS = 3600


def _parse_float(value: str | None) -> float | None:
    if value in (None, "", "—"):
        return None
    return float(value)


def parse_reading(raw: dict) -> ConsumptionReading:
    return ConsumptionReading(
        # The portal gives no timezone; we treat it as a naive local
        # timestamp rather than guessing an offset (see README "Assumptions").
        timestamp=datetime.strptime(raw["timestamp"], _TIMESTAMP_FORMAT),
        kwh=float(raw["kwh"]),
        kvah=float(raw["kvah"]),
        volt_r=_parse_float(raw.get("voltR")),
    )


def _infer_resolution(sorted_readings: list[ConsumptionReading]) -> ConsumptionResolution:
    if len(sorted_readings) < 2:
        return ConsumptionResolution.unknown
    gaps = sorted(
        (b.timestamp - a.timestamp).total_seconds()
        for a, b in zip(sorted_readings, sorted_readings[1:])
    )
    median_gap = gaps[len(gaps) // 2]
    return (
        ConsumptionResolution.sub_hourly
        if median_gap <= _SUB_HOURLY_THRESHOLD_SECONDS
        else ConsumptionResolution.daily
    )


def build_consumption(meter_id: str, raw_readings: list[dict]) -> MeterConsumption:
    readings = sorted((parse_reading(r) for r in raw_readings), key=lambda r: r.timestamp)
    volt_values = [r.volt_r for r in readings if r.volt_r is not None]

    summary = ConsumptionSummary(
        reading_count=len(readings),
        resolution=_infer_resolution(readings),
        first_timestamp=readings[0].timestamp if readings else None,
        last_timestamp=readings[-1].timestamp if readings else None,
        kwh_consumed=round(readings[-1].kwh - readings[0].kwh, 3) if len(readings) >= 2 else None,
        kvah_consumed=round(readings[-1].kvah - readings[0].kvah, 3) if len(readings) >= 2 else None,
        avg_volt_r=round(sum(volt_values) / len(volt_values), 2) if volt_values else None,
        min_volt_r=min(volt_values) if volt_values else None,
        max_volt_r=max(volt_values) if volt_values else None,
    )
    return MeterConsumption(meter_id=meter_id, summary=summary, readings=readings)
