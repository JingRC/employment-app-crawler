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

from app.services import job_service  # noqa: E402


class JobServiceActionTests(unittest.TestCase):
    def test_manually_verify_job_creates_notification(self) -> None:
        detail = {
            "job_id": 7,
            "company_id": 9,
            "title": "后端开发",
            "company_name": "测试公司",
            "offline_verification_status": "needs_review",
            "offline_verification_reason": "HTTP 403",
        }
        with patch.object(job_service, "verify_job_offline_status", return_value=detail) as verify_mock, patch.object(
            job_service,
            "create_notification",
        ) as create_notification_mock:
            result = job_service.manually_verify_job(7)

        verify_mock.assert_called_once_with(7)
        create_notification_mock.assert_called_once_with(
            notification_type="job_manual_verify",
            title="已手动复核岗位：后端开发",
            content="测试公司 / 后端开发，复核结果：HTTP 403",
            related_job_id=7,
            related_company_id=9,
        )
        self.assertEqual(result, detail)

    def test_manually_verify_job_creates_batch_notification_when_requested(self) -> None:
        detail = {
            "job_id": 17,
            "company_id": 19,
            "title": "数据开发",
            "company_name": "批量公司",
            "offline_verification_status": "confirmed_offline",
            "offline_verification_reason": "HTTP 404",
        }
        with patch.object(job_service, "verify_job_offline_status", return_value=detail), patch.object(
            job_service,
            "create_notification",
        ) as create_notification_mock:
            result = job_service.manually_verify_job(17, action_source="batch")

        create_notification_mock.assert_called_once_with(
            notification_type="job_batch_verify",
            title="已手动复核岗位：数据开发",
            content="批量公司 / 数据开发，复核结果：HTTP 404",
            related_job_id=17,
            related_company_id=19,
        )
        self.assertEqual(result, detail)

    def test_manually_restore_job_creates_notification(self) -> None:
        detail = {
            "job_id": 8,
            "company_id": 10,
            "title": "测试开发",
            "company_name": "恢复公司",
        }
        with patch.object(job_service, "restore_job_to_active", return_value=detail) as restore_mock, patch.object(
            job_service,
            "create_notification",
        ) as create_notification_mock:
            result = job_service.manually_restore_job(8)

        restore_mock.assert_called_once_with(8)
        create_notification_mock.assert_called_once_with(
            notification_type="job_manual_restore",
            title="已人工恢复岗位：测试开发",
            content="恢复公司 / 测试开发 已从回收站恢复到在库列表",
            related_job_id=8,
            related_company_id=10,
        )
        self.assertEqual(result, detail)

    def test_manually_restore_job_creates_batch_notification_when_requested(self) -> None:
        detail = {
            "job_id": 18,
            "company_id": 20,
            "title": "运维开发",
            "company_name": "批量恢复公司",
        }
        with patch.object(job_service, "restore_job_to_active", return_value=detail), patch.object(
            job_service,
            "create_notification",
        ) as create_notification_mock:
            result = job_service.manually_restore_job(18, action_source="batch")

        create_notification_mock.assert_called_once_with(
            notification_type="job_batch_restore",
            title="已人工恢复岗位：运维开发",
            content="批量恢复公司 / 运维开发 已从回收站恢复到在库列表",
            related_job_id=18,
            related_company_id=20,
        )
        self.assertEqual(result, detail)

    def test_batch_verify_jobs_aggregates_results(self) -> None:
        with patch.object(
            job_service,
            "manually_verify_job",
            side_effect=[
                {"job_id": 1, "status": "inactive"},
                {"job_id": 2, "status": "active"},
                None,
            ],
        ) as verify_mock:
            result = job_service.batch_verify_jobs([1, 2, 3, 2])

        self.assertEqual(verify_mock.call_args_list[0].args[0], 1)
        self.assertEqual(verify_mock.call_args_list[1].args[0], 2)
        self.assertEqual(verify_mock.call_args_list[2].args[0], 3)
        self.assertEqual(verify_mock.call_args_list[0].kwargs.get("action_source"), "batch")
        self.assertEqual(verify_mock.call_args_list[1].kwargs.get("action_source"), "batch")
        self.assertEqual(verify_mock.call_args_list[2].kwargs.get("action_source"), "batch")
        self.assertEqual(
            result,
            {
                "requested_count": 3,
                "success_count": 2,
                "failed_count": 1,
                "restored_count": 1,
                "items": [{"job_id": 1, "status": "inactive"}, {"job_id": 2, "status": "active"}],
                "failed_job_ids": [3],
            },
        )

    def test_batch_restore_jobs_aggregates_results(self) -> None:
        with patch.object(
            job_service,
            "manually_restore_job",
            side_effect=[
                {"job_id": 11, "status": "active"},
                None,
            ],
        ) as restore_mock:
            result = job_service.batch_restore_jobs([11, 12, 11])

        self.assertEqual(restore_mock.call_args_list[0].args[0], 11)
        self.assertEqual(restore_mock.call_args_list[1].args[0], 12)
        self.assertEqual(restore_mock.call_args_list[0].kwargs.get("action_source"), "batch")
        self.assertEqual(restore_mock.call_args_list[1].kwargs.get("action_source"), "batch")
        self.assertEqual(
            result,
            {
                "requested_count": 2,
                "success_count": 1,
                "failed_count": 1,
                "restored_count": 1,
                "items": [{"job_id": 11, "status": "active"}],
                "failed_job_ids": [12],
            },
        )


if __name__ == "__main__":
    unittest.main()