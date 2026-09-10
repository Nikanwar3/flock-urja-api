from fastapi import APIRouter, Depends

from app.deps import get_service
from app.models import HierarchyTree
from app.service import UrjaService

router = APIRouter(prefix="/api/v1/hierarchy", tags=["hierarchy"])


@router.get("", response_model=HierarchyTree, summary="Full network hierarchy tree (zone -> ... -> DT)")
async def get_hierarchy(service: UrjaService = Depends(get_service)) -> HierarchyTree:
    """Reconstructed from per-meter data, since the portal exposes the
    hierarchy only as a breadcrumb on each meter's own page, never as a
    tree. `data_quality_issues` surfaces DTs whose meters disagree on (or
    are missing) part of their upstream path — see PROTOCOL.md."""
    return await service.hierarchy()
