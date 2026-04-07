from pydantic import BaseModel, Field


class CrawlLogItem(BaseModel):
    timestamp: str = ""
    message: str = ""
    city_name: str = ""
    query: str = ""
    page: int = 0
    source_code: str = ""
    branch: str = ""
    branch_label: str = ""
    debug_snapshot_path: str = ""


class CrawlTaskHistoryItem(BaseModel):
    task_id: str = ""
    status: str = "idle"
    message: str = ""
    started_at: str = ""
    finished_at: str = ""
    config: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    logs: list[CrawlLogItem] = Field(default_factory=list)


class CrawlTriggerRequest(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["boss_dp"])
    queries: list[str] = Field(default_factory=lambda: ["Java", "Python", "前端", "测试"])
    cities: list[str] = Field(default_factory=lambda: ["青岛", "济南", "北京", "上海"])
    max_pages: int = 2
    page_size: int = 30
    runtime_mode: str = "browser"
    stale_after_hours: int = 72
    source_options: dict = Field(default_factory=dict)


class SafeVerifyTriggerRequest(BaseModel):
    limit: int = 12
    timeout_seconds: float = 6.0
    recent_active_hours: int = 24 * 14
    cooldown_hours: int = 12
    auto_only: bool = False


class BossCookiePrepareRequest(BaseModel):
    query: str = "Java"
    city: str = "101010100"
    runtime_mode: str = "requests_only"
    browser_preference: str = "edge"
    browser_profile: str = "Default"
    login_wait_seconds: int = 40


class BossCookieManualSaveRequest(BaseModel):
    cookie_text: str = ""
    query: str = "Java"
    city: str = "101010100"
    runtime_mode: str = "requests_only"


class BossCookiePrepareResult(BaseModel):
    source_code: str = "boss"
    query: str = ""
    city: str = ""
    runtime_mode: str = "requests_only"
    browser_preference: str = "edge"
    browser_profile: str = "Default"
    login_wait_seconds: int = 40
    cookie_refreshed_at: str = ""
    cookie_runtime_mode: str = ""
    cookie_present: bool = False
    cookie_valid: bool = False
    missing_keys: list[str] = Field(default_factory=list)
    validation_mode: str = ""
    probe_code: str = ""
    probe_message: str = ""
    message: str = ""


class BossCookieStatusResult(BaseModel):
    source_code: str = "boss"
    cookie_present: bool = False
    cookie_valid: bool = False
    missing_keys: list[str] = Field(default_factory=list)
    cookie_refreshed_at: str = ""
    cookie_runtime_mode: str = ""
    browser_profile: str = "Default"
    validation_mode: str = ""
    probe_code: str = ""
    probe_message: str = ""
    query: str = ""
    city: str = ""
    message: str = ""


class CrawlSourceItem(BaseModel):
    source_code: str
    source_name: str
    platform_code: str
    platform_name: str
    status: str = "planned"
    enabled: bool = False
    strategy: str = "pending"
    description: str = ""


class CrawlTaskStatus(BaseModel):
    task_id: str = ""
    status: str = "idle"
    is_running: bool = False
    message: str = "尚未开始增量更新"
    started_at: str = ""
    finished_at: str = ""
    cancel_requested: bool = False
    config: dict = Field(default_factory=dict)
    last_result: dict = Field(default_factory=dict)
    error: str = ""
    current_city_name: str = ""
    current_query: str = ""
    logs: list[CrawlLogItem] = Field(default_factory=list)
    recent_tasks: list[CrawlTaskHistoryItem] = Field(default_factory=list)
