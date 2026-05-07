from pydantic import BaseModel


class NotificationItem(BaseModel):
    notification_id: int
    notification_type: str
    action_source: str = ""
    action_source_name: str = ""
    title: str
    content: str = ""
    is_read: bool = False
    created_at: str = ""
    related_job_id: int | None = None
    related_company_id: int | None = None


class JobChangeEventItem(BaseModel):
    event_id: int
    event_type: str
    source_code: str = ""
    source_name: str = ""
    change_summary: str = ""
    created_at: str = ""
    before_payload: dict = {}
    after_payload: dict = {}


class JobTimelineEntryItem(BaseModel):
    entry_kind: str
    created_at: str = ""
    title: str = ""
    content: str = ""
    notification_type: str = ""
    action_source: str = ""
    action_source_name: str = ""
    event_type: str = ""
    source_code: str = ""
    source_name: str = ""
    is_read: bool = False


class NotificationListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[NotificationItem]


class JobNotificationTimelineData(BaseModel):
    items: list[NotificationItem]
    events: list[JobChangeEventItem] = []
    timeline: list[JobTimelineEntryItem] = []


class NotificationStatsData(BaseModel):
    total: int
    unread: int
