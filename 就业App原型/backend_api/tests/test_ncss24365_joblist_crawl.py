from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import requests


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import ncss24365_joblist_crawl as ncss24365  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class NCSS24365JoblistCrawlTests(unittest.TestCase):
    def test_resolve_city_code_supports_added_core_cities(self) -> None:
        self.assertEqual(ncss24365.resolve_city_code("石家庄"), "130100")
        self.assertEqual(ncss24365.resolve_city_code("太原"), "140100")
        self.assertEqual(ncss24365.resolve_city_code("呼和浩特"), "150100")
        self.assertEqual(ncss24365.resolve_city_code("南昌"), "360100")
        self.assertEqual(ncss24365.resolve_city_code("长春"), "220100")
        self.assertEqual(ncss24365.resolve_city_code("哈尔滨"), "230100")
        self.assertEqual(ncss24365.resolve_city_code("南宁"), "450100")
        self.assertEqual(ncss24365.resolve_city_code("海口"), "460100")
        self.assertEqual(ncss24365.resolve_city_code("贵阳"), "520100")
        self.assertEqual(ncss24365.resolve_city_code("昆明"), "530100")
        self.assertEqual(ncss24365.resolve_city_code("拉萨"), "540100")
        self.assertEqual(ncss24365.resolve_city_code("兰州"), "620100")
        self.assertEqual(ncss24365.resolve_city_code("西宁"), "630100")
        self.assertEqual(ncss24365.resolve_city_code("银川"), "640100")
        self.assertEqual(ncss24365.resolve_city_code("乌鲁木齐"), "650100")

    def test_normalize_source_options_parses_bounds(self) -> None:
        result = ncss24365.normalize_source_options(
            {
                "detail_mode": "detail_html",
                "request_timeout_seconds": "99",
                "sleep_seconds": "-1",
                "job_type": "intern",
                "sources_name": "fawzqa3wo3hy2x4uqe1b1bwy4met2wpb",
                "sources_type": "0",
                "allow_empty_query": "true",
            }
        )

        self.assertEqual(result["detail_mode"], "detail_html")
        self.assertEqual(result["request_timeout_seconds"], 60.0)
        self.assertEqual(result["sleep_seconds"], 0.0)
        self.assertEqual(result["job_type"], "03")
        self.assertEqual(result["sources_name"], "fawzqa3wo3hy2x4uqe1b1bwy4met2wpb")
        self.assertEqual(result["sources_type"], "0")
        self.assertTrue(result["allow_empty_query"])

    def test_normalize_queries_can_allow_empty_query(self) -> None:
        self.assertEqual(ncss24365.normalize_queries([""], allow_empty=True), [""])
        self.assertEqual(ncss24365.normalize_queries(None, allow_empty=True), [""])
        self.assertEqual(ncss24365.normalize_queries(["Java", ""], allow_empty=True), ["Java"])

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <li class="job-title basic-color" id="jobName">Java开发</li>
          <ul class="work"><li>Java开发</li><li>[全职]</li><li>——</li><li>青岛百杉软件科技有限公司</li></ul>
          <ul class="salary"><li><span>6k-6.5k</span></li><li>|</li><li><span>本科及以上</span></li></ul>
          <div class="major-bl"><div class="major">计算机相关</div><div class="source-rl"><span class="source-sp">山东轻工职业学院</span></div><div id="sourcesName">abc123</div></div>
          <ul class="address"><li><div class="site-tag">山东省青岛市</div></li></ul>
          <div class="jobdetail-box"><div class="mainContent">职位描述正文</div></div>
          <div class="con-right"><div class="company"><ul class="details">
            <li><span class="ico fl">所属行业</span><span class="show fr">计算机服务</span></li>
            <li><span class="ico fl">公司性质</span><span class="show fr">民营企业</span></li>
            <li><span class="ico fl">公司规模</span><span class="show fr">100-499人</span></li>
            <li><span class="ico fl">所在地址</span><span class="show fr">山东省青岛市李沧区</span></li>
          </ul></div></div>
          <span id="realCorpName">青岛百杉软件科技有限公司</span>
        </body></html>
        """

        result = ncss24365.parse_detail_html(html)

        self.assertEqual(result["title"], "Java开发")
        self.assertEqual(result["job_type"], "全职")
        self.assertEqual(result["salary_text"], "6k-6.5k")
        self.assertEqual(result["degree_text"], "本科及以上")
        self.assertEqual(result["address_text"], "山东省青岛市")
        self.assertEqual(result["source_name_ch"], "山东轻工职业学院")
        self.assertEqual(result["brand_stage"], "民营企业")
        self.assertEqual(result["brand_scale"], "100-499人")

    def test_run_incremental_update_tracks_resolved_and_fallback_locations(self) -> None:
        fake_job = {
            "source_job_id": "ncss-1",
            "title": "Java开发工程师",
            "company_name": "测试公司",
            "city_name": "北京",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            city_name = str(kwargs.get("city_name") or "")
            if city_name == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 0}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 12, "total_pages": 3}

        with patch.object(ncss24365, "ensure_db"), patch.object(ncss24365, "build_session", return_value=DummySession()), patch.object(
            ncss24365, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(ncss24365, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = ncss24365.run_incremental_update(
                queries=["Java"],
                cities=["北京", "火星"],
                max_pages=1,
                page_size=10,
            )

        self.assertEqual(result["resolved_city_codes"], {"北京": "110100"})
        self.assertEqual(result["fallback_to_national_locations"], ["火星"])
        self.assertEqual(result["empty_result_locations"], ["火星"])
        self.assertEqual(
            result["request_summary"],
            {"total_targets": 2, "resolved_targets": 1, "fallback_targets": 1, "empty_targets": 1, "login_wall_targets": 0},
        )
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "empty"])

    def test_run_incremental_update_supports_intern_all_sources_mode(self) -> None:
        captured_kwargs: list[dict[str, object]] = []

        def fake_collect_filtered_jobs(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 0}

        with patch.object(ncss24365, "ensure_db"), patch.object(ncss24365, "build_session", return_value=DummySession()), patch.object(
            ncss24365, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ):
            result = ncss24365.run_incremental_update(
                queries=[""],
                cities=["全国"],
                max_pages=1,
                page_size=10,
                source_options={
                    "job_type": "intern",
                    "sources_name": "",
                    "sources_type": "",
                    "allow_empty_query": True,
                },
            )

        self.assertEqual(result["job_type"], "03")
        self.assertEqual(result["sources_name"], "")
        self.assertEqual(result["sources_type"], "")
        self.assertEqual(result["queries"], 1)
        self.assertEqual(captured_kwargs[0]["query"], "")
        self.assertEqual(captured_kwargs[0]["job_type"], "03")
        self.assertEqual(captured_kwargs[0]["sources_name"], "")
        self.assertEqual(captured_kwargs[0]["sources_type"], "")

    def test_collect_filtered_jobs_stops_gracefully_on_login_wall_after_first_page(self) -> None:
        first_page = {
            "items": [
                {
                    "jobId": "job-1",
                    "jobName": "实习生",
                    "recName": "测试公司",
                    "areaCodeName": "北京",
                    "degreeName": "本科及以上",
                    "recScale": "100-499人",
                    "recProperty": "民营企业",
                    "sourcesName": "fawzqa3wo3hy2x4uqe1b1bwy4met2wpb",
                    "sourcesNameCh": "智联招聘",
                    "lowMonthPay": 2,
                    "highMonthPay": 4,
                }
            ],
            "page_no": 1,
            "page_size": 20,
            "total_pages": 10,
            "total_count": 200,
        }

        with patch.object(ncss24365, "fetch_job_list_page", side_effect=[first_page, RuntimeError("请登录后查看")]):
            result = ncss24365.collect_filtered_jobs(
                DummySession(),
                query="",
                city_name="全国",
                area_code=None,
                max_pages=10,
                page_size=20,
                detail_mode="list_only",
                timeout_seconds=15.0,
                sleep_seconds=0.0,
                job_type="03",
                sources_name="",
                sources_type="",
                should_stop_callback=None,
                progress_callback=None,
            )

        self.assertEqual(len(result["matched_jobs"]), 1)
        self.assertEqual(result["api_pages"], 10)
        self.assertEqual(result["stop_reason"], "login_wall")


if __name__ == "__main__":
    unittest.main()