from fastapi import APIRouter, Query

from app.core.platform_catalog import get_platform_catalog_filters, list_platform_catalog
from app.schemas.platform import PlatformCatalogFilterData, PlatformCatalogItem, PlatformCatalogListData

router = APIRouter()


@router.get("")
def list_platforms(
    platform_category: str = Query(default=""),
    current_status: str = Query(default=""),
    crawl_priority: str = Query(default=""),
    region_scope: str = Query(default=""),
) -> dict:
    items = [
        PlatformCatalogItem(**item)
        for item in list_platform_catalog(
            platform_category=platform_category,
            current_status=current_status,
            crawl_priority=crawl_priority,
            region_scope=region_scope,
        )
    ]
    data = PlatformCatalogListData(items=items, total=len(items))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/filters")
def list_platform_filters() -> dict:
    data = PlatformCatalogFilterData(**get_platform_catalog_filters())
    return {"code": 0, "message": "success", "data": data.model_dump()}