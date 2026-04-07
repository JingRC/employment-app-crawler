from pydantic import BaseModel


class FavoriteCompanyItem(BaseModel):
    company_id: int
    company_name: str


class FavoriteCompanyListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[FavoriteCompanyItem]