from __future__ import annotations

import base64
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sdgxbys_joblist_crawl as sdgxbys  # noqa: E402


class DummySession:
    def close(self) -> None:
        return None


class SdgxbysJoblistCrawlTests(unittest.TestCase):
    def test_normalize_source_options_parses_bounds(self) -> None:
        result = sdgxbys.normalize_source_options(
            {
                "detail_mode": "bad-mode",
                "request_timeout_seconds": "99",
                "sleep_seconds": "-1",
            }
        )

        self.assertEqual(result["detail_mode"], "detail_html")
        self.assertEqual(result["request_timeout_seconds"], 60.0)
        self.assertEqual(result["sleep_seconds"], 0.0)

    def test_decode_embedded_list_html_restores_compressed_payload(self) -> None:
        content = '<ul class="list"><li><a href="/job/view/id/1">测试岗位</a></li></ul>'
        substr_1 = 7
        substr_2 = 5
        second_stage = ("x" * substr_2 + content).encode("utf-8")
        inflated_text = ("y" * substr_1) + base64.b64encode(second_stage).decode("ascii")
        payload = base64.b64encode(zlib.compress(inflated_text.encode("latin1"))).decode("ascii")
        html = f'<script>$("#content1").each(function(){{$(this).replaceWith(Base64.decode(unzip("{payload}").substr({substr_1})).substr({substr_2}));}});</script>'

        result = sdgxbys.decode_embedded_list_html(html)

        self.assertEqual(result, content)

    def test_parse_list_page_extracts_items_and_total_pages(self) -> None:
        decoded_html = """
        <ul class="list">
          <li>
            <div class="left">
              <div class="job">
                <div class="company">
                  <a href="/companydetail/view/id/413180">合众人寿保险股份有限公司枣庄中心支公司</a>
                  <div class="clearfix"><ul><li>其他企业（含民营企业等）</li><li>少于50人</li></ul></div>
                </div>
                <div class="name">
                  <a class="text-primary" href="/job/view/id/1320718">综合内勤[山东省 - 枣庄市]</a>
                  <small>2026-01-17</small>
                </div>
                <div class="clearfix">
                  <span class="text-orange">5000-5499</span>
                  <ul><li>本科</li><li>不限</li><li>全职</li></ul>
                </div>
              </div>
            </div>
          </li>
        </ul>
        <a href="/job/index?page=5">5</a>
        <a href="/job/index?page=3371">末页</a>
        """

        result = sdgxbys.parse_list_page(decoded_html, 1)

        self.assertEqual(result["total_pages"], 3371)
        self.assertEqual(result["items"][0]["title"], "综合内勤")
        self.assertEqual(result["items"][0]["company_name"], "合众人寿保险股份有限公司枣庄中心支公司")
        self.assertEqual(result["items"][0]["salary_text"], "5000-5499")

    def test_parse_detail_html_extracts_core_fields(self) -> None:
        html = """
        <html><body>
          <div class="head">
            <h2>学徒工</h2>
            <ul><li><a class="text-primary" href="/companydetail/view/id/498900">青岛科源世电子科技有限公司</a></li></ul>
          </div>
          <div class="content">
            <div class="info">
              <ul class="b-b-e">
                <li><label>单位性质：</label><span>其他企业（含民营企业等）</span></li>
                <li><label>单位行业：</label><span>橡胶和塑料制品业</span></li>
                <li><label>单位规模：</label><span>100-499人</span></li>
              </ul>
              <ul>
                <li><label>月薪：</label><span>3500-3999</span></li>
                <li><label>招聘人数：</label><span>3人</span></li>
                <li><label>发布时间：</label><span>2026-01-13 00:00</span></li>
                <li><label>职位性质：</label><span>实习</span></li>
                <li><label>职位类别：</label><span>模具工</span></li>
                <li><label>工作地点：</label><span>山东省 - 青岛市</span></li>
                <li><label>学历要求：</label><span>大专</span></li>
                <li><label>工作经验：</label><span>不限</span></li>
              </ul>
            </div>
            <div class="jobinfo">
              <div class="text">
                <div><p>模具车间招聘实习生 3 名</p><p>先从铣床、磨床学起。</p></div>
                <div class="hide"><div class="title"><b>单位介绍</b></div><p>公司介绍</p></div>
              </div>
            </div>
          </div>
        </body></html>
        """

        result = sdgxbys.parse_detail_html(html, "https://job.sdgxbys.cn/job/view/id/1320672")

        self.assertEqual(result["title"], "学徒工")
        self.assertEqual(result["company_name"], "青岛科源世电子科技有限公司")
        self.assertEqual(result["salary_text"], "3500-3999")
        self.assertEqual(result["degree_text"], "大专")
        self.assertEqual(result["experience_text"], "不限")
        self.assertEqual(result["job_type"], "实习")
        self.assertEqual(result["city_name"], "青岛")
        self.assertIn("模具车间招聘实习生", result["description_text"])

    def test_run_incremental_update_tracks_empty_targets(self) -> None:
        fake_job = {
            "source_job_id": "/job/view/id/1320672",
            "title": "学徒工",
            "company_name": "青岛科源世电子科技有限公司",
            "city_name": "青岛",
        }

        def fake_collect_filtered_jobs(*args, **kwargs):
            city_name = str(kwargs.get("city_name") or "")
            if city_name == "火星":
                return {"pages": [], "matched_jobs": [], "api_pages": 1, "total_count": 0, "total_pages": 3371, "upstream_page_size": 10}
            return {"pages": [[fake_job]], "matched_jobs": [fake_job], "api_pages": 1, "total_count": 33710, "total_pages": 3371, "upstream_page_size": 10}

        with patch.object(sdgxbys, "ensure_db"), patch.object(sdgxbys, "build_session", return_value=DummySession()), patch.object(
            sdgxbys, "collect_filtered_jobs", side_effect=fake_collect_filtered_jobs
        ), patch.object(sdgxbys, "save_to_db", return_value={"new": 1, "updated": 0, "unchanged": 0}):
            result = sdgxbys.run_incremental_update(
                queries=["学徒"],
                cities=["青岛", "火星"],
                max_pages=1,
            )

        self.assertEqual(result["request_summary"], {"total_targets": 2, "resolved_targets": 1, "empty_targets": 1})
        self.assertEqual([item["status"] for item in result["request_trace"]], ["resolved", "empty"])

    def test_collect_filtered_jobs_keeps_previous_pages_when_later_page_fails(self) -> None:
        page_one = {
            "items": [
                {
                    "title": "学徒工",
                    "company_name": "青岛科源世电子科技有限公司",
                    "location_text": "山东省 - 青岛市",
                    "detail_url": "https://job.sdgxbys.cn/job/view/id/1320672",
                    "salary_text": "3500-3999",
                    "degree_text": "大专",
                    "experience_text": "不限",
                    "job_type": "实习",
                    "published_at": "2026-01-13 00:00",
                    "summary_text": "学徒工 青岛科源世电子科技有限公司 山东省 - 青岛市",
                }
            ],
            "total_pages": 4,
            "total_count": 40,
            "page_size": 10,
        }

        with patch.object(sdgxbys, "fetch_list_page", side_effect=[page_one, RuntimeError("503")]), patch.object(
            sdgxbys, "fetch_text", return_value=("", "https://job.sdgxbys.cn/job/view/id/1320672")
        ), patch.object(
            sdgxbys, "parse_detail_html", return_value={}
        ):
            result = sdgxbys.collect_filtered_jobs(
                DummySession(),
                query="学徒",
                city_name="山东",
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