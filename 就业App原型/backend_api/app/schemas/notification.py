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


class NotificationListData(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[NotificationItem]


class JobNotificationTimelineData(BaseModel):
    items: list[NotificationItem]
