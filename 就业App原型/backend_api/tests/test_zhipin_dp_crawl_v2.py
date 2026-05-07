from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import zhipin_dp_crawl_v2 as boss_dp  # noqa: E402


class DummyListener:
    def start(self, *args, **kwargs):
        return None

    def stop(self):
        return None

    def wait(self, timeout=0):
        class Packet:
            response = type("Resp", (), {"body": {"code": 0, "zpData": {"jobList": [{"jobName": "职位-1", "brandName": "测试公司", "cityName": "北京", "encryptJobId": "enc-1"}]}}})()
        return Packet()


class DummyPage:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.title = "Boss"
        self.url = "https://www.zhipin.com/"
        self.listen = DummyListener()

    def get(self, url):
        self.url = url
        return None

    def quit(self):
        return None

    def eles(self, selector):
        return []


class DummyChromiumOptions:
    def __init__(self, address: str = "") -> None:
        self.address = address
        self._address = address

    def set_address(self, value: str) -> None:
        self.address = value
        self._address = value

    def set_local_port(self, port: int) -> None:
        self.set_address(f"127.0.0.1:{port}")


class ZhipinDpCrawlV2Tests(unittest.TestCase):
    def test_ensure_chromium_debug_address_keeps_full_address(self) -> None:
        options = DummyChromiumOptions("127.0.0.1:9222")

        address = boss_dp.ensure_chromium_debug_address(options)

        self.assertEqual(address, "127.0.0.1:9222")
        self.assertEqual(options.address, "127.0.0.1:9222")

    def test_ensure_chromium_debug_address_normalizes_port_only(self) -> None:
        options = DummyChromiumOptions("9222")

        address = boss_dp.ensure_chromium_debug_address(options)

        self.assertEqual(address, "127.0.0.1:9222")
        self.assertEqual(options.address, "127.0.0.1:9222")

    def test_ensure_chromium_debug_address_allocates_port_when_missing(self) -> None:
        options = DummyChromiumOptions("")

        with patch.object(boss_dp, "reserve_local_debug_port", return_value=9333):
            address = boss_dp.ensure_chromium_debug_address(options)

        self.assertEqual(address, "127.0.0.1:9333")
        self.assertEqual(options.address, "127.0.0.1:9333")

    def test_run_incremental_update_returns_boss_dp_trace(self) -> None:
        with patch.object(boss_dp, "ensure_db"), patch.object(boss_dp, "ChromiumPage", return_value=DummyPage()), patch.object(
            boss_dp, "safe_sleep"
        ), patch.object(
            boss_dp, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ), patch.object(
            boss_dp, "random"
        ) as random_mock:
            random_mock.uniform.return_value = 0.0
            result = boss_dp.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=1,
                page_size=30,
            )

        self.assertEqual(result["total_fetched"], 1)
        self.assertEqual(result["new_to_db"], 1)
        self.assertEqual(result["boss_dp_summary"]["trace_count"], 1)
        self.assertEqual(result["boss_dp_summary"]["api_pages"], 1)
        self.assertEqual(result["boss_dp_summary"]["html_fallback_pages"], 0)
        self.assertEqual(result["boss_dp_summary"]["verify_hits"], 0)
        self.assertEqual(result["boss_dp_summary"]["page_load_failures"], 0)
        self.assertEqual(result["boss_dp_summary"]["runtime_mode"], "hybrid")
        self.assertEqual(result["boss_dp_summary"]["pair_ordering_strategy"], "deferred_high_risk")
        self.assertEqual(result["boss_dp_summary"]["deferred_pair_count"], 1)
        self.assertEqual(result["boss_dp_summary"]["deferred_pairs"], [{"query": "Java", "city": "北京"}])
        self.assertEqual(
            result["boss_dp_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "city_code": "101010100",
                    "status": "target_pages_reached",
                    "pages_completed": 1,
                    "fetched_count": 1,
                    "new_count": 1,
                    "updated_count": 0,
                    "api_pages": 1,
                    "html_fallback_pages": 0,
                    "verify_hits": 0,
                    "page_load_failures": 0,
                    "runtime_mode": "hybrid",
                    "risk_bucket": "deferred_high_risk",
                    "schedule_order": 1,
                }
            ],
        )

    def test_build_ordered_target_pairs_moves_high_risk_pair_to_end(self) -> None:
        ordered_pairs, deferred_pairs, strategy = boss_dp.build_ordered_target_pairs(
            prepared_queries=["Java", "Python"],
            city_items=[("101010100", "北京"), ("101020100", "上海")],
            source_options={"defer_high_risk_pairs": True},
        )

        self.assertEqual(strategy, "deferred_high_risk")
        self.assertEqual(deferred_pairs, [{"query": "Java", "city": "北京"}])
        self.assertEqual(
            [(item["query"], item["city_name"], item["risk_bucket"], item["schedule_order"]) for item in ordered_pairs],
            [
                ("Java", "上海", "normal", 1),
                ("Python", "北京", "normal", 2),
                ("Python", "上海", "normal", 3),
                ("Java", "北京", "deferred_high_risk", 4),
            ],
        )


if __name__ == "__main__":
    unittest.main()