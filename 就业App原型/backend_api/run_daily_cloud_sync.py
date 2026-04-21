from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "daily_cloud_sync_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import run_browser_cloud_sync as browser_cloud_sync  # noqa: E402
import run_requests_only_cloud_sync as requests_cloud_sync  # noqa: E402
from app.core.database import get_job_market_analytics  # noqa: E402


ASSISTED_ONLY_SOURCE_CODES = ["boss_dp", "boss", "lagou"]
ANALYTICS_WARMUP_CONFIGS = [
    {
        "status": "active",
        "top_n": 12,
        "focus_source_code": "qdhr",
    }
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily cloud sync plan.")
    parser.add_argument("--requests-sources", help="Comma-separated requests-only source codes.")
    parser.add_argument("--browser-sources", help="Comma-separated browser/API source codes.")
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup and summary generation without running real crawls.",
    )
    return parser.parse_args(argv)


def emit_console(message: str) -> None:
    print(message, flush=True)


def _resolve_stage_sources(
    raw_value: str | None,
    resolver: Callable[[str | None], list[str]],
) -> list[str] | None:
    if raw_value is None:
        return None
    return resolver(raw_value)


def _collect_failures(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(summary.get("results") or []) if item.get("status") == "failed"]


def warm_job_market_analytics_cache() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for config in ANALYTICS_WARMUP_CONFIGS:
        normalized_config = {
            "status": str(config.get("status") or "active"),
            "top_n": int(config.get("top_n") or 12),
            "focus_source_code": str(config.get("focus_source_code") or "").strip().lower() or None,
        }
        try:
            result = get_job_market_analytics(**normalized_config)
            overview = dict(result.get("overview") or {})
            items.append(
                {
                    **normalized_config,
                    "status": "success",
                    "total_jobs": int(overview.get("total_jobs") or 0),
                    "total_cities": int(overview.get("total_cities") or 0),
                    "total_companies": int(overview.get("total_companies") or 0),
                }
            )
        except Exception as exc:
            items.append(
                {
                    **normalized_config,
                    "status": "failed",
                    "error": str(exc),
                }
            )
    return {
        "items": items,
        "success_count": sum(1 for item in items if item.get("status") == "success"),
        "failed_count": sum(1 for item in items if item.get("status") == "failed"),
    }


def run_daily_cloud_sync(
    requests_sources: list[str] | None = None,
    browser_sources: list[str] | None = None,
    validate_startup: bool = False,
) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    emit_console("[daily-cloud-sync] 开始执行 requests-only 日更链路")
    requests_summary = requests_cloud_sync.run_cloud_sync(
        selected_sources=requests_sources,
        validate_startup=validate_startup,
    )

    emit_console("[daily-cloud-sync] 开始执行 browser/API 日更链路")
    browser_summary = browser_cloud_sync.run_cloud_sync(
        selected_sources=browser_sources,
        validate_startup=validate_startup,
    )

    requests_failures = _collect_failures(requests_summary)
    browser_failures = _collect_failures(browser_summary)
    failed_sources = [str(item.get("source_code") or "") for item in [*requests_failures, *browser_failures] if item.get("source_code")]

    emit_console("[daily-cloud-sync] 预热全国分析快照")
    analytics_warmup = warm_job_market_analytics_cache()

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "validate_startup": bool(validate_startup),
        "overall_status": "success" if not failed_sources else "partial_failed",
        "total_fetched": int(requests_summary.get("total_fetched") or 0) + int(browser_summary.get("total_fetched") or 0),
        "total_new": int(requests_summary.get("total_new") or 0) + int(browser_summary.get("total_new") or 0),
        "total_updated": int(requests_summary.get("total_updated") or 0) + int(browser_summary.get("total_updated") or 0),
        "requests_summary": requests_summary,
        "browser_summary": browser_summary,
        "failed_sources": failed_sources,
        "analytics_warmup": analytics_warmup,
        "automation_scope": {
            "requests_only_default_sources": list(requests_cloud_sync.DEFAULT_SOURCE_CODES),
            "browser_default_sources": list(browser_cloud_sync.DEFAULT_SOURCE_CODES),
            "assisted_only_sources": list(ASSISTED_ONLY_SOURCE_CODES),
            "notes": [
                "requests_only_default_sources 和 browser_default_sources 适合挂到云端定时任务做日更。",
                "assisted_only_sources 当前不纳入默认云端日更，通常需要登录态、人工验证码处理或更稳定的浏览器上下文。",
            ],
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[daily-cloud-sync] 汇总摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requests_sources = _resolve_stage_sources(args.requests_sources, requests_cloud_sync.resolve_sources)
    browser_sources = _resolve_stage_sources(args.browser_sources, browser_cloud_sync.resolve_sources)
    result = run_daily_cloud_sync(
        requests_sources=requests_sources,
        browser_sources=browser_sources,
        validate_startup=bool(args.validate_startup),
    )
    return 1 if list(result.get("failed_sources") or []) else 0


if __name__ == "__main__":
    raise SystemExit(main())
