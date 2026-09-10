from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_service
from app.models import PaginatedTransformers, Transformer
from app.service import UrjaService

router = APIRouter(prefix="/api/v1/transformers", tags=["transformers"])


@router.get("", response_model=PaginatedTransformers, summary="List distribution transformers (DTs)")
async def list_transformers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    service: UrjaService = Depends(get_service),
) -> PaginatedTransformers:
    """Each DT is enriched with `meter_count` / `status_breakdown` computed
    from the meter dataset — the portal's own DT listing doesn't include
    either."""
    all_transformers = await service.transformers()
    total = len(all_transformers)
    start = (page - 1) * page_size
    page_items = all_transformers[start : start + page_size]
    return PaginatedTransformers(data=page_items, total=total, page=page, page_size=page_size)


@router.get("/{code}", response_model=Transformer, summary="Get a single transformer")
async def get_transformer(code: str, service: UrjaService = Depends(get_service)) -> Transformer:
    transformer = await service.transformer(code)
    if transformer is None:
        raise HTTPException(status_code=404, detail=f"Transformer not found: {code}")
    return transformer
