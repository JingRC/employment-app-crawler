from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import lagou_joblist_crawl as lagou  # noqa: E402


class DummyPage:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def quit(self) -> None:
        return None


class LagouJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_string_booleans(self) -> None:
        result = lagou.normalize_source_options(
            {
                "verification_wait_seconds": "400",
                "capture_debug_snapshot": "false",
                "stop_on_all_seen_page": "0",
            }
        )

        self.assertEqual(result["verification_wait_seconds"], 300)
        self.assertFalse(result["capture_debug_snapshot"])
        self.assertFalse(result["stop_on_all_seen_page"])

    def test_run_incremental_update_returns_trace_and_summary(self) -> None:
        first_payload = {
            "items": [
                {"source_job_id": "job-1", "title": "职位-1", "company_name": "测试公司", "city_name": "北京"}
            ],
            "from_next_data": True,
            "current_page": 1,
        }
        second_payload = {
            "items": [
                {"source_job_id": "job-2", "title": "职位-2", "company_name": "测试公司", "city_name": "北京"}
            ],
            "from_dom": True,
            "current_page": 2,
            "debug_snapshot_path": "debug/lagou/p2.json",
        }

        with patch.object(lagou, "ensure_db"), patch.object(lagou, "build_browser_options", return_value=object()), patch.object(
            lagou, "ChromiumPage", return_value=DummyPage()
        ), patch.object(
            lagou, "capture_current_page_jobs", return_value=first_payload
        ), patch.object(
            lagou, "load_page_via_click", return_value=second_payload
        ), patch.object(
            lagou, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = lagou.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=2,
                page_size=20,
                source_options={
                    "verification_wait_seconds": 90,
                    "capture_debug_snapshot": True,
                    "stop_on_all_seen_page": True,
                },
            )

        self.assertEqual(result["total_fetched"], 2)
        self.assertEqual(result["new_to_db"], 2)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["lagou_summary"]["trace_count"], 1)
        self.assertEqual(result["lagou_summary"]["debug_snapshot_count"], 1)
        self.assertEqual(result["lagou_summary"]["branch_counts"], {"next_data": 1, "dom": 1})
        self.assertEqual(
            result["lagou_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "status": "target_pages_reached",
                    "pages_completed": 2,
                    "fetched_count": 2,
                    "new_count": 2,
                    "updated_count": 0,
                    "last_branch": "dom",
                    "last_branch_label": "结果页DOM",
                    "branch_counts": {"next_data": 1, "dom": 1},
                    "debug_snapshot_path": "debug/lagou/p2.json",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()