from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import qdhr_joblist_crawl as qdhr  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class QdhrJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = qdhr.normalize_source_options(
            {
                "detail_mode": "bad-mode",
                "request_timeout_seconds": "99",
                "sleep_seconds": "-1",
            }
        )

        self.assertEqual(result["detail_mode"], "detail_html")
        self.assertEqual(result["request_timeout_seconds"], 60.0)
        self.assertEqual(result["sleep_seconds"], 0.0)

    def test_parse_list_page_extracts_items_and_page_count(self) -> None:
        html = """
        <html><body>
          <div class="J_jobsList yli" data-jid="24109">
            <div class="td2"><div class="td-j-name"><a href="/jobs/24109.html">崂山区 | Java实习生</a></div></div>
            <div class="td3"><a href="/company/24038.html">数金公共服务（青岛）有限公司</a></div>
            <div class="td4">5千-6千/月</div>
            <div class="td5">2026-03-26</div>
            <div class="detail"><div class="txt">学历：本科<span>|</span>经验：无经验<span>|</span>职位性质：全职<span>|</span>人数：5人<span>|</span>地点：山东/青岛/崂山区</div></div>
          </div>
          <a href="/jobs/jobs_list/page/14.html">最后一页</a>
        </body></html>
        """

        result = qdhr.parse_list_page(html, 2)

        self.assertEqual(result["total_pages"], 14)
        self.assertEqual(result["items"][0]["title"], "Java实习生")
        self.assertEqual(result["items"][0]["company_name"], "数金公共服务（青岛）有限公司")

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><head><title>AI创意产品视频生成师-青岛云小华数字科技有限公司招聘-青帆引才</title></head><body>
        <div>2026-03-30 7次 AI创意产品视频生成师 4千5-7千/月 青岛云小华数字科技有限公司</div>
        <div>基本信息 工作性质 全职 招聘人数 8人 招聘部门 AIGC短视频运营部门 学历要求 本科 工作经验 1年以下 年龄要求 23岁--29岁 工作地点 山东省青岛市崂山区青岛国际创新园c座1801（山东/青岛/崂山区） 联系方式 联系人：赵女士</div>
        <div>职位描述 负责品牌宣传、产品推广、剧情短片、IP形象等各类短视频的脚本撰写、创意策划。 申请职位 收藏 分享 举报</div>
        <div>青岛云小华数字科技有限公司 性质 民营 行业 计算机软件/硬件 规模 20人以下 地区 山东/青岛/崂山区 扫描二维码即可在手机端精彩呈现</div>
        </body></html>
        """

        result = qdhr.parse_detail_html(html, "http://laoshan.qdhr.com/jobs/24114.html")

        self.assertEqual(result["title"], "AI创意产品视频生成师")
        self.assertEqual(result["company_name"], "青岛云小华数字科技有限公司")
        self.assertEqual(result["salary_text"], "4千5-7千/月")
        self.assertEqual(result["degree_text"], "本科")
        self.assertEqual(result["experience_text"], "1年以下")
        self.assertEqual(result["city_name"], "青岛")
        self.assertEqual(result["district_name"], "崂山区")
        self.assertIn("创意策划", result["description_text"])

    def test_run_incremental_update_tracks_empty_targets(self) -> None:
        fake_job = {
            "source_job_id": "/jobs/24109.html",
            "title": "Java实习生",
            "company_name": "数金公共服务（青岛）有限公司",
            "city_name": "青岛",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            city_name = str(kwargs.get("city_name") or "")
            if city_name == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 14, "upstream_page_size": 20}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 280, "total_pages": 14, "upstream_page_size": 20}

        with patch.object(qdhr, "ensure_db"), patch.object(qdhr, "build_session", return_value=DummySession()), patch.object(
            qdhr, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(qdhr, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = qdhr.run_incremental_update(
                queries=["Java"],
                cities=["青岛", "火星"],
                max_pages=1,
            )

        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 1, "empty_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "empty"])

    def test_collect_filtered_jobs_keeps_previous_pages_when_later_page_fails(self) -> None:
        page_one = {
            "items": [
                {
                    "title": "测试工程师",
                    "list_title": "崂山区 | 测试工程师",
                    "detail_url": "http://laoshan.qdhr.com/jobs/24109.html",
                    "company_name": "数金公共服务（青岛）有限公司",
                    "salary_text": "5千-6千/月",
                    "published_at": "2026-03-26",
                    "summary_text": "学历：本科 | 经验：无经验 | 地点：山东/青岛/崂山区",
                }
            ],
            "total_pages": 14,
            "total_count": 280,
            "page_size": 20,
        }

        with patch.object(qdhr, "fetch_list_page", side_effect=[page_one, RuntimeError("timeout")]), patch.object(
            qdhr, "fetch_text", return_value=""
        ), patch.object(
            qdhr, "parse_detail_html", return_value={}
        ):
            result = qdhr.collect_filtered_jobs(
                DummySession(),
                query="测试",
                city_name="青岛",
                max_pages=3,
                detail_mode="detail_html",
                timeout_seconds=30,
                sleep_seconds=0,
                should_stop_callback=None,
                progress_callback=None,
            )

        self.assertEqual(len(result["matched_jobs"]), 1)
        self.assertEqual(result["stop_reason"], "list_page_error:RuntimeError")


if __name__ == "__main__":
    unittest.main()