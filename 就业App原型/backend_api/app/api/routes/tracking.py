from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.job_import import JobImportRequest, JobTrackingItem, JobTrackingListData, JobTrackingSummary, JobTrackingUpdateRequest
from app.services.job_service import (
    delete_tracking,
    get_tracking_summary,
    import_job,
    list_tracked_jobs,
    update_tracking,
)

router = APIRouter()


@router.post("/jobs/import")
def import_job_api(body: JobImportRequest) -> dict:
    if not body.title.strip() or not body.company_name.strip():
        raise HTTPException(status_code=422, detail="职位名称和公司名称为必填")
    result = import_job(
        title=body.title.strip(),
        company_name=body.company_name.strip(),
        city_name=body.city_name.strip(),
        salary_text=body.salary_text.strip(),
        source_url=body.url.strip(),
        source_code=body.source_code.strip(),
        notes=body.notes.strip(),
        tracking_status=body.tracking_status.strip() or "saved",
    )
    data = JobTrackingItem(**result)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/tracking")
def list_tracking_api(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    result = list_tracked_jobs(status=status, page=page, page_size=page_size)
    items = [JobTrackingItem(**item) for item in result["items"]]
    summary = JobTrackingSummary(**result["summary"])
    data = JobTrackingListData(
        items=items,
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        summary=summary,
    )
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/tracking/summary")
def tracking_summary_api() -> dict:
    data = JobTrackingSummary(**get_tracking_summary())
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.patch("/tracking/{job_id}")
def update_tracking_api(job_id: int, body: JobTrackingUpdateRequest) -> dict:
    result = update_tracking(
        job_id=job_id,
        tracking_status=body.tracking_status,
        notes=body.notes,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="tracking record not found")
    data = JobTrackingItem(**result)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.delete("/tracking/{job_id}")
def delete_tracking_api(job_id: int) -> dict:
    success = delete_tracking(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="tracking record not found")
    return {"code": 0, "message": "success", "data": True}
