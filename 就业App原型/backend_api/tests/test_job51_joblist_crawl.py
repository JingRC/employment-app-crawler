from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import job51_joblist_crawl as job51  # noqa: E402


class DummyPage:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def quit(self) -> None:
        return None


class Job51JoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_string_booleans(self) -> None:
        result = job51.normalize_source_options(
            {
                "enable_request_probe": "false",
                "prefer_request_pages": "0",
                "probe_timeout_seconds": "12.5",
            }
        )

        self.assertFalse(result["enable_request_probe"])
        self.assertFalse(result["prefer_request_pages"])
        self.assertEqual(result["probe_timeout_seconds"], 12.5)

    def test_normalize_source_options_clamps_timeout_and_keeps_defaults(self) -> None:
        result = job51.normalize_source_options(
            {
                "enable_request_probe": "",
                "prefer_request_pages": None,
                "probe_timeout_seconds": "99",
            }
        )

        self.assertTrue(result["enable_request_probe"])
        self.assertTrue(result["prefer_request_pages"])
        self.assertEqual(result["probe_timeout_seconds"], 20.0)

    def test_run_incremental_update_returns_request_trace(self) -> None:
        click_results = [
            {
                "items": [{"jobId": "job-2"}],
                "total_count": 9,
                "request_sample": {"url": "https://example.com/job51-api"},
            }
        ]
        request_results = [
            {
                "payload": {"items": [{"jobId": "job-3"}], "total_count": 9},
                "request_sample": {"url": "https://example.com/job51-api"},
            },
            {
                "payload": {"items": [{"jobId": "job-4"}], "total_count": 9},
                "request_sample": {"url": "https://example.com/job51-api"},
            },
        ]

        with patch.object(job51, "ensure_db"), patch.object(job51, "fetch_city_code_map", return_value={"全国": "", "北京": "010000"}), patch.object(
            job51, "build_browser_options", return_value=object()
        ), patch.object(
            job51, "ChromiumPage", DummyPage
        ), patch.object(
            job51,
            "capture_current_page_payload",
            return_value={"items": [{"jobId": "job-1"}], "total_count": 9, "request_sample": {"url": "https://example.com/job51-api"}},
        ), patch.object(
            job51, "replay_list_api_sample", return_value={"ok": False, "reason": "non_json_response"}
        ), patch.object(
            job51, "replay_list_api_sample_with_browser_prewarm", return_value={"ok": True, "items": 20, "browser_cookie_count": 3}
        ), patch.object(
            job51, "load_page_via_request_sample", side_effect=request_results
        ), patch.object(
            job51, "load_page_via_click", side_effect=click_results
        ), patch.object(
            job51,
            "normalize_job_item",
            side_effect=lambda item: {"source_job_id": item["jobId"], "title": f"职位-{item['jobId']}", "company_name": "测试公司"},
        ), patch.object(
            job51, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = job51.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=3,
                page_size=20,
                source_options={
                    "enable_request_probe": True,
                    "prefer_request_pages": True,
                    "probe_timeout_seconds": 8,
                },
            )

        self.assertEqual(result["request_probe_attempts"], 1)
        self.assertEqual(result["request_probe_successes"], 0)
        self.assertEqual(result["preheated_probe_attempts"], 1)
        self.assertEqual(result["preheated_probe_successes"], 1)
        self.assertEqual(result["request_page_attempts"], 2)
        self.assertEqual(result["request_page_successes"], 2)
        self.assertEqual(result["captured_request_samples"], 1)
        self.assertEqual(
            result["job51_request_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "city_code": "010000",
                    "status": "target_pages_reached",
                    "pages_completed": 3,
                    "total_items": 9,
                    "fetched_count": 3,
                    "new_count": 3,
                    "updated_count": 0,
                    "request_probe_attempts": 1,
                    "request_probe_successes": 0,
                    "preheated_probe_attempts": 1,
                    "preheated_probe_successes": 1,
                    "request_page_attempts": 2,
                    "request_page_successes": 2,
                    "captured_request_sample": True,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
