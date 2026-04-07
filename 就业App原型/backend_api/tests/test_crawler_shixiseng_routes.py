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


class CrawlerShixisengRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_shixiseng_source_options(self) -> None:
        body = CrawlTriggerRequest(
            sources=["shixiseng"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="requests_only",
            source_options={
                "shixiseng": {
                    "track": "campus",
                    "detail_workers": 3,
                    "detail_rate_per_second": 2.5,
                    "include_campus_home_modules": False,
                    "campus_hotintern_city": "北京",
                    "campus_hotcompany_industry": "互联网",
                }
            },
        )
        fake_status = {
            "task_id": "task-shixiseng-1",
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
            sources=["shixiseng"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="requests_only",
            source_options={
                "shixiseng": {
                    "track": "campus",
                    "detail_workers": 3,
                    "detail_rate_per_second": 2.5,
                    "include_campus_home_modules": False,
                    "campus_hotintern_city": "北京",
                    "campus_hotcompany_industry": "互联网",
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["shixiseng"])
        self.assertFalse(result["data"]["config"]["source_options"]["shixiseng"]["include_campus_home_modules"])

    def test_get_status_preserves_shixiseng_trace(self) -> None:
        fake_status = {
            "task_id": "task-shixiseng-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 21:00:00",
            "finished_at": "2026-03-30 21:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["shixiseng"],
                "cities": ["北京"],
                "source_options": {
                    "shixiseng": {
                        "track": "campus",
                        "detail_workers": 4,
                        "detail_rate_per_second": 1.5,
                        "include_campus_home_modules": True,
                    }
                },
            },
            "last_result": {
                "campus_home": {"job_items": 3, "company_items": 2},
                "shixiseng_summary": {
                    "trace_count": 1,
                    "campus_home_jobs": 3,
                    "campus_home_companies": 2,
                    "detail_mode": "api",
                    "track": "campus",
                },
                "shixiseng_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "status": "target_pages_reached",
                        "pages_completed": 2,
                        "total_items": 20,
                        "estimated_total_pages": 5,
                        "fetched_count": 8,
                        "new_count": 3,
                        "updated_count": 1,
                        "detail_mode": "api",
                        "track": "campus",
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
        self.assertEqual(result["data"]["last_result"]["campus_home"]["job_items"], 3)
        self.assertEqual(result["data"]["last_result"]["shixiseng_summary"]["detail_mode"], "api")
        self.assertEqual(result["data"]["last_result"]["shixiseng_trace"][0]["status"], "target_pages_reached")
        self.assertEqual(result["data"]["last_result"]["shixiseng_trace"][0]["track"], "campus")


if __name__ == "__main__":
    unittest.main()