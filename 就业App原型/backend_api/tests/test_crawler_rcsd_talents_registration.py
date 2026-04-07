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

from app.core.job_sources import get_source_info  # noqa: E402
from app.services.crawler_adapters import SOURCE_SCRIPTS  # noqa: E402


class RcsdTalentsRegistrationTests(unittest.TestCase):
    def test_source_catalog_contains_rcsd_talents(self) -> None:
        source_info = get_source_info("rcsd_talents")

        self.assertTrue(source_info["enabled"])
        self.assertEqual(source_info["platform_code"], "rcsd")
        self.assertEqual(source_info["strategy"], "requests_html")

    def test_source_scripts_contains_rcsd_talents_script(self) -> None:
        script_path = SOURCE_SCRIPTS.get("rcsd_talents")

        self.assertIsNotNone(script_path)
        self.assertTrue(script_path.exists())


if __name__ == "__main__":
    unittest.main()