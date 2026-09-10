"""HTTP-level tests: status codes, query-param handling, error mapping.

These hit the FastAPI app directly (via TestClient) with the portal
adapter swapped out for an in-memory fake, so they never touch the
network — the lower-level adapter behaviour is covered separately in
test_portal_client.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.consumption import build_consumption
from app.deps import get_service
from app.index import MeterIndex, build_hierarchy_tree, build_transformers
from app.main import app
from app.models import HealthStatus
from app.portal_errors import MeterNotFoundError

FAKE_DTS = [{"code": "DT-001", "name": "Malviya Nagar DT 1", "feederCode": "F-001", "capacityKva": 100}]
FAKE_ENERGY = {
    "J100000": [
        {"timestamp": "23/06/2026 00:00", "kwh": "10.0", "kvah": "11.0", "voltR": "230"},
        {"timestamp": "24/06/2026 00:00", "kwh": "12.0", "kvah": "13.0", "voltR": "228"},
    ]
}


class FakeService:
    def __init__(self, raw_meters):
        self._index = MeterIndex(raw_meters)

    async def meter_index(self):
        return self._index

    async def transformers(self):
        return build_transformers(FAKE_DTS, self._index)

    async def transformer(self, code):
        return next((t for t in await self.transformers() if t.code == code), None)

    async def hierarchy(self):
        return build_hierarchy_tree(self._index)

    async def consumption(self, meter_id):
        if meter_id not in FAKE_ENERGY:
            raise MeterNotFoundError(meter_id)
        return build_consumption(meter_id, FAKE_ENERGY[meter_id])

    async def health(self):
        return HealthStatus(status="ok", portal_reachable=True, session_active=True)


@pytest.fixture
def client(fake_meters):
    app.dependency_overrides[get_service] = lambda: FakeService(fake_meters)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_list_meters_default(client):
    resp = client.get("/api/v1/meters")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["data"]) == 3


def test_list_meters_filter_combo_the_portal_cannot_do(client):
    resp = client.get("/api/v1/meters", params={"install_status": "Faulty", "phase_type": "three"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["meter_id"] == "J100001"


def test_get_meter_404(client):
    resp = client.get("/api/v1/meters/NOPE")
    assert resp.status_code == 404


def test_get_meter_200_includes_hierarchy_flag(client):
    resp = client.get("/api/v1/meters/J100001")
    assert resp.status_code == 200
    assert resp.json()["hierarchy_complete"] is False


def test_consumption_404_for_unknown_meter(client):
    resp = client.get("/api/v1/meters/J100000/consumption")
    assert resp.status_code == 200  # J100000 has fake energy data
    resp = client.get("/api/v1/meters/J100002/consumption")
    assert resp.status_code == 404


def test_meters_near_requires_lat_lng(client):
    resp = client.get("/api/v1/meters/near")
    assert resp.status_code == 422  # FastAPI validation error, not a 500


def test_meters_near_ok(client):
    resp = client.get("/api/v1/meters/near", params={"lat": 26.9, "lng": 75.8})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_transformer_detail_and_404(client):
    resp = client.get("/api/v1/transformers/DT-001")
    assert resp.status_code == 200
    assert resp.json()["meter_count"] == 2

    resp = client.get("/api/v1/transformers/NOPE")
    assert resp.status_code == 404


def test_hierarchy_endpoint(client):
    resp = client.get("/api/v1/hierarchy")
    assert resp.status_code == 200
    assert resp.json()["total_meters"] == 3


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_page_size_validation(client):
    resp = client.get("/api/v1/meters", params={"page_size": 0})
    assert resp.status_code == 422
    resp = client.get("/api/v1/meters", params={"page_size": 1000})
    assert resp.status_code == 422
