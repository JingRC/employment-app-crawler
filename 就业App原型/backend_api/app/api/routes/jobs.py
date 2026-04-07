from fastapi import APIRouter, HTTPException, Query

from fastapi import Body

from app.schemas.job import JobAnalyticsData, JobBatchActionRequest, JobBatchActionResult, JobDetail, JobFilterData, JobListData
from app.services.job_service import batch_restore_jobs, batch_verify_jobs, manually_restore_job, manually_verify_job, query_job_detail, query_job_filter_options, query_job_market_analytics, query_jobs

router = APIRouter()


@router.get("")
def list_jobs(
    keyword: str | None = Query(default=None),
    city_name: str | None = Query(default=None),
    internship_only: bool = Query(default=False),
    source_code: str | None = Query(default=None),
    status: str | None = Query(default="active"),
    offline_verification_status: str | None = Query(default=None),
    salary_min_k: float | None = Query(default=None, ge=0),
    salary_max_k: float | None = Query(default=None, ge=0),
    degree_text: str | None = Query(default=None),
    experience_text: str | None = Query(default=None),
    sort_by: str | None = Query(default="latest"),
    page: int = 1,
    page_size: int = 20,
) -> dict:
    result = query_jobs(
        keyword=keyword,
        city_name=city_name,
        internship_only=internship_only,
        source_code=source_code,
        status=status,
        offline_verification_status=offline_verification_status,
        salary_min_k=salary_min_k,
        salary_max_k=salary_max_k,
        degree_text=degree_text,
        experience_text=experience_text,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    data = JobListData(**result)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/filters")
def list_job_filters(
    status: str | None = Query(default="active"),
    offline_verification_status: str | None = Query(default=None),
) -> dict:
    data = JobFilterData(**query_job_filter_options(status=status, offline_verification_status=offline_verification_status))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/analytics")
def get_job_analytics(
    status: str | None = Query(default="active"),
    top_n: int = Query(default=12, ge=1, le=50),
    focus_source_code: str | None = Query(default=None),
) -> dict:
    data = JobAnalyticsData(**query_job_market_analytics(status=status, top_n=top_n, focus_source_code=focus_source_code))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/{job_id}/verify-offline")
def verify_job_offline(job_id: int) -> dict:
    detail = manually_verify_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = JobDetail(**detail)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/{job_id}/restore")
def restore_job(job_id: int) -> dict:
    detail = manually_restore_job(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = JobDetail(**detail)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/batch/verify-offline")
def batch_verify_offline_jobs(payload: JobBatchActionRequest = Body(...)) -> dict:
    data = JobBatchActionResult(**batch_verify_jobs(payload.job_ids))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/batch/restore")
def batch_restore_offline_jobs(payload: JobBatchActionRequest = Body(...)) -> dict:
    data = JobBatchActionResult(**batch_restore_jobs(payload.job_ids))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/{job_id}")
def get_job_detail(job_id: int) -> dict:
    detail = query_job_detail(job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = JobDetail(**detail)
    return {"code": 0, "message": "success", "data": data.model_dump()}
