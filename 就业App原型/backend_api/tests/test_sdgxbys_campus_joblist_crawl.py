from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sdgxbys_campus_joblist_crawl as sdgxbys_campus  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class SdgxbysCampusJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = sdgxbys_campus.normalize_source_options(
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
          <ul>
            <li class="w-500"><a href="/campus/view/id/750259">山东省青岛心智心理医院2026年招聘公告</a></li>
            <li class="w-250">滨州医学院</li>
            <li class="w-120">2026-04-03</li>
          </ul>
          <a href="/campus/index?page=5">5</a>
          <a href="/campus/index?page=9780">末页</a>
        </body></html>
        """

        result = sdgxbys_campus.parse_list_page(html, 2)

        self.assertEqual(result["total_pages"], 9780)
        self.assertEqual(result["items"][0]["title"], "山东省青岛心智心理医院2026年招聘公告")
        self.assertEqual(result["items"][0]["school_name"], "滨州医学院")
        self.assertEqual(result["items"][0]["published_at"], "2026-04-03")

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <div class="details-title clearfix">
            <div class="title-message">
              <h5>山东省青岛心智心理医院2026年招聘公告</h5>
              <span class="expired_time">过期时间：2026-06-03</span>
            </div>
            <div class="operation"><ul><li>发布时间：2026-04-03 17:09</li><li>浏览次数：29</li></ul></div>
          </div>
          <div class="aContent">这里是公告正文，含青岛岗位需求。</div>
        </body></html>
        """

        result = sdgxbys_campus.parse_detail_html(html, "https://bzmc.sdbys.com/campus/view/id/750259", "滨州医学院")

        self.assertEqual(result["title"], "山东省青岛心智心理医院2026年招聘公告")
        self.assertEqual(result["published_at"], "2026-04-03 17:09")
        self.assertEqual(result["expired_at"], "2026-06-03")
        self.assertEqual(result["company_name"], "山东省青岛心智心理医院")
        self.assertEqual(result["city_name"], "青岛")
        self.assertIn("公告正文", result["content_text"])

    def test_run_incremental_update_tracks_empty_targets(self) -> None:
        fake_job = {
            "source_job_id": "job.sdgxbys.cn/campus/view/id/750259",
            "title": "山东省青岛心智心理医院2026年招聘公告",
            "company_name": "山东省青岛心智心理医院",
            "city_name": "青岛",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            query = str(kwargs.get("query") or "")
            if query == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 100, "upstream_page_size": 20}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 100, "total_pages": 100, "upstream_page_size": 20}

        with patch.object(sdgxbys_campus, "ensure_db"), patch.object(sdgxbys_campus, "build_session", return_value=DummySession()), patch.object(
            sdgxbys_campus, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(sdgxbys_campus, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = sdgxbys_campus.run_incremental_update(
                queries=["招聘", "火星"],
                cities=["青岛"],
                max_pages=1,
            )

        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 1, "empty_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "empty"])


if __name__ == "__main__":
    unittest.main()