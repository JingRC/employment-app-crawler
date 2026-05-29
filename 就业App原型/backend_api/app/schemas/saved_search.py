from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SavedSearchRequest(BaseModel):
    keyword: str = ""
    city_name: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    notify_frequency: str = "daily"


class SavedSearchPatchRequest(BaseModel):
    keyword: str | None = None
    city_name: str | None = None
    filters: dict[str, Any] | None = None
    enabled: bool | None = None
    notify_frequency: str | None = None


class SavedSearchItem(BaseModel):
    search_id: int
    keyword: str = ""
    city_name: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    notify_frequency: str = "daily"
    last_triggered_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class SavedSearchListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[SavedSearchItem]