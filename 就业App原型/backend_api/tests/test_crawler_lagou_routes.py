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


class CrawlerLagouRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_lagou_source_options(self) -> None:
        body = CrawlTriggerRequest(
            sources=["lagou"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "lagou": {
                    "verification_wait_seconds": 120,
                    "capture_debug_snapshot": False,
                    "stop_on_all_seen_page": False,
                }
            },
        )
        fake_status = {
            "task_id": "task-lagou-1",
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
            sources=["lagou"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=20,
            runtime_mode="browser",
            source_options={
                "lagou": {
                    "verification_wait_seconds": 120,
                    "capture_debug_snapshot": False,
                    "stop_on_all_seen_page": False,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["lagou"])
        self.assertFalse(result["data"]["config"]["source_options"]["lagou"]["capture_debug_snapshot"])

    def test_get_status_preserves_lagou_trace(self) -> None:
        fake_status = {
            "task_id": "task-lagou-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 22:00:00",
            "finished_at": "2026-03-30 22:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["lagou"],
                "cities": ["北京"],
                "source_options": {
                    "lagou": {
                        "verification_wait_seconds": 90,
                        "capture_debug_snapshot": True,
                        "stop_on_all_seen_page": True,
                    }
                },
            },
            "last_result": {
                "debug_snapshot_paths": ["debug/lagou/p2.json"],
                "lagou_summary": {
                    "trace_count": 1,
                    "branch_counts": {"next_data": 1, "dom": 1},
                    "debug_snapshot_count": 1,
                    "detail_mode": "manual_verification_next_data_or_dom",
                },
                "lagou_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "status": "target_pages_reached",
                        "pages_completed": 2,
                        "fetched_count": 6,
                        "new_count": 2,
                        "updated_count": 1,
                        "last_branch": "dom",
                        "last_branch_label": "结果页DOM",
                        "branch_counts": {"next_data": 1, "dom": 1},
                        "debug_snapshot_path": "debug/lagou/p2.json",
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
        self.assertEqual(result["data"]["last_result"]["debug_snapshot_paths"], ["debug/lagou/p2.json"])
        self.assertEqual(result["data"]["last_result"]["lagou_summary"]["debug_snapshot_count"], 1)
        self.assertEqual(result["data"]["last_result"]["lagou_trace"][0]["status"], "target_pages_reached")
        self.assertEqual(result["data"]["last_result"]["lagou_trace"][0]["last_branch"], "dom")


if __name__ == "__main__":
    unittest.main()