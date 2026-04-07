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


class CrawlerZhilianRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_zhilian_source_options(self) -> None:
        body = CrawlTriggerRequest(
            sources=["zhilian"],
            queries=["Java"],
            cities=["北京"],
            max_pages=3,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "zhilian": {
                    "enable_request_probe": False,
                    "prefer_request_pages": True,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        fake_status = {
            "task_id": "task-zhilian-1",
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
            sources=["zhilian"],
            queries=["Java"],
            cities=["北京"],
            max_pages=3,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "zhilian": {
                    "enable_request_probe": False,
                    "prefer_request_pages": True,
                    "probe_timeout_seconds": 11.5,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["zhilian"])
        self.assertEqual(result["data"]["config"]["cities"], ["北京"])
        self.assertFalse(result["data"]["config"]["source_options"]["zhilian"]["enable_request_probe"])

    def test_start_incremental_job_crawl_preserves_mixed_sources_with_zhilian(self) -> None:
        body = CrawlTriggerRequest(
            sources=["zhilian", "boss"],
            queries=["Python"],
            cities=["上海", "深圳"],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            source_options={
                "zhilian": {
                    "enable_request_probe": True,
                    "prefer_request_pages": False,
                    "probe_timeout_seconds": 9,
                }
            },
        )
        fake_status = {
            "task_id": "task-zhilian-mixed-1",
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
            sources=["zhilian", "boss"],
            queries=["Python"],
            cities=["上海", "深圳"],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            source_options={
                "zhilian": {
                    "enable_request_probe": True,
                    "prefer_request_pages": False,
                    "probe_timeout_seconds": 9,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["zhilian", "boss"])
        self.assertEqual(result["data"]["config"]["cities"], ["上海", "深圳"])

    def test_get_status_preserves_zhilian_request_metrics(self) -> None:
        fake_status = {
            "task_id": "task-zhilian-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 14:00:00",
            "finished_at": "2026-03-30 14:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["zhilian"],
                "cities": ["北京"],
                "source_options": {
                    "zhilian": {
                        "enable_request_probe": True,
                        "prefer_request_pages": True,
                        "probe_timeout_seconds": 8,
                    }
                },
            },
            "last_result": {
                "resolved_city_codes": {"北京": "530"},
                "request_probe_attempts": 1,
                "request_probe_successes": 1,
                "request_page_attempts": 2,
                "request_page_successes": 1,
                "captured_request_samples": 1,
                "zhilian_request_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "city_code": "530",
                        "status": "target_pages_reached",
                        "pages_completed": 3,
                        "total_items": 12,
                        "fetched_count": 10,
                        "new_count": 4,
                        "updated_count": 1,
                        "request_probe_attempts": 1,
                        "request_probe_successes": 1,
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
        self.assertEqual(result["data"]["last_result"]["resolved_city_codes"], {"北京": "530"})
        self.assertEqual(result["data"]["last_result"]["request_probe_attempts"], 1)
        self.assertEqual(result["data"]["last_result"]["request_page_successes"], 1)
        self.assertEqual(result["data"]["last_result"]["captured_request_samples"], 1)
        self.assertEqual(result["data"]["last_result"]["zhilian_request_trace"][0]["status"], "target_pages_reached")
        self.assertTrue(result["data"]["last_result"]["zhilian_request_trace"][0]["captured_request_sample"])


if __name__ == "__main__":
    unittest.main()
