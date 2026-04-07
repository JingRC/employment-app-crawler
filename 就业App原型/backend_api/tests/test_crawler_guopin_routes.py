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


class CrawlerGuopinRouteTests(unittest.TestCase):
    def test_get_guopin_cities_returns_lightweight_city_items(self) -> None:
        fake_items = [{"city_name": "北京", "city_code": "000000.110000", "district_count": 16}]
        with patch.object(crawler, "_build_guopin_city_catalog", return_value=fake_items):
            result = crawler.get_guopin_cities()

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["items"], fake_items)

    def test_get_guopin_districts_filters_by_city_name(self) -> None:
        fake_items = [{"district_name": "朝阳区", "target_value": "北京-朝阳区", "district_code": "000000.110000.110100.110105"}]
        with patch.object(crawler, "_get_guopin_district_items", return_value=fake_items) as get_items_mock:
            result = crawler.get_guopin_districts("北京")

        get_items_mock.assert_called_once_with("北京")
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["items"], fake_items)

    def test_start_incremental_job_crawl_forwards_guopin_district_only_config(self) -> None:
        body = CrawlTriggerRequest(
            sources=["guopin"],
            queries=["Java"],
            cities=[],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            source_options={
                "guopin": {
                    "detail_mode": "detail_api",
                    "api_page_size": 50,
                    "district_targets": ["北京-海淀区", "北京-不存在区"],
                    "use_district_targets_only": True,
                }
            },
        )
        fake_status = {
            "task_id": "task-guopin-1",
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
            sources=["guopin"],
            queries=["Java"],
            cities=[],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            source_options={
                "guopin": {
                    "detail_mode": "detail_api",
                    "api_page_size": 50,
                    "district_targets": ["北京-海淀区", "北京-不存在区"],
                    "use_district_targets_only": True,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["cities"], [])
        self.assertTrue(result["data"]["config"]["source_options"]["guopin"]["use_district_targets_only"])

    def test_start_incremental_job_crawl_preserves_mixed_sources_and_global_cities(self) -> None:
        body = CrawlTriggerRequest(
            sources=["guopin", "boss"],
            queries=["Python"],
            cities=["青岛", "上海"],
            max_pages=1,
            page_size=20,
            runtime_mode="requests_only",
            source_options={
                "guopin": {
                    "district_targets": ["北京-朝阳区"],
                    "use_district_targets_only": True,
                }
            },
        )
        fake_status = {
            "task_id": "task-mixed-1",
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
            sources=["guopin", "boss"],
            queries=["Python"],
            cities=["青岛", "上海"],
            max_pages=1,
            page_size=20,
            runtime_mode="requests_only",
            source_options={
                "guopin": {
                    "district_targets": ["北京-朝阳区"],
                    "use_district_targets_only": True,
                }
            },
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["guopin", "boss"])
        self.assertEqual(result["data"]["config"]["cities"], ["青岛", "上海"])

    def test_get_status_preserves_unresolved_district_targets_in_last_result(self) -> None:
        fake_status = {
            "task_id": "task-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 10:00:00",
            "finished_at": "2026-03-30 10:01:00",
            "cancel_requested": False,
            "config": {
                "sources": ["guopin"],
                "source_options": {"guopin": {"district_targets": ["北京-海淀区", "北京-不存在区"]}},
            },
            "last_result": {
                "resolved_city_codes": {"北京-海淀区": "000000.110000.110100.110108"},
                "unresolved_district_targets": ["北京-不存在区"],
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
        self.assertEqual(result["data"]["last_result"]["unresolved_district_targets"], ["北京-不存在区"])
        self.assertEqual(
            result["data"]["last_result"]["resolved_city_codes"],
            {"北京-海淀区": "000000.110000.110100.110108"},
        )


if __name__ == "__main__":
    unittest.main()