from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import zhilian_joblist_crawl as zhilian  # noqa: E402


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


class ZhilianJoblistCrawlTests(unittest.TestCase):
    def test_build_browser_options_enables_ci_headless_profile(self) -> None:
        with patch.object(zhilian, "ChromiumOptions", FakeChromiumOptions), patch.object(
            zhilian, "reserve_local_debug_port", return_value=9333
        ), patch.object(
            zhilian.tempfile, "mkdtemp", return_value="/tmp/zhilian-ci-profile"
        ), patch.dict(
            zhilian.os.environ,
            {"GITHUB_ACTIONS": "true", "CHROME_PATH": "/tmp/chrome"},
            clear=False,
        ):
            options = zhilian.build_browser_options()

        self.assertEqual(options.auto_port_calls, [(True, None)])
        self.assertEqual(options.browser_path, "/tmp/chrome")
        self.assertEqual(options.headless_calls, [True])
        self.assertEqual(options.user_data_path, "/tmp/zhilian-ci-profile")
        self.assertEqual(options.address, "127.0.0.1:9333")
        self.assertIn("--disable-dev-shm-usage", options.arguments)
        self.assertEqual(getattr(options, "_copilot_temp_user_data_path"), "/tmp/zhilian-ci-profile")

    def test_cleanup_temp_browser_data_dir_ignores_errors(self) -> None:
        with patch.object(zhilian.shutil, "rmtree") as mocked_rmtree:
            zhilian.cleanup_temp_browser_data_dir("/tmp/zhilian-ci-profile")

        mocked_rmtree.assert_called_once_with("/tmp/zhilian-ci-profile", ignore_errors=True)

    def test_normalize_source_options_parses_string_booleans(self) -> None:
        result = zhilian.normalize_source_options(
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
        result = zhilian.normalize_source_options(
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
        page_click_results = [
            {"payload": {"items": [{"jobId": "job-2"}], "count": 8, "pages": 5}, "request_sample": {"url": "https://example.com/api"}},
        ]
        request_page_results = [
            {"payload": {"items": [{"jobId": "job-3"}], "count": 8, "pages": 5}, "request_sample": {"url": "https://example.com/api"}},
        ]

        with patch.object(zhilian, "ensure_db"), patch.object(zhilian, "build_browser_options", return_value=object()), patch.object(
            zhilian, "ChromiumPage", DummyPage
        ), patch.object(
            zhilian, "load_search_items_with_retry", return_value=([{"jobId": "job-1"}], 8, 5)
        ), patch.object(
            zhilian, "extract_initial_state", return_value={}
        ), patch.object(
            zhilian, "extract_page_payload_from_state", return_value={"items": [{"jobId": "job-1"}], "count": 8, "pages": 5, "city_code": "530"}
        ), patch.object(
            zhilian, "load_positions_api_page_via_click", side_effect=page_click_results
        ), patch.object(
            zhilian, "load_positions_api_page_via_request_sample", side_effect=request_page_results
        ), patch.object(
            zhilian, "replay_positions_api_sample", return_value={"ok": True, "items": 20}
        ), patch.object(
            zhilian,
            "normalize_job_item",
            side_effect=lambda item: {"source_job_id": item["jobId"], "title": f"职位-{item['jobId']}", "company_name": "测试公司"},
        ), patch.object(
            zhilian, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = zhilian.run_incremental_update(
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
        self.assertEqual(result["request_probe_successes"], 1)
        self.assertEqual(result["request_page_attempts"], 1)
        self.assertEqual(result["request_page_successes"], 1)
        self.assertEqual(result["captured_request_samples"], 1)
        self.assertEqual(
            result["zhilian_request_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "city_code": "530",
                    "status": "target_pages_reached",
                    "pages_completed": 3,
                    "total_items": 8,
                    "fetched_count": 3,
                    "new_count": 3,
                    "updated_count": 0,
                    "request_probe_attempts": 1,
                    "request_probe_successes": 1,
                    "request_page_attempts": 1,
                    "request_page_successes": 1,
                    "captured_request_sample": True,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
