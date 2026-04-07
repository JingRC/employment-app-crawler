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
from app.schemas.crawl import BossCookieManualSaveRequest, CrawlTriggerRequest  # noqa: E402


class CrawlerBossRouteTests(unittest.TestCase):
    def test_start_incremental_job_crawl_forwards_boss_config(self) -> None:
        body = CrawlTriggerRequest(
            sources=["boss"],
            queries=["Java"],
            cities=["北京"],
            max_pages=2,
            page_size=30,
            runtime_mode="requests_only",
            source_options={},
        )
        fake_status = {
            "task_id": "task-boss-1",
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
            stale_after_hours=72,
            source_options={},
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["config"]["sources"], ["boss"])
        self.assertEqual(result["data"]["config"]["runtime_mode"], "requests_only")
        self.assertEqual(result["data"]["config"]["stale_after_hours"], 72)

    def test_get_status_preserves_boss_trace(self) -> None:
        fake_status = {
            "task_id": "task-boss-status-1",
            "status": "success",
            "is_running": False,
            "message": "增量更新完成",
            "started_at": "2026-03-30 23:00:00",
            "finished_at": "2026-03-30 23:02:00",
            "cancel_requested": False,
            "config": {
                "sources": ["boss"],
                "cities": ["北京"],
                "runtime_mode": "requests_only",
                "source_options": {},
            },
            "last_result": {
                "boss_summary": {
                    "trace_count": 1,
                    "risk_control_hits": 1,
                    "rate_limit_hits": 1,
                    "request_failures": 1,
                    "cookie_refreshes": 1,
                    "runtime_mode": "requests_only",
                },
                "boss_trace": [
                    {
                        "query": "Java",
                        "location_name": "北京",
                        "city_code": "101010100",
                        "status": "code_37",
                        "pages_completed": 1,
                        "fetched_count": 2,
                        "request_failures": 1,
                        "rate_limit_hits": 1,
                        "risk_control_hits": 1,
                        "cookie_refreshes": 1,
                        "last_code": "37",
                        "runtime_mode": "requests_only",
                        "new_count": 1,
                        "updated_count": 1,
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
        self.assertEqual(result["data"]["last_result"]["boss_summary"]["risk_control_hits"], 1)
        self.assertEqual(result["data"]["last_result"]["boss_trace"][0]["status"], "code_37")
        self.assertEqual(result["data"]["last_result"]["boss_trace"][0]["last_code"], "37")

    def test_save_boss_cookie_persists_manual_cookie(self) -> None:
        module = type(
            "BossModule",
            (),
            {
                "persist_cookie_bundle": lambda self, cookie_text, runtime_mode='requests_only': None,
                "load_local_secrets": lambda self: {
                    "cookie": "__zp_stoken__=abc; wt2=def",
                    "cookie_refreshed_at": "2026-04-07 10:00:00",
                    "cookie_runtime_mode": "requests_only",
                },
                "probe_persisted_cookie": lambda self, query, city, runtime_mode='requests_only': {
                    "cookie_valid": True,
                    "missing_keys": [],
                    "validation_mode": "api_probe",
                    "probe_code": "0",
                    "probe_message": "ok",
                    "message": "Boss Cookie 可用",
                },
            },
        )()

        with patch.object(crawler, "load_source_module", return_value=module):
            result = crawler.save_boss_cookie(BossCookieManualSaveRequest(cookie_text="Cookie: __zp_stoken__=abc; wt2=def"))

        self.assertEqual(result["code"], 0)
        self.assertTrue(result["data"]["cookie_present"])
        self.assertTrue(result["data"]["cookie_valid"])
        self.assertEqual(result["data"]["browser_preference"], "manual")

    def test_save_boss_cookie_returns_error_when_invalid(self) -> None:
        module = type(
            "BossModule",
            (),
            {
                "persist_cookie_bundle": lambda self, cookie_text, runtime_mode='requests_only': (_ for _ in ()).throw(ValueError("持久化 cookie 不完整")),
            },
        )()

        with patch.object(crawler, "load_source_module", return_value=module):
            result = crawler.save_boss_cookie(BossCookieManualSaveRequest(cookie_text="bad-cookie"))

        self.assertEqual(result["code"], 1)
        self.assertIn("持久化 cookie 不完整", result["message"])


if __name__ == "__main__":
    unittest.main()