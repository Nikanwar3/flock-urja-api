from fastapi import APIRouter, Depends

from app.deps import get_service
from app.models import HealthStatus
from app.service import UrjaService

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus, summary="Service + upstream portal health")
async def healthz(service: UrjaService = Depends(get_service)) -> HealthStatus:
    return await service.health()
