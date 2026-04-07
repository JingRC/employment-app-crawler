from __future__ import annotations

import shutil
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

from app.api.routes import jobs  # noqa: E402
from app.core import database  # noqa: E402


class JobsAnalyticsRouteTests(unittest.TestCase):
    def test_get_job_analytics_forwards_focus_source_code(self) -> None:
        fake_result = {
            "overview": {
                "total_jobs": 0,
                "total_companies": 0,
                "total_cities": 0,
                "average_salary_k": None,
                "salary_sample_count": 0,
                "recent_24h_count": 0,
                "recent_7d_count": 0,
                "status_scope": "active",
            },
            "city_distribution": [],
            "source_distribution": [],
            "salary_distribution": [],
            "focus_source_profile": None,
        }

        with patch.object(jobs, "query_job_market_analytics", return_value=fake_result) as query_mock:
            result = jobs.get_job_analytics(status="active", top_n=8, focus_source_code="qdhr")

        query_mock.assert_called_once_with(status="active", top_n=8, focus_source_code="qdhr")
        self.assertEqual(result["code"], 0)


class JobMarketAnalyticsFocusProfileTests(unittest.TestCase):
    def test_get_job_market_analytics_builds_focus_profile(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ), patch.object(database, "mark_stale_jobs_inactive", return_value={"updated": 0}):
                database.init_database()
                with database.get_connection() as conn:
                    conn.executemany(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, district_name, salary_text,
                            job_type, unique_hash, content_hash, source_code, status, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                "qdhr-1",
                                "Java工程师",
                                "青岛镭测创芯科技有限公司",
                                "青岛",
                                "崂山区",
                                "12-18K",
                                "全职",
                                "hash-qdhr-1",
                                "content-qdhr-1",
                                "qdhr",
                                "active",
                                "2026-04-05 10:00:00",
                            ),
                            (
                                "qdhr-2",
                                "测试工程师",
                                "青岛镭测创芯科技有限公司",
                                "青岛",
                                "崂山区",
                                "10-14K",
                                "全职",
                                "hash-qdhr-2",
                                "content-qdhr-2",
                                "qdhr",
                                "active",
                                "2026-04-05 11:00:00",
                            ),
                            (
                                "qdhr-3",
                                "产品实习生",
                                "海纳云物联科技有限公司",
                                "青岛",
                                "黄岛区",
                                "150元/天",
                                "实习",
                                "hash-qdhr-3",
                                "content-qdhr-3",
                                "qdhr",
                                "active",
                                "2026-04-05 12:00:00",
                            ),
                            (
                                "boss-1",
                                "Python开发",
                                "外部公司",
                                "北京",
                                "朝阳区",
                                "20-30K",
                                "全职",
                                "hash-boss-1",
                                "content-boss-1",
                                "boss",
                                "active",
                                "2026-04-05 09:00:00",
                            ),
                        ],
                    )
                    conn.commit()

                result = database.get_job_market_analytics(status="active", top_n=3, focus_source_code="qdhr")

            self.assertEqual(result["overview"]["total_jobs"], 4)
            focus_profile = result["focus_source_profile"]
            self.assertIsNotNone(focus_profile)
            assert focus_profile is not None
            self.assertEqual(focus_profile["source_code"], "qdhr")
            self.assertEqual(focus_profile["total_jobs"], 3)
            self.assertEqual(focus_profile["total_companies"], 2)
            self.assertEqual(focus_profile["total_cities"], 1)
            self.assertEqual(focus_profile["total_districts"], 2)
            self.assertEqual(focus_profile["district_distribution"][0], {"label": "崂山区", "job_count": 2})
            self.assertEqual(focus_profile["company_distribution"][0], {"label": "青岛镭测创芯科技有限公司", "job_count": 2})
            self.assertEqual(focus_profile["job_type_distribution"][0], {"label": "全职", "job_count": 2})
            self.assertEqual(focus_profile["job_type_distribution"][1], {"label": "实习", "job_count": 1})
            self.assertGreater(float(focus_profile["average_salary_k"]), 7.0)
            self.assertEqual(int(focus_profile["salary_sample_count"]), 3)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()