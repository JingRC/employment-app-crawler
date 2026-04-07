from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import qingdao_rc_joblist_crawl as qingdao_rc  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class QingdaoRcJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = qingdao_rc.normalize_source_options(
            {
                "detail_mode": "bad-mode",
                "request_timeout_seconds": "99",
                "sleep_seconds": "-1",
            }
        )

        self.assertEqual(result["detail_mode"], "detail_html")
        self.assertEqual(result["request_timeout_seconds"], 60.0)
        self.assertEqual(result["sleep_seconds"], 0.0)

    def test_fetch_json_page_style_payload_is_understood(self) -> None:
        array_payload = [
            {"gwid": "abc", "gwname": "Java后端工程师", "gab003": "测试公司", "ys": 3, "sign": "2"},
            {"gwid": "def", "gwname": "测试工程师", "gab003": "测试公司", "ys": 0, "sign": "2"},
        ]
        dict_payload = {
            "data": [{"gwid": "ghi", "gwname": "前端开发", "gab003": "测试公司", "ys": 0, "sign": "2"}],
            "total": 25,
        }

        class DummyResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return self._payload

        class DummyRequestSession:
            def __init__(self, payload):
                self.payload = payload

            def post(self, *args, **kwargs):
                return DummyResponse(self.payload)

        array_result = qingdao_rc.fetch_json_page(DummyRequestSession(array_payload), query="Java", page_no=1, region_code="", timeout_seconds=10)
        dict_result = qingdao_rc.fetch_json_page(DummyRequestSession(dict_payload), query="Java", page_no=2, region_code="", timeout_seconds=10)

        self.assertEqual(array_result["page_size"], 2)
        self.assertEqual(array_result["total_pages"], 3)
        self.assertEqual(array_result["items"][0]["gwname"], "Java后端工程师")
        self.assertEqual(dict_result["total_count"], 25)
        self.assertEqual(dict_result["items"][0]["gwname"], "前端开发")

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <div class="left-title"><div class="name">Java后端工程师</div><div class="money">1w-2w</div></div>
          <ul class="left-btn"><li>不限</li><li>大学本科</li><li>10人</li></ul>
          <div class="bottom-item"><div><div class="company">青岛乾程科技股份有限公司</div></div></div>
          <div class="main-left-box">
            <div class="main-left-item"><div class="content2">举办地点：青岛</div><div class="content2">举办时间：9.25</div></div>
            <div class="main-left-item"><div class="title">任职要求<div class="xiaokuai"></div></div><div class="content">计算机相关专业</div></div>
            <div class="main-left-item"><div class="title">岗位描述<div class="xiaokuai"></div></div><div class="content">负责后端开发</div></div>
          </div>
          <div class="main-right-box">
            <div class="main-right-item">
              <div class="lable"><span class="lable-text">民营企业</span></div>
              <div class="lable"><span class="lable-text">崂山区</span></div>
              <div class="lable"><span class="lable-text">13800138000</span></div>
              <div class="lable"><span class="lable-text">hr@example.com</span></div>
              <div class="lable"><span class="lable-text">公司主营智能电力设备。</span></div>
            </div>
          </div>
        </body></html>
        """

        result = qingdao_rc.parse_detail_html(html)

        self.assertEqual(result["title"], "Java后端工程师")
        self.assertEqual(result["salary_text"], "1w-2w")
        self.assertEqual(result["company_name"], "青岛乾程科技股份有限公司")
        self.assertEqual(result["location_text"], "崂山区")
        self.assertEqual(result["contact_phone"], "13800138000")
        self.assertEqual(result["email"], "hr@example.com")
        self.assertIn("计算机相关专业", result["requirement_text"])

    def test_run_incremental_update_tracks_unsupported_locations(self) -> None:
        fake_job = {
            "source_job_id": "2-abc",
            "title": "Java开发工程师",
            "company_name": "测试公司",
            "city_name": "青岛",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            city_name = str(kwargs.get("city_name") or "")
            if city_name == "青岛":
                return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 12, "total_pages": 1, "upstream_page_size": 12, "supported": True}
            return {"pages": [], "matched_jobs": [], "api_pages": 0, "total_count": 0, "total_pages": 0, "upstream_page_size": 0, "supported": False}

        with patch.object(qingdao_rc, "ensure_db"), patch.object(qingdao_rc, "build_session", return_value=DummySession()), patch.object(
            qingdao_rc, "warmup_listing"
        ), patch.object(qingdao_rc, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs), patch.object(
            qingdao_rc, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}
        ):
            result = qingdao_rc.run_incremental_update(
                queries=["Java"],
                cities=["青岛", "北京"],
                max_pages=1,
            )

        self.assertEqual(result["resolved_region_codes"], {"青岛": ""})
        self.assertEqual(result["unsupported_locations"], ["北京"])
        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 1, "unsupported_targets": 1, "empty_targets": 0})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "unsupported_city"])


if __name__ == "__main__":
    unittest.main()