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

from app.api.routes import crawler  # noqa: E402
from app.schemas.crawl import CrawlTriggerRequest  # noqa: E402


class CrawlerOfflineRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_stale_after_hours(self) -> None:
        body = CrawlTriggerRequest(
            sources=["boss"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            stale_after_hours=24,
            source_options={},
        )
        fake_status = {
            "task_id": "task-offline-1",
            "status": "running",
            "is_running": True,
            "message": "任务已启动",
            "config": body.model_dump(),
            "last_result": {},
            "logs": [],
            "recent_tasks": [],
        }

        with patch.object(crawler, "start_incremental_crawl", return_value=fake_status) as start_mock:
            result = crawler.start_incremental_job_crawl(body)

        start_mock.assert_called_once_with(
            sources=["boss"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            stale_after_hours=24,
            source_options={},
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["stale_after_hours"], 24)


if __name__ == "__main__":
    unittest.main()