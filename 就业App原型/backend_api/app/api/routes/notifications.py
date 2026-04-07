from fastapi import APIRouter, HTTPException

from app.schemas.notification import JobNotificationTimelineData, NotificationListData
from app.services.job_service import add_notification, query_job_notification_timeline, query_notifications, set_notification_read

router = APIRouter()


@router.get("")
def list_notifications(
    page: int = 1,
    page_size: int = 20,
    notification_type: str | None = None,
    action_source: str | None = None,
    unread_only: bool = False,
    related_job_id: int | None = None,
) -> dict:
    result = query_notifications(
        page=page,
        page_size=page_size,
        notification_type=notification_type,
        action_source=action_source,
        unread_only=unread_only,
        related_job_id=related_job_id,
    )
    data = NotificationListData(**result)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/jobs/{job_id}")
def get_job_notification_timeline(job_id: int, limit: int = 20) -> dict:
    data = JobNotificationTimelineData(**query_job_notification_timeline(job_id=job_id, limit=limit))
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/{notification_id}/read")
def mark_notification_read_api(notification_id: int) -> dict:
    success = set_notification_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"code": 0, "message": "success", "data": True}
