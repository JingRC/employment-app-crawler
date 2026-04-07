from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import rcsd_talents_joblist_crawl as rcsd_talents  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class RcsdTalentsJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = rcsd_talents.normalize_source_options(
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
          <div class="list">
            <el-row class="item">
              <el-col class="title"><a href="./202405/t20240515_16714979.html">日照高新发展集团有限公司高层次专业人才招聘简章</a></el-col>
              <el-col class="date">2024-05-15</el-col>
            </el-row>
          </div>
          <script>var pageNum = 0; var pageCount = 18</script>
        </body></html>
        """

        result = rcsd_talents.parse_list_page(html, 1)

        self.assertEqual(result["total_pages"], 18)
        self.assertEqual(result["items"][0]["published_at"], "2024-05-15")
        self.assertIn("t20240515_16714979.html", result["items"][0]["detail_url"])

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <div class="article">
            <div class="title">2024年济南城市发展集团春季校园招聘公告</div>
            <div class="info">
              <span>信息来源：济南城市发展集团</span>
              <span>发布时间：2024-03-27</span>
            </div>
            <div class="content">济南城市发展集团现面向社会公开招聘项目经理、技术支持等岗位。</div>
          </div>
        </body></html>
        """

        result = rcsd_talents.parse_detail_html(html, "https://web.rcsd.cn/rcsd20/demand/talents/202403/t20240327_15966441.html")

        self.assertEqual(result["title"], "2024年济南城市发展集团春季校园招聘公告")
        self.assertEqual(result["source_name"], "济南城市发展集团")
        self.assertEqual(result["company_name"], "济南城市发展集团")
        self.assertEqual(result["city_name"], "济南")
        self.assertIn("项目经理", result["content_text"])

    def test_normalize_city_name_returns_empty_for_unmatched_notice_title(self) -> None:
        result = rcsd_talents.normalize_city_name("山东大学2023年管理岗位招聘公告")

        self.assertEqual(result, "")

    def test_save_to_db_updates_metadata_when_hash_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_db_path = Path(temp_dir) / "jobs.db"
            wrong_job = {
                "source_job_id": "/rcsd20/demand/talents/202405/t20240515_16714979.html",
                "title": "山东大学2023年管理岗位招聘公告",
                "company_name": "山东大学",
                "city_name": "山东大学2023年管理岗位招聘公告",
                "district_name": "",
                "salary_text": "",
                "degree_text": "",
                "experience_text": "",
                "brand_scale": "",
                "brand_stage": "引才公告",
                "job_type": "公告",
                "source_url": "https://web.rcsd.cn/rcsd20/demand/talents/202405/t20240515_16714979.html",
                "official_apply_url": "https://web.rcsd.cn/rcsd20/demand/talents/202405/t20240515_16714979.html",
                "description_text": "管理岗位公开招聘",
                "publisher": "山东大学",
            }
            fixed_job = dict(wrong_job)
            fixed_job["city_name"] = "山东"

            with patch.object(rcsd_talents, "DB_PATH", temp_db_path), patch.object(rcsd_talents, "DB_DIR", Path(temp_dir)):
                rcsd_talents.ensure_db()
                first_stats = rcsd_talents.save_to_db([wrong_job])
                second_stats = rcsd_talents.save_to_db([fixed_job])

                self.assertEqual(first_stats["new"], 1)
                self.assertEqual(second_stats["updated"], 1)

                conn = sqlite3.connect(temp_db_path)
                row = conn.execute("select city_name from jobs where source_code='rcsd_talents'").fetchone()
                conn.close()

                self.assertIsNotNone(row)
                self.assertEqual(row[0], "山东")

    def test_run_incremental_update_tracks_empty_targets(self) -> None:
        fake_job = {
            "source_job_id": "/rcsd20/demand/talents/202405/t20240515_16714979.html",
            "title": "日照高新发展集团有限公司高层次专业人才招聘简章",
            "company_name": "日照高新发展集团有限公司",
            "city_name": "日照",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            query = str(kwargs.get("query") or "")
            if query == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 18, "upstream_page_size": 10}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 180, "total_pages": 18, "upstream_page_size": 10}

        with patch.object(rcsd_talents, "ensure_db"), patch.object(rcsd_talents, "build_session", return_value=DummySession()), patch.object(
            rcsd_talents, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(rcsd_talents, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = rcsd_talents.run_incremental_update(
                queries=["招聘", "火星"],
                cities=["山东"],
                max_pages=1,
            )

        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 1, "empty_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "empty"])


if __name__ == "__main__":
    unittest.main()