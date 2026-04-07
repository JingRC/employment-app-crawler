from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.schemas.favorite import FavoriteCompanyListData
from app.services.job_service import create_favorite_company, query_favorite_companies

router = APIRouter()


class FavoriteCompanyRequest(BaseModel):
    company_id: int
    company_name: str


@router.post("/companies")
def favorite_company(body: FavoriteCompanyRequest) -> dict:
    favorite = create_favorite_company(body.company_id, body.company_name)
    return {
        "code": 0,
        "message": "success",
        "data": favorite,
    }


@router.get("/companies")
def list_favorite_companies(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> dict:
    result = query_favorite_companies(keyword=keyword, page=page, page_size=page_size)
    data = FavoriteCompanyListData(**result)
    return {
        "code": 0,
        "message": "success",
        "data": data.model_dump(),
    }
