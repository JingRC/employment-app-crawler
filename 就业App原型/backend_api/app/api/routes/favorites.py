from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas.favorite import FavoriteCompanyListData, FavoriteJobListData, FavoriteJobRequest
from app.services.job_service import create_favorite_company, create_favorite_job, delete_favorite_job, query_favorite_companies, query_favorite_jobs

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


@router.post("/jobs")
def favorite_job(body: FavoriteJobRequest) -> dict:
    favorite = create_favorite_job(body.job_id)
    if favorite is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "code": 0,
        "message": "success",
        "data": favorite,
    }


@router.get("/jobs")
def list_favorite_jobs(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> dict:
    result = query_favorite_jobs(keyword=keyword, page=page, page_size=page_size)
    data = FavoriteJobListData(**result)
    return {
        "code": 0,
        "message": "success",
        "data": data.model_dump(),
    }


@router.delete("/jobs/{job_id}")
def unfavorite_job(job_id: int) -> dict:
    success = delete_favorite_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="favorite job not found")
    return {
        "code": 0,
        "message": "success",
        "data": True,
    }
