from pydantic import BaseModel, Field


class PlatformCatalogItem(BaseModel):
    platform_code: str
    platform_name: str
    platform_category: str
    platform_type: str = ""
    coverage_scope: str = ""
    region_scope: str = ""
    suitable_for: list[str] = Field(default_factory=list)
    reliability_level: str = ""
    crawl_priority: str = ""
    current_status: str = "planned"
    source_codes: list[str] = Field(default_factory=list)
    official_site_url: str = ""
    notes: str = ""


class PlatformCatalogListData(BaseModel):
    items: list[PlatformCatalogItem] = Field(default_factory=list)
    total: int = 0


class PlatformCatalogFilterData(BaseModel):
    platform_categories: list[str] = Field(default_factory=list)
    current_statuses: list[str] = Field(default_factory=list)
    crawl_priorities: list[str] = Field(default_factory=list)
    region_scopes: list[str] = Field(default_factory=list)