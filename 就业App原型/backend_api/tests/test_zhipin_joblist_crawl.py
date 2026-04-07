from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import zhipin_joblist_crawl as boss  # noqa: E402


class DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ZhipinJoblistCrawlTests(unittest.TestCase):
    def test_crawl_jobs_hybrid_batch_returns_boss_trace(self) -> None:
        trace_meta = {
            "query": "Java",
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
        }

        with patch.object(boss, "load_local_secrets", return_value={"cookie": "mock-cookie"}), patch.object(
            boss, "load_ssl_options", return_value=True
        ), patch.object(
            boss, "requests"
        ) as requests_mock, patch.object(
            boss, "crawl_jobs_with_context", return_value=(
                [
                    {"job_name": "职位-1", "brand": "测试公司", "city": "北京", "salary": "20-30K"},
                    {"job_name": "职位-2", "brand": "测试公司", "city": "北京", "salary": "25-35K"},
                ],
                {"cookie": "mock-cookie"},
                trace_meta,
            )
        ), patch.object(
            boss, "save_results"
        ), patch.object(
            boss, "save_to_database", return_value={"new": 1, "updated": 1, "unchanged": 0}
        ), patch.object(
            boss, "safe_sleep"
        ):
            requests_mock.Session.return_value = DummySession()
            result = boss.crawl_jobs_hybrid_batch(
                queries=["Java"],
                cities=["北京"],
                max_pages=2,
                page_size=30,
                output_dir=Path("."),
                runtime_mode="requests_only",
            )

        self.assertEqual(result["total_fetched"], 2)
        self.assertEqual(result["new_to_db"], 1)
        self.assertEqual(result["runtime_mode"], "requests_only")
        self.assertEqual(
            result["boss_summary"],
            {
                "trace_count": 1,
                "risk_control_hits": 1,
                "rate_limit_hits": 1,
                "request_failures": 1,
                "cookie_refreshes": 1,
                "runtime_mode": "requests_only",
            },
        )
        self.assertEqual(
            result["boss_trace"],
            [
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
        )


if __name__ == "__main__":
    unittest.main()