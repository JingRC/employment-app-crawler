from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import guopin_joblist_crawl as guopin  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class GuopinJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_supports_district_only_flag(self) -> None:
        result = guopin.normalize_source_options(
            {
                "district_targets": "北京-朝阳区, 北京-海淀区",
                "use_district_targets_only": "true",
                "api_page_size": "30",
            }
        )

        self.assertEqual(result["district_targets"], ["北京-朝阳区", "北京-海淀区"])
        self.assertTrue(result["use_district_targets_only"])
        self.assertEqual(result["api_page_size"], 30)

    def test_run_incremental_update_uses_only_district_targets_when_flag_enabled(self) -> None:
        collect_calls: list[str] = []

        def fake_collect_filtered_jobs(*args, **kwargs):
            collect_calls.append(str(kwargs.get("city_name") or ""))
            return {"pages": [], "matched_jobs": [], "api_pages": 0, "total": 0}

        with patch.object(guopin, "ensure_db"), patch.object(guopin, "build_session", return_value=DummySession()), patch.object(
            guopin, "fetch_district_tree", return_value=[]
        ), patch.object(guopin, "resolve_city_district_code", return_value="mock-code"), patch.object(
            guopin, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ):
            result = guopin.run_incremental_update(
                queries=["Java"],
                cities=["青岛", "北京"],
                max_pages=1,
                page_size=10,
                source_options={
                    "district_targets": ["北京-朝阳区", "北京-海淀区"],
                    "use_district_targets_only": True,
                },
            )

        self.assertEqual(collect_calls, ["北京-朝阳区", "北京-海淀区"])
        self.assertEqual(result["cities"], 2)
        self.assertTrue(result["use_district_targets_only"])

    def test_run_incremental_update_reports_unresolved_district_targets(self) -> None:
        with patch.object(guopin, "ensure_db"), patch.object(guopin, "build_session", return_value=DummySession()), patch.object(
            guopin, "fetch_district_tree", return_value=[]
        ), patch.object(guopin, "resolve_city_district_code", return_value=None), patch.object(
            guopin, "collect_filtered_jobs"
        ) as collect_mock:
            result = guopin.run_incremental_update(
                queries=["Java"],
                cities=[],
                max_pages=1,
                page_size=10,
                source_options={
                    "district_targets": ["北京-不存在区"],
                    "use_district_targets_only": True,
                },
            )

        collect_mock.assert_not_called()
        self.assertEqual(result["unresolved_district_targets"], ["北京-不存在区"])
        self.assertEqual(result["unresolved_locations"], ["北京-不存在区"])
        self.assertEqual(result["request_summary"]["unresolved_targets"], 1)
        self.assertEqual(result["request_trace"][0]["status"], "unresolved")

    def test_run_incremental_update_returns_request_trace_for_successful_target(self) -> None:
        fake_job = {
            "source_job_id": "gp-1",
            "title": "Java开发工程师",
            "company_name": "测试公司",
            "city_name": "北京",
        }

        with patch.object(guopin, "ensure_db"), patch.object(guopin, "build_session", return_value=DummySession()), patch.object(
            guopin, "fetch_district_tree", return_value=[]
        ), patch.object(guopin, "resolve_city_district_code", return_value="000000.110000"), patch.object(
            guopin,
            "collect_filtered_jobs",
            return_value={"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total": 12},
        ), patch.object(guopin, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = guopin.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=1,
                page_size=10,
                source_options={"district_targets": []},
            )

        self.assertEqual(result["request_summary"]["total_targets"], 1)
        self.assertEqual(result["request_summary"]["resolved_targets"], 1)
        self.assertEqual(result["empty_result_locations"], [])
        self.assertEqual(
            result["request_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "district_code": "000000.110000",
                    "is_district_target": False,
                    "status": "resolved",
                    "target_pages": 1,
                    "api_page_size": 50,
                    "logical_pages": 1,
                    "api_pages_used": 1,
                    "upstream_total": 12,
                    "fetched_count": 1,
                    "new_count": 1,
                    "updated_count": 0,
                }
            ],
        )

    def test_run_incremental_update_tracks_fallback_and_empty_locations(self) -> None:
        collect_calls: list[str] = []

        def fake_collect_filtered_jobs(*args, **kwargs):
            collect_calls.append(str(kwargs.get("city_name") or ""))
            return {"pages": [], "matched_jobs": [], "api_pages": 1, "total": 0}

        def fake_resolve_city_district_code(name, _district_tree):
            return "000000.110000.110100.110108" if name == "北京-海淀区" else None

        with patch.object(guopin, "ensure_db"), patch.object(guopin, "build_session", return_value=DummySession()), patch.object(
            guopin, "fetch_district_tree", return_value=[]
        ), patch.object(guopin, "resolve_city_district_code", side_effect=fake_resolve_city_district_code), patch.object(
            guopin, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ):
            result = guopin.run_incremental_update(
                queries=["Java"],
                cities=["火星"],
                max_pages=1,
                page_size=10,
                source_options={
                    "district_targets": ["北京-海淀区", "北京-不存在区"],
                    "use_district_targets_only": False,
                },
            )

        self.assertEqual(collect_calls, ["火星", "北京-海淀区"])
        self.assertEqual(result["fallback_to_national_locations"], ["火星"])
        self.assertEqual(result["empty_result_locations"], ["火星", "北京-海淀区"])
        self.assertEqual(result["request_summary"], {"total_targets": 3, "resolved_targets": 0, "fallback_targets": 1, "empty_targets": 2, "unresolved_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["empty", "empty", "unresolved"])


if __name__ == "__main__":
    unittest.main()