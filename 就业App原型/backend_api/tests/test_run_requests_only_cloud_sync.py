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

import run_requests_only_cloud_sync as cloud_sync  # noqa: E402


class RunRequestsOnlyCloudSyncTests(unittest.TestCase):
    def test_resolve_sources_defaults_when_unset(self) -> None:
        self.assertEqual(cloud_sync.resolve_sources(None), cloud_sync.DEFAULT_SOURCE_CODES)
        self.assertIn("qlrc", cloud_sync.DEFAULT_SOURCE_CODES)
        self.assertIn("healthr", cloud_sync.DEFAULT_SOURCE_CODES)
        self.assertIn("healthr_doctor", cloud_sync.DEFAULT_SOURCE_CODES)
        self.assertIn("buildhr", cloud_sync.DEFAULT_SOURCE_CODES)
        self.assertIn("chenhr", cloud_sync.DEFAULT_SOURCE_CODES)

    def test_qlrc_preset_uses_targeted_task_groups(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["qlrc"]

        self.assertEqual(preset["module_name"], "qlrc_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(preset["max_pages"], 4)
        self.assertEqual([item["label"] for item in preset["task_groups"]], ["shandong-general", "jinan-weifang-core", "qingdao-support"])
        self.assertEqual(preset["task_groups"][0]["queries"], ["工程师", "销售"])
        self.assertEqual(preset["task_groups"][1]["cities"], ["济南", "潍坊"])
        self.assertEqual(preset["task_groups"][2]["queries"], ["工程师", "技术员"])

    def test_ncss24365_preset_is_grouped_by_region(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["ncss24365"]

        self.assertEqual(preset["module_name"], "ncss24365_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(preset["max_pages"], 1)
        self.assertEqual(len(preset["task_groups"]), len(cloud_sync.REQUESTS_ONLY_REGION_GROUPS))
        self.assertEqual(preset["task_groups"][0]["label"], "north-core-campus")
        self.assertEqual(preset["task_groups"][0]["cities"], ["北京", "天津", "石家庄", "太原", "呼和浩特"])
        self.assertEqual(preset["task_groups"][0]["queries"], cloud_sync.NCSS24365_OFFICIAL_QUERIES)

    def test_jobmohrss_preset_is_grouped_by_region(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["jobmohrss"]

        self.assertEqual(preset["module_name"], "jobmohrss_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(preset["max_pages"], 1)
        self.assertEqual(len(preset["task_groups"]), len(cloud_sync.REQUESTS_ONLY_REGION_GROUPS))
        self.assertEqual(preset["task_groups"][-1]["label"], "northwest-core-public")
        self.assertEqual(preset["task_groups"][-1]["cities"], ["西安", "兰州", "西宁", "银川", "乌鲁木齐"])
        self.assertEqual(preset["task_groups"][-1]["queries"], cloud_sync.JOBMOHRSS_OFFICIAL_QUERIES)

    def test_healthr_preset_is_registered(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["healthr"]

        self.assertEqual(preset["module_name"], "healthr_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(preset["max_pages"], 2)
        self.assertEqual(len(preset["task_groups"]), 3)

    def test_healthr_doctor_preset_is_registered(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["healthr_doctor"]

        self.assertEqual(preset["module_name"], "healthr_doctor_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(len(preset["task_groups"]), 2)
        self.assertEqual(preset["task_groups"][0]["label"], "regional-doctor")
        self.assertEqual(preset["task_groups"][1]["queries"], ["医生", "护士", "医师", "内科"])

    def test_build_preset_runs_supports_task_groups(self) -> None:
        runs = cloud_sync.build_preset_runs("healthr", cloud_sync.REQUESTS_ONLY_PRESETS["healthr"])

        self.assertEqual([run["label"] for run in runs], ["regional-market", "jinan-market", "national-vertical"])
        self.assertEqual(runs[0]["queries"], ["销售", "推广"])
        self.assertEqual(runs[0]["cities"], ["青岛"])
        self.assertEqual(runs[2]["queries"], ["销售", "工程师", "渠道"])
        self.assertEqual(runs[2]["cities"], ["全国"])

    def test_buildhr_preset_is_registered(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["buildhr"]

        self.assertEqual(preset["module_name"], "buildhr_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(len(preset["task_groups"]), 2)
        self.assertEqual(preset["task_groups"][0]["queries"], ["项目经理"])
        self.assertEqual(preset["task_groups"][1]["label"], "national-design-cost")
        self.assertEqual(preset["task_groups"][1]["queries"], ["建筑师", "预算员", "造价工程师", "BIM工程师"])

    def test_chenhr_preset_is_registered(self) -> None:
        preset = cloud_sync.REQUESTS_ONLY_PRESETS["chenhr"]

        self.assertEqual(preset["module_name"], "chenhr_joblist_crawl")
        self.assertEqual(preset["runner_name"], "run_incremental_update")
        self.assertEqual(len(preset["task_groups"]), 3)
        self.assertEqual(preset["task_groups"][0]["label"], "regional-safety")
        self.assertEqual(preset["task_groups"][0]["queries"], ["安全工程师"])
        self.assertEqual(preset["task_groups"][1]["label"], "jinan-safety")
        self.assertEqual(preset["task_groups"][1]["queries"], ["安全工程师", "设备工程师"])
        self.assertEqual(preset["task_groups"][2]["label"], "national-chemcore")
        self.assertEqual(
            preset["task_groups"][2]["queries"],
            ["研发工程师", "工艺工程师", "设备工程师", "安全工程师", "生产经理", "化工"],
        )

    def test_run_cloud_sync_merges_grouped_source_results(self) -> None:
        fake_results = [
            {
                "source_code": "healthr",
                "total_fetched": 3,
                "new_to_db": 2,
                "updated": 0,
                "resolved_city_codes": {"青岛": "2102"},
                "empty_result_locations": [],
                "fallback_to_national_locations": [],
                "request_trace": [{"location_name": "青岛", "fetched_count": 3, "status": "resolved"}],
                "request_summary": {"total_targets": 2, "resolved_targets": 2, "fallback_targets": 0, "empty_targets": 0},
            },
            {
                "source_code": "healthr",
                "total_fetched": 5,
                "new_to_db": 1,
                "updated": 0,
                "resolved_city_codes": {"济南": "2101"},
                "empty_result_locations": ["全国"],
                "fallback_to_national_locations": [],
                "request_trace": [{"location_name": "全国", "fetched_count": 5, "status": "empty"}],
                "request_summary": {"total_targets": 1, "resolved_targets": 0, "fallback_targets": 0, "empty_targets": 1},
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
            "module_name": "healthr_joblist_crawl",
            "runner_name": "run_incremental_update",
            "max_pages": 2,
            "source_options": {"detail_mode": "detail_html"},
            "task_groups": [
                {"label": "g1", "queries": ["销售"], "cities": ["青岛"]},
                {"label": "g2", "queries": ["工程师"], "cities": ["全国"]},
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "cloud_sync_last_result.json"
            with patch.object(cloud_sync, "SUMMARY_PATH", summary_path), patch.object(cloud_sync, "init_database"), patch.dict(
                cloud_sync.REQUESTS_ONLY_PRESETS, {"healthr": fake_preset}, clear=False
            ), patch.object(cloud_sync, "load_runner", return_value=fake_runner):
                result = cloud_sync.run_cloud_sync(selected_sources=["healthr"])

        self.assertEqual(result["total_fetched"], 8)
        self.assertEqual(result["total_new"], 3)
        self.assertEqual(result["results"][0]["details"]["resolved_city_codes"], {"青岛": "2102", "济南": "2101"})
        self.assertEqual(result["results"][0]["details"]["request_summary"], {"total_targets": 3, "resolved_targets": 2, "fallback_targets": 0, "empty_targets": 1})
        self.assertEqual(len(result["results"][0]["details"]["sub_runs"]), 2)
        self.assertEqual(result["results"][0]["details"]["sub_runs"][0]["run_label"], "g1")
        self.assertEqual(result["results"][0]["details"]["sub_runs"][0]["run_queries"], ["销售"])
        self.assertEqual(result["results"][0]["details"]["sub_runs"][1]["run_cities"], ["全国"])

    def test_resolve_sources_supports_explicit_none_marker(self) -> None:
        self.assertEqual(cloud_sync.resolve_sources("none"), [])
        self.assertEqual(cloud_sync.resolve_sources("off"), [])

    def test_resolve_sources_rejects_unknown_items(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知的 CLOUD_SYNC_SOURCES 来源"):
            cloud_sync.resolve_sources("qdhr,unknown-source")

    def test_validate_startup_skips_runner_loading_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "cloud_sync_last_result.json"
            with patch.object(cloud_sync, "SUMMARY_PATH", summary_path), patch.object(cloud_sync, "init_database"), patch.object(
                cloud_sync, "load_runner", side_effect=AssertionError("validate_startup should not load runners")
            ):
                result = cloud_sync.run_cloud_sync(validate_startup=True)
            self.assertTrue(summary_path.exists())
            written_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(result["selected_sources"], [])
        self.assertTrue(result["validate_startup"])
        self.assertEqual(result["results"], [])
        self.assertTrue(written_summary["validate_startup"])
        self.assertEqual(written_summary["selected_sources"], [])

    def test_explicit_empty_sources_skip_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "cloud_sync_last_result.json"
            with patch.object(cloud_sync, "SUMMARY_PATH", summary_path), patch.object(cloud_sync, "init_database"), patch.object(
                cloud_sync, "load_runner", side_effect=AssertionError("empty sources should not load runners")
            ):
                result = cloud_sync.run_cloud_sync(selected_sources=[])

        self.assertFalse(result["validate_startup"])
        self.assertEqual(result["selected_sources"], [])
        self.assertEqual(result["results"], [])


if __name__ == "__main__":
    unittest.main()