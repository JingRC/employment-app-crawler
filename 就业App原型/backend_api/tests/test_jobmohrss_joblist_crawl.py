from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jobmohrss_joblist_crawl as jobmohrss  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class JobMohrssJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = jobmohrss.normalize_source_options(
            {
                "detail_mode": "detail_html",
                "request_timeout_seconds": "99",
                "sleep_seconds": "-1",
                "search_type": "bad-value",
            }
        )

        self.assertEqual(result["detail_mode"], "detail_html")
        self.assertEqual(result["request_timeout_seconds"], 60.0)
        self.assertEqual(result["sleep_seconds"], 0.0)
        self.assertEqual(result["search_type"], "2")

    def test_parse_job_list_page_extracts_hidden_json(self) -> None:
        html = """
        <html><body>
          <input id="findjoblist" name="findjoblist" value="[{&#34;acb200&#34;:79106904,&#34;aca112&#34;:&#34;普工&#34;,&#34;aab302&#34;:&#34;仙桃市&#34;,&#34;acb241&#34;:&#34;5000&#34;,&#34;acb242&#34;:&#34;7000&#34;}]" />
          <input name="pageNo" value="1" />
          <input name="totalpages" value="15364" />
          <input name="totalcount" value="307274" />
        </body></html>
        """

        result = jobmohrss.parse_job_list_page(html)

        self.assertEqual(result["page_no"], 1)
        self.assertEqual(result["total_pages"], 15364)
        self.assertEqual(result["total_count"], 307274)
        self.assertEqual(result["items"][0]["aca112"], "普工")

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <h1>普工</h1>
          <div>招聘单位： 百合医疗科技（武汉）有限公司 学历要求： 小学 提供住宿： 面议 发布机构： 仙桃市公共就业服务中心 工作性质： 全职 工作地点： 仙桃市干河办事处黄金大道西段118号 岗位描述 有经验者优先 单位简介 暂无介绍 联系方式 联 系 人 ： 吴女士 联 系 电 话： 19072320643 邮 箱： 623932979@qq.com.cn</div>
          <a href="/cjobs/jobinfolist/cb21/showdw?id=36842309">单位详情</a>
        </body></html>
        """

        result = jobmohrss.parse_detail_html(html)

        self.assertEqual(result["company_name"], "百合医疗科技（武汉）有限公司")
        self.assertEqual(result["degree_text"], "小学")
        self.assertEqual(result["job_type"], "全职")
        self.assertEqual(result["address_text"], "仙桃市干河办事处黄金大道西段118号")
        self.assertEqual(result["contact_person"], "吴女士")
        self.assertIn("showdw?id=36842309", result["company_detail_url"])

    def test_run_incremental_update_tracks_fallback_locations(self) -> None:
        fake_job = {
            "source_job_id": "jobmohrss-1",
            "title": "Java开发工程师",
            "company_name": "测试公司",
            "city_name": "北京",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            city_name = str(kwargs.get("city_name") or "")
            if city_name == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 0, "upstream_page_size": 20}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 3, "total_pages": 1, "upstream_page_size": 20}

        with patch.object(jobmohrss, "ensure_db"), patch.object(jobmohrss, "build_session", return_value=DummySession()), patch.object(
            jobmohrss, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(jobmohrss, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = jobmohrss.run_incremental_update(
                queries=["Java"],
                cities=["北京", "火星"],
                max_pages=1,
                page_size=10,
            )

        self.assertEqual(result["resolved_city_codes"], {})
        self.assertEqual(result["fallback_to_national_locations"], ["北京", "火星"])
        self.assertEqual(result["empty_result_locations"], ["火星"])
        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 0, "fallback_targets": 2, "empty_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["fallback_national", "empty"])


if __name__ == "__main__":
    unittest.main()