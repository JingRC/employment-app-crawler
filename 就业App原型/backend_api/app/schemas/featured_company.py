from pydantic import BaseModel


class FeaturedCompanyItem(BaseModel):
    company_id: int
    featured_company_id: int
    board_code: str = "featured_famous"
    board_name: str = "名企"
    company_type: str = "famous_enterprise"
    company_type_name: str = "名企"
    group_name: str = ""
    source_code: str = "unknown"
    source_name: str = "未知来源"
    company_uuid: str = ""
    company_name: str
    city_text: str = ""
    industry: str = ""
    scale_text: str = ""
    module_name: str = ""
    description_text: str = ""
    official_site_url: str = ""
    career_site_url: str = ""
    last_seen_at: str = ""


class FeaturedCompanyRelatedJobItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    city_name: str = ""
    salary_text: str = ""
    degree_text: str = ""
    experience_text: str = ""
    source_code: str = "unknown"
    source_name: str = "未知来源"
    source_url: str = ""
    official_apply_url: str = ""
    last_seen_at: str = ""


class FeaturedCompanyRelatedSourceSummary(BaseModel):
    source_code: str
    source_name: str
    count: int


class FeaturedCompanyDetail(FeaturedCompanyItem):
    collect_mode: str = ""
    crawl_suggested_queries: list[str] = []
    crawl_suggested_cities: list[str] = []
    crawl_suggested_sources: list[str] = []
    related_job_count: int = 0
    related_jobs: list[FeaturedCompanyRelatedJobItem] = []
    related_sources: list[FeaturedCompanyRelatedSourceSummary] = []
    matched_company_names: list[str] = []


class FeaturedCompanyFilterOption(BaseModel):
    count: int


class FeaturedCompanyCityOption(FeaturedCompanyFilterOption):
    city_name: str


class FeaturedCompanyBoardOption(FeaturedCompanyFilterOption):
    board_code: str
    board_name: str


class FeaturedCompanyTypeOption(FeaturedCompanyFilterOption):
    company_type: str
    company_type_name: str


class FeaturedCompanyGroupOption(FeaturedCompanyFilterOption):
    group_name: str


class FeaturedCompanyIndustryOption(FeaturedCompanyFilterOption):
    industry: str


class FeaturedCompanyModuleOption(FeaturedCompanyFilterOption):
    module_name: str


class FeaturedCompanyFilterData(BaseModel):
    boards: list[FeaturedCompanyBoardOption]
    company_types: list[FeaturedCompanyTypeOption]
    groups: list[FeaturedCompanyGroupOption]
    cities: list[FeaturedCompanyCityOption]
    industries: list[FeaturedCompanyIndustryOption]
    modules: list[FeaturedCompanyModuleOption]


class FeaturedCompanyListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[FeaturedCompanyItem]