from pydantic import BaseModel


class JobItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    city_name: str
    salary_text: str = ""
    degree_text: str = ""
    official_apply_url: str = ""
    source_code: str = "unknown"
    source_name: str = "未知来源"
    job_type: str = ""
    experience_text: str = ""
    status: str = "active"
    last_seen_at: str = ""
    offline_verification_status: str = ""
    offline_verified_at: str = ""


class JobFilterOption(BaseModel):
    count: int


class CityFilterOption(JobFilterOption):
    city_name: str


class SourceFilterOption(JobFilterOption):
    source_code: str
    source_name: str


class DegreeFilterOption(JobFilterOption):
    degree_text: str


class ExperienceFilterOption(JobFilterOption):
    experience_text: str


class VerificationStatusFilterOption(JobFilterOption):
    offline_verification_status: str


class JobFilterData(BaseModel):
    cities: list[CityFilterOption]
    sources: list[SourceFilterOption]
    degrees: list[DegreeFilterOption]
    experiences: list[ExperienceFilterOption]
    verification_statuses: list[VerificationStatusFilterOption] = []


class JobListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[JobItem]


class JobAnalyticsOverview(BaseModel):
    total_jobs: int
    total_companies: int
    total_cities: int
    average_salary_k: float | None = None
    salary_sample_count: int = 0
    recent_24h_count: int = 0
    recent_7d_count: int = 0
    status_scope: str = "active"


class JobAnalyticsCityItem(BaseModel):
    city_name: str
    job_count: int
    avg_salary_k: float | None = None
    salary_sample_count: int = 0


class JobAnalyticsSourceItem(BaseModel):
    source_code: str
    source_name: str
    job_count: int


class JobAnalyticsSalaryItem(BaseModel):
    label: str
    job_count: int


class JobAnalyticsBreakdownItem(BaseModel):
    label: str
    job_count: int


class JobAnalyticsFocusProfile(BaseModel):
    source_code: str
    source_name: str
    total_jobs: int
    total_companies: int
    total_cities: int
    total_districts: int
    average_salary_k: float | None = None
    salary_sample_count: int = 0
    district_distribution: list[JobAnalyticsBreakdownItem]
    company_distribution: list[JobAnalyticsBreakdownItem]
    job_type_distribution: list[JobAnalyticsBreakdownItem]


class JobAnalyticsData(BaseModel):
    overview: JobAnalyticsOverview
    city_distribution: list[JobAnalyticsCityItem]
    source_distribution: list[JobAnalyticsSourceItem]
    salary_distribution: list[JobAnalyticsSalaryItem]
    focus_source_profile: JobAnalyticsFocusProfile | None = None


class JobDetail(BaseModel):
    job_id: int
    company_id: int = 0
    title: str
    company_name: str
    city_name: str = ""
    district_name: str = ""
    salary_text: str = ""
    degree_text: str = ""
    experience_text: str = ""
    description_text: str = ""
    source_url: str = ""
    official_apply_url: str = ""
    job_type: str = ""
    brand_scale: str = ""
    brand_stage: str = ""
    source_code: str = "unknown"
    source_name: str = "未知来源"
    status: str = "active"
    last_seen_at: str = ""
    offline_verification_status: str = ""
    offline_verification_reason: str = ""
    offline_verified_at: str = ""


class JobBatchActionRequest(BaseModel):
    job_ids: list[int]


class JobBatchActionResult(BaseModel):
    requested_count: int
    success_count: int
    failed_count: int
    restored_count: int = 0
    items: list[JobDetail] = []
    failed_job_ids: list[int] = []
