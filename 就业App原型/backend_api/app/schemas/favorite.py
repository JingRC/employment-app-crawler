from pydantic import BaseModel


class FavoriteCompanyItem(BaseModel):
    company_id: int
    company_name: str


class FavoriteCompanyListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[FavoriteCompanyItem]


class FavoriteJobRequest(BaseModel):
    job_id: int


class FavoriteJobItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    city_name: str = ""
    salary_text: str = ""
    source_code: str = "unknown"
    source_name: str = "未知来源"
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    is_favorited: bool = True


class FavoriteJobListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[FavoriteJobItem]