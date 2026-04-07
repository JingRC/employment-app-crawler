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


class CrawlerJob51RouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_job51_source_options(self) -> None:
        body = CrawlTriggerRequest(
            sources=["job51"],
            queries=["Java"],
            cities=["北京"],
            max_pages=3,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "job51": {
                    "enable_request_probe": False,
                    "prefer_request_pages": True,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        fake_status = {
            "task_id": "task-job51-1",
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
            sources=["job51"],
            queries=["Java"],
            cities=["北京"],
            max_pages=3,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "job51": {
                    "enable_request_probe": False,
                    "prefer_request_pages": True,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["job51"])
        self.assertFalse(result["data"]["config"]["source_options"]["job51"]["enable_request_probe"])

    def test_get_status_preserves_job51_request_metrics(self) -> None:
        fake_status = {
            "task_id": "task-job51-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 18:00:00",
            "finished_at": "2026-03-30 18:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["job51"],
                "cities": ["北京"],
                "source_options": {
                    "job51": {
                        "enable_request_probe": True,
                        "prefer_request_pages": True,
                        "probe_timeout_seconds": 8,
                    }
                },
            },
            "last_result": {
                "request_probe_attempts": 1,
                "request_probe_successes": 0,
                "preheated_probe_attempts": 1,
                "preheated_probe_successes": 1,
                "request_page_attempts": 2,
                "request_page_successes": 1,
                "captured_request_samples": 1,
                "job51_request_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "city_code": "010000",
                        "status": "target_pages_reached",
                        "pages_completed": 3,
                        "total_items": 12,
                        "fetched_count": 10,
                        "new_count": 4,
                        "updated_count": 1,
                        "request_probe_attempts": 1,
                        "request_probe_successes": 0,
                        "preheated_probe_attempts": 1,
                        "preheated_probe_successes": 1,
                        "request_page_attempts": 2,
                        "request_page_successes": 1,
                        "captured_request_sample": True,
                    }
                ],
            },
            "error": "",
            "current_city_name": "",
            "current_query": "",
            "logs": [],
            "recent_tasks": [],
        }

        with patch.object(crawler, "get_crawl_status", return_value=fake_status):
            result = crawler.get_status()

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["last_result"]["preheated_probe_successes"], 1)
        self.assertEqual(result["data"]["last_result"]["request_page_successes"], 1)
        self.assertEqual(result["data"]["last_result"]["captured_request_samples"], 1)
        self.assertEqual(result["data"]["last_result"]["job51_request_trace"][0]["status"], "target_pages_reached")
        self.assertTrue(result["data"]["last_result"]["job51_request_trace"][0]["captured_request_sample"])


if __name__ == "__main__":
    unittest.main()
