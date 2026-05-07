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
                "active_source_count_7d": 0,
                "historical_source_count": 0,
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
                                "2026-03-20 09:00:00",
                            ),
                        ],
                    )
                    conn.commit()

                result = database.get_job_market_analytics(status="active", top_n=3, focus_source_code="qdhr")

            self.assertEqual(result["overview"]["total_jobs"], 4)
            self.assertEqual(result["overview"]["recent_7d_count"], 3)
            self.assertEqual(result["overview"]["active_source_count_7d"], 1)
            self.assertEqual(result["overview"]["historical_source_count"], 1)
            self.assertEqual(result["source_distribution"][0]["source_code"], "qdhr")
            self.assertEqual(result["source_distribution"][0]["active_7d_job_count"], 3)
            self.assertEqual(result["source_distribution"][0]["historical_job_count"], 0)
            self.assertTrue(result["source_distribution"][0]["is_active_7d"])
            self.assertEqual(result["source_distribution"][1]["source_code"], "boss")
            self.assertEqual(result["source_distribution"][1]["active_7d_job_count"], 0)
            self.assertEqual(result["source_distribution"][1]["historical_job_count"], 1)
            self.assertFalse(result["source_distribution"][1]["is_active_7d"])
            focus_profile = result["focus_source_profile"]
            self.assertIsNotNone(focus_profile)
            assert focus_profile is not None
            self.assertEqual(focus_profile["source_code"], "qdhr")
            self.assertEqual(focus_profile["requested_source_code"], "qdhr")
            self.assertEqual(focus_profile["profile_mode"], "requested_active")
            self.assertEqual(focus_profile["total_jobs"], 3)
            self.assertEqual(focus_profile["active_7d_job_count"], 3)
            self.assertEqual(focus_profile["historical_job_count"], 0)
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

    def test_get_job_market_analytics_falls_back_to_requested_all_scope_when_active_scope_is_empty(self) -> None:
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
                                "qdhr-old-1",
                                "质量工程师",
                                "青岛样本公司",
                                "青岛",
                                "崂山区",
                                "8-12K",
                                "全职",
                                "hash-qdhr-old-1",
                                "content-qdhr-old-1",
                                "qdhr",
                                "inactive",
                                "2026-03-10 10:00:00",
                            ),
                            (
                                "job51-1",
                                "Java工程师",
                                "全国样本公司",
                                "上海",
                                "浦东新区",
                                "15-20K",
                                "全职",
                                "hash-job51-1",
                                "content-job51-1",
                                "job51",
                                "active",
                                "2026-04-05 10:00:00",
                            ),
                        ],
                    )
                    conn.commit()

                result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="qdhr")

            focus_profile = result["focus_source_profile"]
            self.assertIsNotNone(focus_profile)
            assert focus_profile is not None
            self.assertEqual(result["source_distribution"][0]["source_code"], "job51")
            self.assertEqual(result["source_distribution"][1]["source_code"], "qdhr")
            self.assertEqual(result["source_distribution"][1]["active_7d_job_count"], 0)
            self.assertEqual(result["source_distribution"][1]["historical_job_count"], 1)
            self.assertEqual(focus_profile["source_code"], "qdhr")
            self.assertEqual(focus_profile["requested_source_code"], "qdhr")
            self.assertEqual(focus_profile["profile_mode"], "requested_all")
            self.assertEqual(focus_profile["total_jobs"], 1)
            self.assertEqual(focus_profile["active_7d_job_count"], 0)
            self.assertEqual(focus_profile["historical_job_count"], 1)
            self.assertIn("active 口径样本为 0", focus_profile["profile_note"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_get_job_market_analytics_falls_back_to_active_source_when_requested_source_missing(self) -> None:
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
                                "job51-1",
                                "Java工程师",
                                "全国样本公司",
                                "上海",
                                "浦东新区",
                                "15-20K",
                                "全职",
                                "hash-job51-1",
                                "content-job51-1",
                                "job51",
                                "active",
                                "2026-04-05 10:00:00",
                            ),
                            (
                                "job51-2",
                                "测试工程师",
                                "全国样本公司",
                                "上海",
                                "浦东新区",
                                "12-16K",
                                "全职",
                                "hash-job51-2",
                                "content-job51-2",
                                "job51",
                                "active",
                                "2026-04-05 11:00:00",
                            ),
                        ],
                    )
                    conn.commit()

                result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="qdhr")

            focus_profile = result["focus_source_profile"]
            self.assertIsNotNone(focus_profile)
            assert focus_profile is not None
            self.assertEqual(result["source_distribution"][0]["source_code"], "job51")
            self.assertEqual(focus_profile["requested_source_code"], "qdhr")
            self.assertEqual(focus_profile["source_code"], "job51")
            self.assertEqual(focus_profile["profile_mode"], "fallback_active")
            self.assertEqual(focus_profile["total_jobs"], 2)
            self.assertIn("临时展示", focus_profile["profile_note"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_get_job_market_analytics_keeps_inactive_only_sources_in_source_distribution(self) -> None:
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
                                "job51-1",
                                "Java工程师",
                                "全国样本公司",
                                "上海",
                                "浦东新区",
                                "15-20K",
                                "全职",
                                "hash-job51-1",
                                "content-job51-1",
                                "job51",
                                "active",
                                "2026-04-05 10:00:00",
                            ),
                            (
                                "boss-old-1",
                                "Python开发",
                                "Boss样本公司",
                                "北京",
                                "朝阳区",
                                "20-30K",
                                "全职",
                                "hash-boss-old-1",
                                "content-boss-old-1",
                                "boss_dp",
                                "inactive",
                                "2026-04-08 08:00:00",
                            ),
                        ],
                    )
                    conn.commit()

                result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="job51")

            source_codes = [item["source_code"] for item in result["source_distribution"]]
            self.assertEqual(source_codes, ["job51", "boss_dp"])
            self.assertEqual(result["source_distribution"][1]["job_count"], 1)
            self.assertEqual(result["source_distribution"][1]["active_7d_job_count"], 0)
            self.assertEqual(result["source_distribution"][1]["historical_job_count"], 1)
            self.assertEqual(result["source_distribution"][1]["last_seen_at"], "2026-04-08 08:00:00")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_get_job_market_analytics_reuses_cache_when_database_is_unchanged(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"
        analytics_cache_dir = temp_root / "cache"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ), patch.object(database, "JOB_MARKET_ANALYTICS_CACHE_DIR", analytics_cache_dir), patch.object(
                database,
                "JOB_MARKET_ANALYTICS_CACHE_TTL_SECONDS",
                300,
            ), patch.dict(database._JOB_MARKET_ANALYTICS_MEMORY_CACHE, {}, clear=True):
                database.init_database()
                with database.get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, district_name, salary_text,
                            job_type, unique_hash, content_hash, source_code, status, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "job51-1",
                            "Java工程师",
                            "全国样本公司",
                            "上海",
                            "浦东新区",
                            "15-20K",
                            "全职",
                            "hash-job51-1",
                            "content-job51-1",
                            "job51",
                            "active",
                            "2026-04-05 10:00:00",
                        ),
                    )
                    conn.commit()

                with patch.object(database, "mark_stale_jobs_inactive", return_value={"inactive_marked": 0}) as stale_mock:
                    first_result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="job51")
                    second_result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="job51")

            self.assertEqual(stale_mock.call_count, 1)
            self.assertEqual(first_result["overview"]["total_jobs"], 1)
            self.assertEqual(second_result["overview"]["total_jobs"], 1)
            self.assertEqual(second_result["source_distribution"][0]["source_code"], "job51")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_get_job_market_analytics_invalidates_cache_after_database_change(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"
        analytics_cache_dir = temp_root / "cache"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ), patch.object(database, "JOB_MARKET_ANALYTICS_CACHE_DIR", analytics_cache_dir), patch.object(
                database,
                "JOB_MARKET_ANALYTICS_CACHE_TTL_SECONDS",
                300,
            ), patch.dict(database._JOB_MARKET_ANALYTICS_MEMORY_CACHE, {}, clear=True):
                database.init_database()
                with database.get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, district_name, salary_text,
                            job_type, unique_hash, content_hash, source_code, status, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "job51-1",
                            "Java工程师",
                            "全国样本公司",
                            "上海",
                            "浦东新区",
                            "15-20K",
                            "全职",
                            "hash-job51-1",
                            "content-job51-1",
                            "job51",
                            "active",
                            "2026-04-05 10:00:00",
                        ),
                    )
                    conn.commit()

                with patch.object(database, "mark_stale_jobs_inactive", return_value={"inactive_marked": 0}) as stale_mock:
                    first_result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="job51")
                    with database.get_connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO jobs (
                                source_job_id, title, company_name, city_name, district_name, salary_text,
                                job_type, unique_hash, content_hash, source_code, status, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "job51-2",
                                "测试工程师",
                                "全国样本公司",
                                "上海",
                                "浦东新区",
                                "12-16K",
                                "全职",
                                "hash-job51-2",
                                "content-job51-2",
                                "job51",
                                "active",
                                "2026-04-05 11:00:00",
                            ),
                        )
                        conn.commit()
                    second_result = database.get_job_market_analytics(status="active", top_n=5, focus_source_code="job51")

            self.assertEqual(stale_mock.call_count, 2)
            self.assertEqual(first_result["overview"]["total_jobs"], 1)
            self.assertEqual(second_result["overview"]["total_jobs"], 2)
            self.assertEqual(second_result["focus_source_profile"]["total_jobs"], 2)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()