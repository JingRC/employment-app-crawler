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

from app.services import crawler_service  # noqa: E402


class CrawlerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        crawler_service._CANCEL_EVENT.clear()
        with crawler_service._STATUS_LOCK:
            crawler_service._STATUS.clear()
            crawler_service._STATUS.update(dict(crawler_service._DEFAULT_STATUS))

    def test_run_incremental_crawl_updates_status_and_recent_tasks_for_mixed_sources(self) -> None:
        config = {
            "sources": ["boss", "shixiseng"],
            "queries": ["Java"],
            "cities": ["北京"],
            "max_pages": 2,
            "page_size": 30,
            "runtime_mode": "requests_only",
            "stale_after_hours": 24,
            "source_options": {"shixiseng": {"track": "campus"}},
        }

        def fake_run_incremental_crawl_for_sources(**kwargs):
            kwargs["progress_callback"](
                "来源执行过程日志",
                {
                    "source_code": "boss",
                    "city_name": "北京",
                    "query": "Java",
                    "page": 1,
                    "branch": "dom",
                    "branch_label": "来源分支: 结果页DOM",
                    "debug_snapshot_path": "debug/path.json",
                },
            )
            return {
                "total_fetched": 5,
                "new_to_db": 3,
                "sources": [
                    {"source_code": "boss", "status": "success", "total_fetched": 2, "new_to_db": 1},
                    {"source_code": "shixiseng", "status": "success", "total_fetched": 3, "new_to_db": 2},
                ],
                "source_details": {
                    "boss": {"boss_summary": {"trace_count": 1}},
                    "shixiseng": {"shixiseng_summary": {"trace_count": 1}},
                },
                "boss_summary": {"trace_count": 1},
                "shixiseng_summary": {"trace_count": 1},
            }

        with patch.object(crawler_service, "run_incremental_crawl_for_sources", side_effect=fake_run_incremental_crawl_for_sources), patch.object(
            crawler_service,
            "mark_stale_jobs_inactive",
            return_value={"inactive_marked": 2, "stale_after_hours": 24, "cutoff_time": "2026-03-29 23:30:00"},
        ), patch.object(
            crawler_service,
            "verify_pending_inactive_jobs",
            return_value={
                "verified_count": 2,
                "restored_count": 1,
                "confirmed_count": 1,
                "review_count": 0,
                "missing_url_count": 0,
                "limit": 5,
                "timeout_seconds": 6.0,
            },
        ), patch.object(
            crawler_service,
            "set_job_stale_hours",
        ), patch.object(
            crawler_service,
            "_now_text",
            side_effect=[
                "2026-03-30 23:30:00",
                "2026-03-30 23:30:01",
                "2026-03-30 23:30:02",
                "2026-03-30 23:30:03",
                "2026-03-30 23:30:04",
                "2026-03-30 23:30:05",
                "2026-03-30 23:30:06",
            ],
        ):
            crawler_service._run_incremental_crawl("task-mixed-1", config)

        status = crawler_service.get_crawl_status()
        self.assertEqual(status["status"], "success")
        self.assertIn("检测下架 2 条", status["message"])
        self.assertIn("强校验恢复 1 条", status["message"])
        self.assertEqual(status["last_result"]["inactive_marked"], 2)
        self.assertEqual(status["last_result"]["stale_after_hours"], 24)
        self.assertEqual(status["last_result"]["offline_verified_count"], 2)
        self.assertEqual(status["last_result"]["offline_restored_count"], 1)
        self.assertEqual(status["last_result"]["offline_confirmed_count"], 1)
        self.assertEqual(status["last_result"]["offline_review_count"], 0)
        self.assertEqual(status["last_result"]["offline_missing_url_count"], 0)
        self.assertEqual(status["last_result"]["offline_strong_check_limit"], 5)
        self.assertEqual(status["last_result"]["offline_strong_check_timeout_seconds"], 6.0)
        self.assertEqual(status["last_result"]["source_details"]["boss"]["boss_summary"]["trace_count"], 1)
        self.assertEqual(status["last_result"]["source_details"]["shixiseng"]["shixiseng_summary"]["trace_count"], 1)
        self.assertEqual(status["logs"][1]["source_code"], "boss")
        self.assertEqual(status["logs"][1]["branch"], "dom")
        self.assertEqual(status["logs"][1]["debug_snapshot_path"], "debug/path.json")
        self.assertEqual(status["logs"][-2]["message"], "岗位下架检测完成：标记 2 条为 inactive")
        self.assertEqual(status["logs"][-1]["message"], "岗位下架强校验完成：校验 2 条 / 恢复 1 条 / 确认下架 1 条 / 待人工复核 0 条 / 缺少链接 0 条")
        self.assertEqual(status["recent_tasks"][0]["result"]["source_details"]["boss"]["boss_summary"]["trace_count"], 1)
        self.assertEqual(status["recent_tasks"][0]["result"]["inactive_marked"], 2)
        self.assertEqual(status["recent_tasks"][0]["result"]["offline_restored_count"], 1)
        self.assertEqual(status["recent_tasks"][0]["logs"][1]["source_code"], "boss")



if __name__ == "__main__":
    unittest.main()