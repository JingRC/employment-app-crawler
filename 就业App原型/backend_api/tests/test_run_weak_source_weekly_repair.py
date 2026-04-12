from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import run_weak_source_weekly_repair as weekly_repair  # noqa: E402


class RunWeakSourceWeeklyRepairTests(unittest.TestCase):
    def test_resolve_sources_defaults_when_unset(self) -> None:
        self.assertEqual(weekly_repair.resolve_sources(None), weekly_repair.DEFAULT_SOURCE_CODES)
        self.assertEqual(weekly_repair.DEFAULT_SOURCE_CODES, ["qdhr", "qingdao_rc", "rcsd_talents", "sdgxbys"])

    def test_qingdao_rc_preset_uses_targeted_district_groups(self) -> None:
        preset = weekly_repair.WEEKLY_REPAIR_PRESETS["qingdao_rc"]

        self.assertEqual(preset["module_name"], "qingdao_rc_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(preset["max_pages"], 3)
        self.assertEqual([item["label"] for item in preset["task_groups"]], ["pm-project-core", "support-delivery-core"])
        self.assertEqual(preset["task_groups"][0]["queries"], ["产品经理", "项目经理"])
        self.assertEqual(preset["task_groups"][1]["cities"], ["崂山区", "市北区", "西海岸新区", "李沧区", "即墨区"])

    def test_validate_startup_writes_summary_without_running_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "weak_source_weekly_repair_last_result.json"
            with patch.object(weekly_repair, "SUMMARY_PATH", summary_path), patch.object(weekly_repair, "init_database"), patch.object(
                weekly_repair,
                "load_runner",
                side_effect=AssertionError("validate_startup should not load runners"),
            ), patch.object(
                weekly_repair,
                "warm_job_market_analytics_cache",
                return_value={"items": [{"status": "success"}], "success_count": 1, "failed_count": 0},
            ):
                result = weekly_repair.run_weekly_repair_sync(validate_startup=True)

            self.assertTrue(summary_path.exists())
            written = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertTrue(result["validate_startup"])
        self.assertEqual(result["results"], [])
        self.assertEqual(written["analytics_warmup"]["success_count"], 1)

    def test_run_weekly_repair_merges_grouped_source_results(self) -> None:
        fake_results = [
            {
                "source_code": "qingdao_rc",
                "total_fetched": 4,
                "new_to_db": 2,
                "updated_in_db": 1,
                "resolved_region_codes": {"崂山区": "370212"},
                "empty_result_locations": [],
                "unsupported_locations": [],
                "request_trace": [{"location_name": "崂山区", "status": "resolved"}],
                "request_summary": {"total_targets": 1, "resolved_targets": 1, "unsupported_targets": 0, "empty_targets": 0},
            },
            {
                "source_code": "qingdao_rc",
                "total_fetched": 0,
                "new_to_db": 0,
                "updated_in_db": 0,
                "resolved_region_codes": {"市北区": "370203"},
                "empty_result_locations": ["市北区"],
                "unsupported_locations": [],
                "request_trace": [{"location_name": "市北区", "status": "empty"}],
                "request_summary": {"total_targets": 1, "resolved_targets": 1, "unsupported_targets": 0, "empty_targets": 1},
            },
        ]

        class FakeRunner:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, **kwargs):
                result = fake_results[self.calls]
                self.calls += 1
                return result

        fake_runner = FakeRunner()
        fake_preset = {
            "module_name": "qingdao_rc_joblist_crawl",
            "runner_name": "run_incremental_update",
            "max_pages": 3,
            "source_options": {"detail_mode": "list_only"},
            "task_groups": [
                {"label": "g1", "queries": ["产品经理"], "cities": ["崂山区"]},
                {"label": "g2", "queries": ["技术支持"], "cities": ["市北区"]},
            ],
            "note": "测试预设",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "weak_source_weekly_repair_last_result.json"
            with patch.object(weekly_repair, "SUMMARY_PATH", summary_path), patch.object(weekly_repair, "init_database"), patch.dict(
                weekly_repair.WEEKLY_REPAIR_PRESETS, {"qingdao_rc": fake_preset}, clear=False
            ), patch.object(
                weekly_repair,
                "load_runner",
                return_value=fake_runner,
            ), patch.object(
                weekly_repair,
                "warm_job_market_analytics_cache",
                return_value={"items": [], "success_count": 0, "failed_count": 0},
            ):
                result = weekly_repair.run_weekly_repair_sync(selected_sources=["qingdao_rc"])

        self.assertEqual(result["total_fetched"], 4)
        self.assertEqual(result["total_new"], 2)
        self.assertEqual(result["total_updated"], 1)
        self.assertEqual(result["results"][0]["details"]["resolved_region_codes"], {"崂山区": "370212", "市北区": "370203"})
        self.assertEqual(result["results"][0]["details"]["request_summary"], {"total_targets": 2, "resolved_targets": 2, "unsupported_targets": 0, "empty_targets": 1})
        self.assertEqual(result["results"][0]["details"]["sub_runs"][0]["run_label"], "g1")
        self.assertEqual(result["results"][0]["details"]["sub_runs"][1]["run_cities"], ["市北区"])

    def test_main_returns_failure_when_weekly_repair_fails(self) -> None:
        with patch.object(weekly_repair, "run_weekly_repair_sync", return_value={"results": [{"status": "failed"}]}) as runner:
            exit_code = weekly_repair.main([])

        runner.assert_called_once_with(selected_sources=None, validate_startup=False)
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()