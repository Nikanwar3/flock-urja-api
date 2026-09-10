from app.consumption import build_consumption
from app.models import ConsumptionResolution

HALF_HOURLY = [
    {"timestamp": "23/06/2026 23:30", "kwh": "100.00", "kvah": "110.00", "voltR": "230"},
    {"timestamp": "24/06/2026 00:00", "kwh": "100.50", "kvah": "110.60", "voltR": "228"},
    {"timestamp": "24/06/2026 00:30", "kwh": "101.00", "kvah": "111.10", "voltR": "231"},
]

DAILY = [
    {"timestamp": "23/06/2026 00:00", "kwh": "1000.0", "kvah": "1100.0", "voltR": "225"},
    {"timestamp": "24/06/2026 00:00", "kwh": "1042.0", "kvah": "1150.0", "voltR": "227"},
]


def test_resolution_inferred_sub_hourly():
    result = build_consumption("M1", HALF_HOURLY)
    assert result.summary.resolution == ConsumptionResolution.sub_hourly
    assert result.summary.reading_count == 3


def test_resolution_inferred_daily():
    result = build_consumption("M1", DAILY)
    assert result.summary.resolution == ConsumptionResolution.daily


def test_single_reading_resolution_unknown():
    result = build_consumption("M1", HALF_HOURLY[:1])
    assert result.summary.resolution == ConsumptionResolution.unknown
    assert result.summary.kwh_consumed is None


def test_consumption_is_last_minus_first_not_a_sum():
    result = build_consumption("M1", HALF_HOURLY)
    assert result.summary.kwh_consumed == round(101.00 - 100.00, 3)
    assert result.summary.kvah_consumed == round(111.10 - 110.00, 3)


def test_readings_sorted_even_if_input_is_not():
    result = build_consumption("M1", list(reversed(HALF_HOURLY)))
    timestamps = [r.timestamp for r in result.readings]
    assert timestamps == sorted(timestamps)


def test_missing_voltage_value_becomes_none():
    raw = [{"timestamp": "23/06/2026 00:00", "kwh": "1.0", "kvah": "1.0", "voltR": "—"}]
    result = build_consumption("M1", raw)
    assert result.readings[0].volt_r is None
    assert result.summary.avg_volt_r is None
