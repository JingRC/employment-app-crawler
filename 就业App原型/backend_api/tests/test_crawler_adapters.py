from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_API_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (BACKEND_API_DIR, WORKSPACE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services import crawler_adapters  # noqa: E402


class CrawlerAdaptersTests(unittest.TestCase):
    def test_run_incremental_crawl_for_sources_preserves_source_details_for_mixed_sources(self) -> None:
        boss_module = types.SimpleNamespace(
            run_incremental_update=lambda **kwargs: {
                "total_fetched": 2,
                "new_to_db": 1,
                "boss_summary": {"trace_count": 1},
                "boss_trace": [{"query": "Java", "status": "code_37"}],
            }
        )
        shixiseng_module = types.SimpleNamespace(
            run_incremental_update=lambda **kwargs: {
                "total_fetched": 3,
                "new_to_db": 2,
                "shixiseng_summary": {"trace_count": 1},
                "shixiseng_trace": [{"query": "Test", "status": "target_pages_reached"}],
            }
        )

        with patch.object(
            crawler_adapters,
            "get_source_info",
            side_effect=lambda source_code: {"source_name": source_code, "enabled": True},
        ), patch.object(
            crawler_adapters,
            "_load_source_module",
            side_effect=lambda source_code: boss_module if source_code == "boss" else shixiseng_module,
        ):
            result = crawler_adapters.run_incremental_crawl_for_sources(
                sources=["boss", "shixiseng"],
                queries=["Java"],
                cities=["北京"],
                max_pages=2,
                page_size=30,
                runtime_mode="requests_only",
                source_options={"shixiseng": {"track": "campus"}},
            )

        self.assertEqual(result["total_fetched"], 5)
        self.assertEqual(result["new_to_db"], 3)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["source_details"]["boss"]["boss_summary"]["trace_count"], 1)
        self.assertEqual(result["source_details"]["shixiseng"]["shixiseng_summary"]["trace_count"], 1)
        self.assertEqual(result["boss_trace"][0]["status"], "code_37")
        self.assertEqual(result["shixiseng_trace"][0]["status"], "target_pages_reached")

    def test_run_incremental_crawl_for_sources_marks_disabled_source_as_skipped(self) -> None:
        with patch.object(
            crawler_adapters,
            "get_source_info",
            side_effect=lambda source_code: {"source_name": source_code, "enabled": source_code != "boss_dp", "description": "来源未启用"},
        ), patch.object(
            crawler_adapters,
            "_load_source_module",
            return_value=types.SimpleNamespace(run_incremental_update=lambda **kwargs: {"total_fetched": 1, "new_to_db": 1}),
        ):
            result = crawler_adapters.run_incremental_crawl_for_sources(
                sources=["boss_dp"],
                queries=["Java"],
                cities=["北京"],
                max_pages=1,
                page_size=30,
                runtime_mode="hybrid",
            )

        self.assertEqual(result["total_fetched"], 0)
        self.assertEqual(result["new_to_db"], 0)
        self.assertEqual(result["sources"][0]["status"], "skipped")
        self.assertEqual(result["source_details"]["boss_dp"], {})


if __name__ == "__main__":
    unittest.main()