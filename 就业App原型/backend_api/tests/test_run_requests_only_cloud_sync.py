from __future__ import annotations

import json
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

import run_requests_only_cloud_sync as cloud_sync  # noqa: E402


class RunRequestsOnlyCloudSyncTests(unittest.TestCase):
    def test_resolve_sources_defaults_when_unset(self) -> None:
        self.assertEqual(cloud_sync.resolve_sources(None), cloud_sync.DEFAULT_SOURCE_CODES)

    def test_resolve_sources_supports_explicit_none_marker(self) -> None:
        self.assertEqual(cloud_sync.resolve_sources("none"), [])
        self.assertEqual(cloud_sync.resolve_sources("off"), [])

    def test_resolve_sources_rejects_unknown_items(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知的 CLOUD_SYNC_SOURCES 来源"):
            cloud_sync.resolve_sources("qdhr,unknown-source")

    def test_validate_startup_skips_runner_loading_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "cloud_sync_last_result.json"
            with patch.object(cloud_sync, "SUMMARY_PATH", summary_path), patch.object(cloud_sync, "init_database"), patch.object(
                cloud_sync, "load_runner", side_effect=AssertionError("validate_startup should not load runners")
            ):
                result = cloud_sync.run_cloud_sync(validate_startup=True)
            self.assertTrue(summary_path.exists())
            written_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(result["selected_sources"], [])
        self.assertTrue(result["validate_startup"])
        self.assertEqual(result["results"], [])
        self.assertTrue(written_summary["validate_startup"])
        self.assertEqual(written_summary["selected_sources"], [])

    def test_explicit_empty_sources_skip_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "cloud_sync_last_result.json"
            with patch.object(cloud_sync, "SUMMARY_PATH", summary_path), patch.object(cloud_sync, "init_database"), patch.object(
                cloud_sync, "load_runner", side_effect=AssertionError("empty sources should not load runners")
            ):
                result = cloud_sync.run_cloud_sync(selected_sources=[])

        self.assertFalse(result["validate_startup"])
        self.assertEqual(result["selected_sources"], [])
        self.assertEqual(result["results"], [])


if __name__ == "__main__":
    unittest.main()