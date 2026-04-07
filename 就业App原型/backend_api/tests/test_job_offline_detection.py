from __future__ import annotations

import sys
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.core import database  # noqa: E402


class JobOfflineDetectionTests(unittest.TestCase):
    def test_mark_stale_jobs_inactive_and_hide_from_list(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ):
                database.init_database()
                with database.get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, salary_text,
                            unique_hash, content_hash, source_code, status, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "stale-1",
                            "过期岗位",
                            "旧公司",
                            "北京",
                            "10-15K",
                            "hash-stale-1",
                            "content-stale-1",
                            "boss",
                            "active",
                            "2026-03-20 08:00:00",
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, salary_text,
                            unique_hash, content_hash, source_code, status, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "fresh-1",
                            "新鲜岗位",
                            "新公司",
                            "北京",
                            "15-20K",
                            "hash-fresh-1",
                            "content-fresh-1",
                            "boss",
                            "active",
                            "2026-03-30 10:00:00",
                        ),
                    )
                    conn.commit()

                stats = database.mark_stale_jobs_inactive(
                    stale_after_hours=72,
                    now=datetime(2026, 3, 30, 12, 0, 0),
                )

                self.assertEqual(stats["inactive_marked"], 1)

                with database.get_connection() as conn:
                    stale_row = conn.execute("SELECT status FROM jobs WHERE source_job_id = ?", ("stale-1",)).fetchone()
                    fresh_row = conn.execute("SELECT status FROM jobs WHERE source_job_id = ?", ("fresh-1",)).fetchone()

                self.assertEqual(str(stale_row["status"]), "inactive")
                self.assertEqual(str(fresh_row["status"]), "active")

                result = database.list_jobs(
                    keyword=None,
                    city_name="北京",
                    internship_only=False,
                    source_code="boss",
                    status="active",
                    salary_min_k=None,
                    salary_max_k=None,
                    degree_text=None,
                    experience_text=None,
                    sort_by="latest",
                    page=1,
                    page_size=20,
                )
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["items"][0]["title"], "新鲜岗位")
                self.assertEqual(result["items"][0]["status"], "active")

                offline_result = database.list_jobs(
                    keyword=None,
                    city_name="北京",
                    internship_only=False,
                    source_code="boss",
                    status="inactive",
                    salary_min_k=None,
                    salary_max_k=None,
                    degree_text=None,
                    experience_text=None,
                    sort_by="latest",
                    page=1,
                    page_size=20,
                )
                self.assertEqual(offline_result["total"], 1)
                self.assertEqual(offline_result["items"][0]["title"], "过期岗位")
                self.assertEqual(offline_result["items"][0]["status"], "inactive")

                offline_filters = database.list_job_filter_options(status="inactive")
                self.assertEqual(offline_filters["cities"][0]["city_name"], "北京")
                self.assertEqual(offline_filters["sources"][0]["source_code"], "boss")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_verify_pending_inactive_jobs_updates_status_by_verification_result(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ):
                database.init_database()
                with database.get_connection() as conn:
                    conn.executemany(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, salary_text,
                            unique_hash, content_hash, source_code, status, last_seen_at,
                            source_url, official_apply_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                "stale-online",
                                "恢复岗位",
                                "在线公司",
                                "北京",
                                "12-18K",
                                "hash-stale-online",
                                "content-stale-online",
                                "boss",
                                "active",
                                "2026-03-20 08:00:00",
                                "https://example.com/source-online",
                                "https://example.com/online",
                            ),
                            (
                                "stale-offline",
                                "确认下架岗位",
                                "下架公司",
                                "北京",
                                "12-18K",
                                "hash-stale-offline",
                                "content-stale-offline",
                                "boss",
                                "active",
                                "2026-03-20 08:05:00",
                                "https://example.com/source-offline",
                                "https://example.com/offline",
                            ),
                            (
                                "stale-review",
                                "待复核岗位",
                                "复核公司",
                                "北京",
                                "12-18K",
                                "hash-stale-review",
                                "content-stale-review",
                                "boss",
                                "active",
                                "2026-03-20 08:10:00",
                                "https://example.com/review",
                                "",
                            ),
                            (
                                "stale-missing",
                                "缺链接岗位",
                                "缺链公司",
                                "北京",
                                "12-18K",
                                "hash-stale-missing",
                                "content-stale-missing",
                                "boss",
                                "active",
                                "2026-03-20 08:15:00",
                                "",
                                "",
                            ),
                        ],
                    )
                    conn.commit()

                mark_stats = database.mark_stale_jobs_inactive(
                    stale_after_hours=72,
                    now=datetime(2026, 3, 30, 12, 0, 0),
                )

                self.assertEqual(mark_stats["inactive_marked"], 4)

                with database.get_connection() as conn:
                    pending_rows = conn.execute(
                        "SELECT source_job_id, status, offline_verification_status FROM jobs ORDER BY id ASC"
                    ).fetchall()

                self.assertEqual(
                    [(str(row["source_job_id"]), str(row["status"]), str(row["offline_verification_status"])) for row in pending_rows],
                    [
                        ("stale-online", "inactive", "pending"),
                        ("stale-offline", "inactive", "pending"),
                        ("stale-review", "inactive", "pending"),
                        ("stale-missing", "inactive", "pending"),
                    ],
                )

                def fake_verify(url: str, timeout_seconds: float) -> dict[str, str]:
                    self.assertEqual(timeout_seconds, 8.0)
                    mapping = {
                        "https://example.com/online": {
                            "verification_status": "rechecked_online",
                            "verification_reason": "链接可访问: https://example.com/online",
                        },
                        "https://example.com/offline": {
                            "verification_status": "confirmed_offline",
                            "verification_reason": "HTTP 404",
                        },
                        "https://example.com/review": {
                            "verification_status": "needs_review",
                            "verification_reason": "HTTP 403",
                        },
                        "": {
                            "verification_status": "missing_url",
                            "verification_reason": "缺少可校验链接",
                        },
                    }
                    return mapping[url]

                with patch.object(database, "_strong_verify_job_url", side_effect=fake_verify):
                    verify_stats = database.verify_pending_inactive_jobs(limit=10, timeout_seconds=8.0)

                self.assertEqual(
                    verify_stats,
                    {
                        "verified_count": 4,
                        "restored_count": 1,
                        "confirmed_count": 1,
                        "review_count": 1,
                        "missing_url_count": 1,
                        "limit": 10,
                        "timeout_seconds": 8.0,
                    },
                )

                with database.get_connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT source_job_id, status, offline_verification_status, offline_verification_reason, offline_verified_at
                        FROM jobs
                        ORDER BY id ASC
                        """
                    ).fetchall()

                normalized_rows = {
                    str(row["source_job_id"]): {
                        "status": str(row["status"]),
                        "verification_status": str(row["offline_verification_status"] or ""),
                        "verification_reason": str(row["offline_verification_reason"] or ""),
                        "verified_at": str(row["offline_verified_at"] or ""),
                    }
                    for row in rows
                }

                self.assertEqual(normalized_rows["stale-online"]["status"], "active")
                self.assertEqual(normalized_rows["stale-online"]["verification_status"], "rechecked_online")
                self.assertIn("链接可访问", normalized_rows["stale-online"]["verification_reason"])
                self.assertTrue(normalized_rows["stale-online"]["verified_at"])

                self.assertEqual(normalized_rows["stale-offline"]["status"], "inactive")
                self.assertEqual(normalized_rows["stale-offline"]["verification_status"], "confirmed_offline")
                self.assertEqual(normalized_rows["stale-offline"]["verification_reason"], "HTTP 404")

                self.assertEqual(normalized_rows["stale-review"]["status"], "inactive")
                self.assertEqual(normalized_rows["stale-review"]["verification_status"], "needs_review")
                self.assertEqual(normalized_rows["stale-review"]["verification_reason"], "HTTP 403")

                self.assertEqual(normalized_rows["stale-missing"]["status"], "inactive")
                self.assertEqual(normalized_rows["stale-missing"]["verification_status"], "missing_url")
                self.assertEqual(normalized_rows["stale-missing"]["verification_reason"], "缺少可校验链接")

                restored_job = database.get_job_detail(1)
                self.assertIsNotNone(restored_job)
                self.assertEqual(restored_job["offline_verification_status"], "rechecked_online")
                self.assertTrue(restored_job["offline_verified_at"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_manual_verify_and_restore_job(self) -> None:
        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "jobs.db"
        missing_sample = temp_root / "missing-sample.json"

        try:
            with patch.object(database, "DATA_DIR", temp_root), patch.object(database, "DB_PATH", db_path), patch.object(
                database,
                "SAMPLE_JSON_PATH",
                missing_sample,
            ):
                database.init_database()
                with database.get_connection() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO jobs (
                            source_job_id, title, company_name, city_name, salary_text,
                            unique_hash, content_hash, source_code, status, last_seen_at,
                            source_url, official_apply_url, offline_verification_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "manual-offline-1",
                            "手动复核岗位",
                            "手动公司",
                            "北京",
                            "10-15K",
                            "hash-manual-offline-1",
                            "content-manual-offline-1",
                            "boss",
                            "inactive",
                            "2026-03-20 08:00:00",
                            "https://example.com/manual-source",
                            "https://example.com/manual-offline",
                            "pending",
                        ),
                    )
                    conn.commit()
                    job_id = int(cursor.lastrowid)

                with patch.object(
                    database,
                    "_strong_verify_job_url",
                    return_value={
                        "verification_status": "needs_review",
                        "verification_reason": "HTTP 403",
                    },
                ):
                    verified_job = database.verify_job_offline_status(job_id)

                self.assertIsNotNone(verified_job)
                self.assertEqual(verified_job["status"], "inactive")
                self.assertEqual(verified_job["offline_verification_status"], "needs_review")
                self.assertEqual(verified_job["offline_verification_reason"], "HTTP 403")
                self.assertTrue(verified_job["offline_verified_at"])

                restored_job = database.restore_job_to_active(job_id)
                self.assertIsNotNone(restored_job)
                self.assertEqual(restored_job["status"], "active")
                self.assertEqual(restored_job["offline_verification_status"], "manual_restored")
                self.assertEqual(restored_job["offline_verification_reason"], "人工恢复为在库岗位")
                self.assertTrue(restored_job["offline_verified_at"])

                missing_job = database.restore_job_to_active(job_id + 999)
                self.assertIsNone(missing_job)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
