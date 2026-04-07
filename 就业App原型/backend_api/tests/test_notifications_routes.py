from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.api.routes import notifications  # noqa: E402


class NotificationRouteTests(unittest.TestCase):
    def test_list_notifications_forwards_related_job_id(self) -> None:
        fake_result = {"page": 1, "page_size": 20, "total": 0, "items": []}
        with patch.object(notifications, "query_notifications", return_value=fake_result) as query_mock:
            result = notifications.list_notifications(page=1, page_size=20, related_job_id=7)

        query_mock.assert_called_once_with(
            page=1,
            page_size=20,
            notification_type=None,
            action_source=None,
            unread_only=False,
            related_job_id=7,
        )
        self.assertEqual(result["code"], 0)

    def test_list_notifications_forwards_action_source(self) -> None:
        fake_result = {"page": 1, "page_size": 20, "total": 0, "items": []}
        with patch.object(notifications, "query_notifications", return_value=fake_result) as query_mock:
            result = notifications.list_notifications(page=1, page_size=20, action_source="batch_restore")

        query_mock.assert_called_once_with(
            page=1,
            page_size=20,
            notification_type=None,
            action_source="batch_restore",
            unread_only=False,
            related_job_id=None,
        )
        self.assertEqual(result["code"], 0)

    def test_job_notification_timeline_forwards_job_id(self) -> None:
        fake_result = {"items": [{"notification_id": 1, "notification_type": "job_manual_verify", "action_source": "manual_verify", "action_source_name": "手动复核", "title": "x", "content": "y", "is_read": False, "created_at": "2026-03-30 12:00:00", "related_job_id": 7, "related_company_id": 3}]}
        with patch.object(notifications, "query_job_notification_timeline", return_value=fake_result) as query_mock:
            result = notifications.get_job_notification_timeline(7, limit=10)

        query_mock.assert_called_once_with(job_id=7, limit=10)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["items"][0]["related_job_id"], 7)
        self.assertEqual(result["data"]["items"][0]["action_source_name"], "手动复核")


if __name__ == "__main__":
    unittest.main()