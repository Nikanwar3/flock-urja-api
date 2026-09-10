from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_service
from app.index import to_summary
from app.models import Meter, MeterConsumption, NearbyMeter, PaginatedMeters
from app.portal_errors import MeterNotFoundError
from app.service import UrjaService

router = APIRouter(prefix="/api/v1/meters", tags=["meters"])


@router.get("", response_model=PaginatedMeters, summary="List / search / filter meters")
async def list_meters(
    q: str | None = Query(None, description="Free-text match against meter ID or serial number."),
    install_status: str | None = Query(None, description="Installed | Faulty | Decommissioned"),
    phase_type: str | None = Query(None, description="single | three"),
    make: str | None = None,
    install_type: str | None = Query(None, description="CT Operated | Whole Current"),
    dt_code: str | None = Query(None, description="Filter to meters under this distribution transformer."),
    zone: str | None = Query(None, description="Zone code, e.g. Z-01."),
    circle: str | None = None,
    division: str | None = None,
    subdivision: str | None = None,
    substation: str | None = None,
    feeder: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    service: UrjaService = Depends(get_service),
) -> PaginatedMeters:
    """List meters with filters the portal's own UI can't combine (it only
    offers a single free-text box). Backed by our in-memory index, not a
    live portal call — see PROTOCOL.md / README for why."""
    index = await service.meter_index()
    results, total = index.search(
        q=q,
        install_status=install_status,
        phase_type=phase_type,
        make=make,
        install_type=install_type,
        dt_code=dt_code,
        zone=zone,
        circle=circle,
        division=division,
        subdivision=subdivision,
        substation=substation,
        feeder=feeder,
        page=page,
        page_size=page_size,
    )
    return PaginatedMeters(data=[to_summary(m) for m in results], total=total, page=page, page_size=page_size)


@router.get("/near", response_model=list[NearbyMeter], summary="Meters near a lat/lng point")
async def meters_near(
    lat: float,
    lng: float,
    radius_km: float | None = Query(None, ge=0, description="Omit for no distance cap."),
    limit: int = Query(20, ge=1, le=200),
    service: UrjaService = Depends(get_service),
) -> list[NearbyMeter]:
    """Not something the portal can answer at all — it has no spatial
    query. Straight-line (haversine) distance, sorted nearest-first."""
    index = await service.meter_index()
    return index.nearby(lat, lng, radius_km, limit)


@router.get("/{meter_id}", response_model=Meter, summary="Get a single meter's nameplate, hierarchy and geo")
async def get_meter(meter_id: str, service: UrjaService = Depends(get_service)) -> Meter:
    index = await service.meter_index()
    meter = index.get(meter_id)
    if meter is None:
        raise HTTPException(status_code=404, detail=f"Meter not found: {meter_id}")
    return meter


@router.get(
    "/{meter_id}/consumption",
    response_model=MeterConsumption,
    summary="Consumption readings for a meter, with a computed usage summary",
)
async def get_meter_consumption(meter_id: str, service: UrjaService = Depends(get_service)) -> MeterConsumption:
    """Raw readings from the portal are cumulative register values, not
    interval usage — this endpoint returns both the raw readings *and* a
    `summary` with derived consumption (last - first) and the inferred
    reading resolution, since the portal's own granularity is inconsistent
    across meters (see PROTOCOL.md)."""
    try:
        return await service.consumption(meter_id)
    except MeterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
