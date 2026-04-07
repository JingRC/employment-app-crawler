from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.api.routes import jobs  # noqa: E402


class JobsStatusRouteTests(unittest.TestCase):
    def test_list_jobs_forwards_status(self) -> None:
        fake_result = {"page": 1, "page_size": 20, "total": 0, "items": []}
        with patch.object(jobs, "query_jobs", return_value=fake_result) as query_mock:
            result = jobs.list_jobs(
                keyword=None,
                city_name=None,
                internship_only=False,
                source_code=None,
                status="inactive",
                offline_verification_status="needs_review",
                salary_min_k=None,
                salary_max_k=None,
                degree_text=None,
                experience_text=None,
                sort_by="latest",
                page=1,
                page_size=20,
            )

        query_mock.assert_called_once_with(
            keyword=None,
            city_name=None,
            internship_only=False,
            source_code=None,
            status="inactive",
            offline_verification_status="needs_review",
            salary_min_k=None,
            salary_max_k=None,
            degree_text=None,
            experience_text=None,
            sort_by="latest",
            page=1,
            page_size=20,
        )
        self.assertEqual(result["code"], 0)

    def test_list_job_filters_forwards_status(self) -> None:
        fake_result = {"cities": [], "sources": [], "degrees": [], "experiences": [], "verification_statuses": []}
        with patch.object(jobs, "query_job_filter_options", return_value=fake_result) as query_mock:
            result = jobs.list_job_filters(status="inactive", offline_verification_status="needs_review")

        query_mock.assert_called_once_with(status="inactive", offline_verification_status="needs_review")
        self.assertEqual(result["code"], 0)

    def test_verify_job_offline_forwards_to_service(self) -> None:
        fake_detail = {
            "job_id": 12,
            "company_id": 3,
            "title": "待复核岗位",
            "company_name": "测试公司",
            "city_name": "北京",
            "district_name": "",
            "salary_text": "10-15K",
            "degree_text": "本科",
            "experience_text": "不限",
            "description_text": "",
            "source_url": "",
            "official_apply_url": "",
            "job_type": "",
            "brand_scale": "",
            "brand_stage": "",
            "source_code": "boss",
            "source_name": "Boss直聘",
            "status": "inactive",
            "last_seen_at": "2026-03-30 10:00:00",
            "offline_verification_status": "needs_review",
            "offline_verification_reason": "HTTP 403",
            "offline_verified_at": "2026-03-30 12:00:00",
        }
        with patch.object(jobs, "manually_verify_job", return_value=fake_detail) as verify_mock:
            result = jobs.verify_job_offline(12)

        verify_mock.assert_called_once_with(12)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["offline_verification_status"], "needs_review")

    def test_restore_job_forwards_to_service(self) -> None:
        fake_detail = {
            "job_id": 12,
            "company_id": 3,
            "title": "恢复岗位",
            "company_name": "测试公司",
            "city_name": "北京",
            "district_name": "",
            "salary_text": "10-15K",
            "degree_text": "本科",
            "experience_text": "不限",
            "description_text": "",
            "source_url": "",
            "official_apply_url": "",
            "job_type": "",
            "brand_scale": "",
            "brand_stage": "",
            "source_code": "boss",
            "source_name": "Boss直聘",
            "status": "active",
            "last_seen_at": "2026-03-30 12:00:00",
            "offline_verification_status": "manual_restored",
            "offline_verification_reason": "人工恢复为在库岗位",
            "offline_verified_at": "2026-03-30 12:00:00",
        }
        with patch.object(jobs, "manually_restore_job", return_value=fake_detail) as restore_mock:
            result = jobs.restore_job(12)

        restore_mock.assert_called_once_with(12)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["status"], "active")

    def test_batch_verify_jobs_forwards_to_service(self) -> None:
        fake_result = {
            "requested_count": 2,
            "success_count": 2,
            "failed_count": 0,
            "restored_count": 1,
            "items": [],
            "failed_job_ids": [],
        }
        with patch.object(jobs, "batch_verify_jobs", return_value=fake_result) as batch_mock:
            result = jobs.batch_verify_offline_jobs(jobs.JobBatchActionRequest(job_ids=[1, 2]))

        batch_mock.assert_called_once_with([1, 2])
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["restored_count"], 1)

    def test_batch_restore_jobs_forwards_to_service(self) -> None:
        fake_result = {
            "requested_count": 2,
            "success_count": 1,
            "failed_count": 1,
            "restored_count": 1,
            "items": [],
            "failed_job_ids": [3],
        }
        with patch.object(jobs, "batch_restore_jobs", return_value=fake_result) as batch_mock:
            result = jobs.batch_restore_offline_jobs(jobs.JobBatchActionRequest(job_ids=[2, 3]))

        batch_mock.assert_called_once_with([2, 3])
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["failed_job_ids"], [3])



if __name__ == "__main__":
    unittest.main()
