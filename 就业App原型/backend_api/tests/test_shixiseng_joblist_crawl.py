from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import shixiseng_joblist_crawl as shixiseng  # noqa: E402


class DummyPage:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def quit(self) -> None:
        return None


class ShixisengJoblistCrawlTests(unittest.TestCase):
    def test_infer_featured_company_metadata_classifies_state_owned_company(self) -> None:
        result = shixiseng.infer_featured_company_metadata(
            {
                "company_name": "国家电网",
                "industry": "电力/能源",
                "description": "央企招聘项目",
            },
            module_name="xiaozhao_hotcompany",
        )

        self.assertEqual(result["board_code"], "featured_soe")
        self.assertEqual(result["company_type"], "central_soe")
        self.assertEqual(result["group_name"], "电力能源央国企")

    def test_infer_featured_company_metadata_keeps_regular_company_in_famous_board(self) -> None:
        result = shixiseng.infer_featured_company_metadata(
            {
                "company_name": "阿里巴巴",
                "industry": "互联网/游戏/软件",
                "description": "校招名企项目",
            },
            module_name="xiaozhao_hotcompany",
        )

        self.assertEqual(result["board_code"], "featured_famous")
        self.assertEqual(result["company_type"], "famous_enterprise")
        self.assertEqual(result["group_name"], "xiaozhao_hotcompany")

    def test_normalize_source_options_parses_string_booleans(self) -> None:
        result = shixiseng.normalize_source_options(
            {
                "track": "campus",
                "detail_workers": "3",
                "detail_rate_per_second": "2.5",
                "include_campus_home_modules": "false",
                "campus_hotintern_city": "北京",
                "campus_hotcompany_industry": "互联网",
            }
        )

        self.assertEqual(result["track"], "campus")
        self.assertEqual(result["detail_workers"], 3)
        self.assertEqual(result["detail_rate_per_second"], 2.5)
        self.assertFalse(result["include_campus_home_modules"])
        self.assertEqual(result["campus_hotintern_city"], "北京")
        self.assertEqual(result["campus_hotcompany_industry"], "互联网")

    def test_run_incremental_update_returns_trace_and_summary(self) -> None:
        api_pages = [
            ([{"uuid": "job-1"}], 20, 5),
            ([{"uuid": "job-2"}], 20, 5),
        ]
        page_jobs = [
            [{"source_job_id": "job-1", "title": "职位-1", "company_name": "测试公司"}],
            [{"source_job_id": "job-2", "title": "职位-2", "company_name": "测试公司"}],
        ]

        with patch.object(shixiseng, "ensure_db"), patch.object(
            shixiseng, "ChromiumPage", DummyPage
        ), patch.object(
            shixiseng,
            "collect_campus_home_modules",
            return_value={"job_items": 3, "job_new": 1, "job_updated": 1, "company_items": 2},
        ), patch.object(
            shixiseng, "load_search_api_page_with_retry", side_effect=api_pages
        ), patch.object(
            shixiseng, "fetch_page_jobs_via_api", side_effect=page_jobs
        ), patch.object(
            shixiseng, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = shixiseng.run_incremental_update(
                queries=["Java"],
                cities=["北京"],
                max_pages=2,
                page_size=20,
                runtime_mode="requests_only",
                source_options={
                    "track": "campus",
                    "detail_workers": 4,
                    "detail_rate_per_second": 1.5,
                    "include_campus_home_modules": True,
                    "campus_hotintern_city": "推荐",
                    "campus_hotcompany_industry": "推荐",
                },
            )

        self.assertEqual(result["total_fetched"], 5)
        self.assertEqual(result["new_to_db"], 3)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["detail_mode"], "api")
        self.assertEqual(result["track"], "campus")
        self.assertEqual(
            result["shixiseng_summary"],
            {
                "trace_count": 1,
                "campus_home_jobs": 3,
                "campus_home_companies": 2,
                "detail_mode": "api",
                "track": "campus",
            },
        )
        self.assertEqual(
            result["shixiseng_trace"],
            [
                {
                    "query": "Java",
                    "location_name": "北京",
                    "status": "target_pages_reached",
                    "pages_completed": 2,
                    "total_items": 20,
                    "estimated_total_pages": 5,
                    "fetched_count": 2,
                    "new_count": 2,
                    "updated_count": 0,
                    "detail_mode": "api",
                    "track": "campus",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()