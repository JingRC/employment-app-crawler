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


class CrawlerBossDpRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_boss_dp_config(self) -> None:
        body = CrawlTriggerRequest(
            sources=["boss_dp"],
            queries=["Java"],
            cities=["北京"],
            max_pages=1,
            page_size=30,
            runtime_mode="hybrid",
            source_options={},
        )
        fake_status = {
            "task_id": "task-boss-dp-1",
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
            sources=["boss_dp"],
            queries=["Java"],
            cities=["北京"],
            max_pages=1,
            page_size=30,
            runtime_mode="hybrid",
            stale_after_hours=72,
            source_options={},
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["boss_dp"])

    def test_get_status_preserves_boss_dp_trace(self) -> None:
        fake_status = {
            "task_id": "task-boss-dp-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 23:20:00",
            "finished_at": "2026-03-30 23:22:00",
            "cancel_requested": False,
            "config": {
                "sources": ["boss_dp"],
                "cities": ["北京"],
                "runtime_mode": "hybrid",
                "source_options": {},
            },
            "last_result": {
                "boss_dp_summary": {
                    "trace_count": 1,
                    "api_pages": 1,
                    "html_fallback_pages": 0,
                    "verify_hits": 1,
                    "page_load_failures": 0,
                    "runtime_mode": "hybrid",
                },
                "boss_dp_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "city_code": "101010100",
                        "status": "verify_page",
                        "pages_completed": 0,
                        "fetched_count": 0,
                        "new_count": 0,
                        "updated_count": 0,
                        "api_pages": 0,
                        "html_fallback_pages": 0,
                        "verify_hits": 1,
                        "page_load_failures": 0,
                        "runtime_mode": "hybrid",
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
        self.assertEqual(result["data"]["last_result"]["boss_dp_summary"]["verify_hits"], 1)
        self.assertEqual(result["data"]["last_result"]["boss_dp_trace"][0]["status"], "verify_page")
        self.assertEqual(result["data"]["last_result"]["boss_dp_trace"][0]["city_code"], "101010100")


if __name__ == "__main__":
    unittest.main()