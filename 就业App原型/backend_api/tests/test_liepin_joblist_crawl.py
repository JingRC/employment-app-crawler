from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import liepin_joblist_crawl as liepin  # noqa: E402


class DummyPage:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def quit(self) -> None:
        return None


class LiepinJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_string_booleans(self) -> None:
        result = liepin.normalize_source_options(
            {
                "city_mode": "precise_if_supported",
                "enable_request_probe": "false",
                "probe_timeout_seconds": "12.5",
            }
        )

        self.assertEqual(result["city_mode"], "precise_if_supported")
        self.assertFalse(result["enable_request_probe"])
        self.assertEqual(result["probe_timeout_seconds"], 12.5)

    def test_normalize_source_options_clamps_timeout_and_falls_back_city_mode(self) -> None:
        result = liepin.normalize_source_options(
            {
                "city_mode": "unknown_mode",
                "enable_request_probe": "",
                "probe_timeout_seconds": "99",
            }
        )

        self.assertEqual(result["city_mode"], "precise_if_supported")
        self.assertTrue(result["enable_request_probe"])
        self.assertEqual(result["probe_timeout_seconds"], 20.0)

    def test_run_incremental_update_returns_request_trace(self) -> None:
        first_payload = {
            "items": [{"jobId": "job-1"}],
            "request_sample": {"url": "https://example.com/liepin-api"},
        }
        second_payload = {
            "items": [{"jobId": "job-2"}],
            "request_sample": {"url": "https://example.com/liepin-api?page=2"},
        }

        with patch.object(liepin, "ensure_db"), patch.object(liepin, "build_browser_options", return_value=object()), patch.object(
            liepin, "ChromiumPage", DummyPage
        ), patch.object(
            liepin,
            "capture_current_page_payload",
            side_effect=lambda *args, **kwargs: kwargs["resolved_city_entries"].update({"北京": {"code": "010", "name": "北京", "search_url": "https://www.liepin.com/city-beijing/"}}) or kwargs["footer_city_pages"].update({"北京": "https://www.liepin.com/city-beijing/"}) or first_payload,
        ), patch.object(
            liepin, "load_page_via_click", return_value=second_payload
        ), patch.object(
            liepin, "replay_list_api_sample", return_value={"ok": True, "items": 20, "current_page": 1, "city_code": "010"}
        ), patch.object(
            liepin, "extract_page_signature_token", side_effect=lambda item: item.get("jobId") or ""
        ), patch.object(
            liepin,
            "normalize_job_item",
            side_effect=lambda item: {"source_job_id": item["jobId"], "title": f"职位-{item['jobId']}", "company_name": "测试公司", "city_name": "北京"},
        ), patch.object(
            liepin, "city_matches", return_value=True
        ), patch.object(
            liepin, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = liepin.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=2,
                page_size=20,
                source_options={
                    "city_mode": "precise_if_supported",
                    "enable_request_probe": True,
                    "probe_timeout_seconds": 8,
                },
            )

        self.assertEqual(result["request_probe_attempts"], 1)
        self.assertEqual(result["request_probe_successes"], 1)
        self.assertEqual(result["captured_request_samples"], 1)
        self.assertEqual(
            result["liepin_request_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "status": "target_pages_reached",
                    "pages_completed": 2,
                    "fetched_count": 2,
                    "new_count": 2,
                    "updated_count": 0,
                    "request_probe_attempts": 1,
                    "request_probe_successes": 1,
                    "captured_request_sample": True,
                    "resolved_city_code": "010",
                    "resolved_city_name": "北京",
                    "resolved_search_url": "https://www.liepin.com/city-beijing/",
                    "footer_city_page": "https://www.liepin.com/city-beijing/",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
