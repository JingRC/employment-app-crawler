from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.saved_search import SavedSearchItem, SavedSearchListData, SavedSearchPatchRequest, SavedSearchRequest
from app.services.job_service import (
    create_saved_search_subscription,
    patch_saved_search_subscription,
    query_saved_searches,
    remove_saved_search_subscription,
)

router = APIRouter()


@router.post("")
def create_saved_search_api(body: SavedSearchRequest) -> dict:
    data = SavedSearchItem(
        **create_saved_search_subscription(
            keyword=body.keyword,
            city_name=body.city_name,
            filters=body.filters,
            enabled=body.enabled,
            notify_frequency=body.notify_frequency,
        )
    )
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("")
def list_saved_searches_api(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> dict:
    data = SavedSearchListData(**query_saved_searches(keyword=keyword, page=page, page_size=page_size))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.patch("/{search_id}")
def patch_saved_search_api(search_id: int, body: SavedSearchPatchRequest) -> dict:
    updated = patch_saved_search_subscription(
        search_id,
        keyword=body.keyword,
        city_name=body.city_name,
        filters=body.filters,
        enabled=body.enabled,
        notify_frequency=body.notify_frequency,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="saved search not found")
    data = SavedSearchItem(**updated)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.delete("/{search_id}")
def delete_saved_search_api(search_id: int) -> dict:
    success = remove_saved_search_subscription(search_id)
    if not success:
        raise HTTPException(status_code=404, detail="saved search not found")
    return {"code": 0, "message": "success", "data": True}