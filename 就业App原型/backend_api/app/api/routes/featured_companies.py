from fastapi import APIRouter, HTTPException, Query

from app.schemas.featured_company import FeaturedCompanyDetail, FeaturedCompanyFilterData, FeaturedCompanyListData
from app.services.job_service import import_dxy_job_featured_topics, import_niuke_campus_featured_topics, import_yingjiesheng_featured_topics, query_featured_companies, query_featured_company_detail, query_featured_company_filter_options

router = APIRouter()


@router.get("")
def list_featured_companies_api(
    keyword: str | None = Query(default=None),
    board_code: str | None = Query(default=None),
    company_type: str | None = Query(default=None),
    group_name: str | None = Query(default=None),
    city_name: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    module_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    result = query_featured_companies(
        keyword=keyword,
        board_code=board_code,
        company_type=company_type,
        group_name=group_name,
        city_name=city_name,
        industry=industry,
        module_name=module_name,
        page=page,
        page_size=page_size,
    )
    data = FeaturedCompanyListData(**result)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/filters")
def list_featured_company_filters_api() -> dict:
    data = FeaturedCompanyFilterData(**query_featured_company_filter_options())
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/import-niuke-campus")
def import_niuke_campus_featured_companies_api() -> dict:
    data = import_niuke_campus_featured_topics()
    return {"code": 0, "message": "success", "data": data}


@router.post("/import-yingjiesheng-topic")
def import_yingjiesheng_featured_companies_api() -> dict:
    data = import_yingjiesheng_featured_topics()
    return {"code": 0, "message": "success", "data": data}


@router.post("/import-dxy-job-topic")
def import_dxy_job_featured_companies_api() -> dict:
    data = import_dxy_job_featured_topics()
    return {"code": 0, "message": "success", "data": data}


@router.get("/{featured_company_id}")
def get_featured_company_detail_api(
    featured_company_id: int,
    jobs_limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    detail = query_featured_company_detail(featured_company_id=featured_company_id, jobs_limit=jobs_limit)
    if detail is None:
        raise HTTPException(status_code=404, detail="featured company not found")
    data = FeaturedCompanyDetail(**detail)
    return {"code": 0, "message": "success", "data": data.model_dump()}