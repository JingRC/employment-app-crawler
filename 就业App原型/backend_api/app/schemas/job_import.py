from __future__ import annotations

from pydantic import BaseModel


class JobImportRequest(BaseModel):
    url: str = ""
    title: str
    company_name: str
    city_name: str = ""
    salary_text: str = ""
    source_code: str = ""
    notes: str = ""
    tracking_status: str = "saved"


class JobTrackingItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    city_name: str = ""
    salary_text: str = ""
    source_url: str = ""
    source_code: str = ""
    source_name: str = ""
    status: str = "active"
    tracking_status: str = "saved"
    notes: str = ""
    applied_at: str = ""
    interview_at: str = ""
    offer_at: str = ""
    result_at: str = ""
    result_status: str = ""
    created_at: str = ""
    updated_at: str = ""


class JobTrackingUpdateRequest(BaseModel):
    tracking_status: str | None = None
    notes: str | None = None


class JobTrackingSummary(BaseModel):
    saved: int = 0
    applied: int = 0
    interview: int = 0
    offer: int = 0
    accepted: int = 0
    rejected: int = 0


class JobTrackingListData(BaseModel):
    items: list[JobTrackingItem]
    total: int
    page: int = 1
    page_size: int = 20
    summary: JobTrackingSummary | None = None
