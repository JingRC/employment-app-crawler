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


class FakeChromiumOptions:
    def __init__(self) -> None:
        self.address = ""
        self.arguments: list[str] = []
        self.auto_port_calls: list[tuple[bool, object]] = []
        self.browser_path = ""
        self.headless_calls: list[bool] = []
        self.user_data_path = ""

    def auto_port(self, on_off: bool = True, scope: object = None) -> None:
        self.auto_port_calls.append((on_off, scope))

    def set_browser_path(self, path: str) -> None:
        self.browser_path = path

    def headless(self, on_off: bool = True) -> None:
        self.headless_calls.append(on_off)

    def set_user_data_path(self, path: str) -> None:
        self.user_data_path = path

    def set_local_port(self, port: int) -> None:
        self.address = f"127.0.0.1:{port}"

    def set_address(self, address: str) -> None:
        self.address = address

    def set_argument(self, argument: str) -> None:
        self.arguments.append(argument)


class Job51JoblistCrawlTests(unittest.TestCase):
    def test_build_browser_options_enables_ci_headless_profile(self) -> None:
        with patch.object(job51, "ChromiumOptions", FakeChromiumOptions), patch.object(
            job51, "reserve_local_debug_port", return_value=9444
        ), patch.object(
            job51.tempfile, "mkdtemp", return_value="/tmp/job51-ci-profile"
        ), patch.dict(
            job51.os.environ,
            {"GITHUB_ACTIONS": "true", "CHROME_PATH": "/tmp/chrome"},
            clear=False,
        ):
            options = job51.build_browser_options()

        self.assertEqual(options.auto_port_calls, [(True, None)])
        self.assertEqual(options.browser_path, "/tmp/chrome")
        self.assertEqual(options.headless_calls, [True])
        self.assertEqual(options.user_data_path, "/tmp/job51-ci-profile")
        self.assertEqual(options.address, "127.0.0.1:9444")
        self.assertIn("--disable-dev-shm-usage", options.arguments)
        self.assertEqual(getattr(options, "_copilot_temp_user_data_path"), "/tmp/job51-ci-profile")

    def test_cleanup_temp_browser_data_dir_ignores_errors(self) -> None:
        with patch.object(job51.shutil, "rmtree") as mocked_rmtree:
            job51.cleanup_temp_browser_data_dir("/tmp/job51-ci-profile")

        mocked_rmtree.assert_called_once_with("/tmp/job51-ci-profile", ignore_errors=True)

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
