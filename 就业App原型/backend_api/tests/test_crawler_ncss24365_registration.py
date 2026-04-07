from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.core import job_sources  # noqa: E402
from app.services import crawler_adapters  # noqa: E402


class CrawlerNCSS24365RegistrationTests(unittest.TestCase):
    def test_source_catalog_contains_ncss24365(self) -> None:
        source_info = job_sources.get_source_info("ncss24365")

        self.assertTrue(source_info["enabled"])
        self.assertEqual(source_info["platform_code"], "ncss")
        self.assertEqual(source_info["strategy"], "requests_api")

    def test_source_scripts_contains_ncss24365_script(self) -> None:
        script_path = crawler_adapters.SOURCE_SCRIPTS.get("ncss24365")

        self.assertIsNotNone(script_path)
        self.assertTrue(script_path.exists())


if __name__ == "__main__":
    unittest.main()