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


class CrawlerLiepinRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_liepin_source_options(self) -> None:
        body = CrawlTriggerRequest(
            sources=["liepin"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "liepin": {
                    "city_mode": "result_filter_only",
                    "enable_request_probe": False,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        fake_status = {
            "task_id": "task-liepin-1",
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
            sources=["liepin"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "liepin": {
                    "city_mode": "result_filter_only",
                    "enable_request_probe": False,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["liepin"])
        self.assertFalse(result["data"]["config"]["source_options"]["liepin"]["enable_request_probe"])

    def test_get_status_preserves_liepin_request_metrics(self) -> None:
        fake_status = {
            "task_id": "task-liepin-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 20:00:00",
            "finished_at": "2026-03-30 20:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["liepin"],
                "cities": ["北京"],
                "source_options": {
                    "liepin": {
                        "city_mode": "precise_if_supported",
                        "enable_request_probe": True,
                        "probe_timeout_seconds": 8,
                    }
                },
            },
            "last_result": {
                "request_probe_attempts": 1,
                "request_probe_successes": 1,
                "captured_request_samples": 1,
                "resolved_city_entries": {
                    "北京": {
                        "code": "010",
                        "name": "北京",
                        "search_url": "https://www.liepin.com/city-beijing/"
                    }
                },
                "footer_city_pages": {
                    "北京": "https://www.liepin.com/city-beijing/"
                },
                "liepin_request_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "status": "target_pages_reached",
                        "pages_completed": 2,
                        "fetched_count": 6,
                        "new_count": 2,
                        "updated_count": 1,
                        "request_probe_attempts": 1,
                        "request_probe_successes": 1,
                        "captured_request_sample": True,
                        "resolved_city_code": "010",
                        "resolved_city_name": "北京",
                        "resolved_search_url": "https://www.liepin.com/city-beijing/",
                        "footer_city_page": "https://www.liepin.com/city-beijing/",
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
        self.assertEqual(result["data"]["last_result"]["request_probe_successes"], 1)
        self.assertEqual(result["data"]["last_result"]["captured_request_samples"], 1)
        self.assertEqual(result["data"]["last_result"]["resolved_city_entries"]["北京"]["code"], "010")
        self.assertEqual(result["data"]["last_result"]["footer_city_pages"]["北京"], "https://www.liepin.com/city-beijing/")
        self.assertEqual(result["data"]["last_result"]["liepin_request_trace"][0]["status"], "target_pages_reached")
        self.assertTrue(result["data"]["last_result"]["liepin_request_trace"][0]["captured_request_sample"])


if __name__ == "__main__":
    unittest.main()
