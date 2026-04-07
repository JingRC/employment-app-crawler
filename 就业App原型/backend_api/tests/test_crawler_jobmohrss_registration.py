from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = BACKEND_ROOT.parents[1]
for candidate in (BACKEND_ROOT, CODE_ROOT):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

from app.core.job_sources import list_source_catalog  # noqa: E402
from app.services.crawler_adapters import SOURCE_SCRIPTS  # noqa: E402


class JobMohrssRegistrationTests(unittest.TestCase):
    def test_jobmohrss_present_in_source_catalog(self) -> None:
        items = {item["source_code"]: item for item in list_source_catalog(include_disabled=True)}
        self.assertIn("jobmohrss", items)
        self.assertEqual(items["jobmohrss"]["platform_code"], "mohrss")
        self.assertTrue(items["jobmohrss"]["enabled"])

    def test_jobmohrss_script_registered(self) -> None:
        self.assertIn("jobmohrss", SOURCE_SCRIPTS)
        self.assertEqual(SOURCE_SCRIPTS["jobmohrss"].name, "jobmohrss_joblist_crawl.py")


if __name__ == "__main__":
    unittest.main()