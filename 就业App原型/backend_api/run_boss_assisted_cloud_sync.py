from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "boss_assisted_cloud_sync_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import init_database  # noqa: E402
import zhipin_dp_crawl_v2 as boss_dp_crawl  # noqa: E402


DEFAULT_QUERIES = ["Java", "Python", "前端", "测试"]
DEFAULT_CITIES = ["北京", "上海", "青岛", "济南", "杭州", "深圳"]
DEFAULT_SOURCE_OPTIONS = {
    "browser_preference": "chrome",
    "browser_profile": "Default",
    "use_system_profile": False,
    "conservative_first_round": True,
    "first_round_page_cap": 1,
    "auto_expand_after_stable": True,
    "homepage_warmup_seconds": 8,
    "result_page_warmup_seconds": 6,
    "defer_high_risk_pairs": True,
    "high_risk_pairs": ["Java@北京"],
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated Boss assisted cloud sync.")
    parser.add_argument("--queries", help="Comma-separated Boss queries.")
    parser.add_argument("--cities", help="Comma-separated Boss cities.")
    parser.add_argument("--validate-startup", action="store_true", help="Only validate startup and summary writing.")
    return parser.parse_args(argv)


def emit_console(message: str) -> None:
    print(message, flush=True)


def parse_csv_list(raw: str | None, defaults: list[str]) -> list[str]:
    if raw is None:
        return list(defaults)
    items = [item.strip() for item in str(raw).replace("\n", ",").split(",") if item.strip()]
    return items or list(defaults)


def run_boss_assisted_cloud_sync(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    validate_startup: bool = False,
) -> dict[str, Any]:
    emit_console("[boss-assisted-cloud-sync] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    selected_queries = list(queries) if queries is not None else list(DEFAULT_QUERIES)
    selected_cities = list(cities) if cities is not None else list(DEFAULT_CITIES)
    started_at = datetime.now(timezone.utc)

    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0
    overall_status = "success"

    if validate_startup:
        emit_console("[boss-assisted-cloud-sync] 启动验证模式，不执行真实抓取")
        selected_queries = []
        selected_cities = []
    else:
        emit_console("[boss-assisted-cloud-sync] 开始执行 Boss 辅助任务")
        try:
            result = boss_dp_crawl.run_incremental_update(
                queries=list(selected_queries),
                cities=list(selected_cities),
                max_pages=1,
                page_size=30,
                runtime_mode="browser",
                source_options=dict(DEFAULT_SOURCE_OPTIONS),
            )
            total_fetched = int(result.get("total_fetched") or 0)
            total_new = int(result.get("new_to_db") or 0)
            total_updated = sum(int(item.get("updated_count") or 0) for item in list(result.get("boss_dp_trace") or []))
            results.append(
                {
                    "source_code": "boss_dp",
                    "status": "success",
                    "total_fetched": total_fetched,
                    "new_to_db": total_new,
                    "updated_in_db": total_updated,
                    "details": result,
                    "note": "Boss 辅助型浏览器任务已独立执行。",
                }
            )
            emit_console(
                f"[boss-assisted-cloud-sync] 来源完成: boss_dp fetched={total_fetched} new={total_new} updated={total_updated}"
            )
        except Exception as exc:
            overall_status = "failed"
            results.append(
                {
                    "source_code": "boss_dp",
                    "status": "failed",
                    "error": str(exc),
                    "total_fetched": 0,
                    "new_to_db": 0,
                    "updated_in_db": 0,
                }
            )
            emit_console(f"[boss-assisted-cloud-sync] 来源失败: boss_dp error={exc}")

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "validate_startup": bool(validate_startup),
        "overall_status": overall_status,
        "task_name": "Boss 辅助型云任务",
        "selected_queries": selected_queries,
        "selected_cities": selected_cities,
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "results": results,
        "notes": [
            "Boss 辅助型云任务与默认日更主链路隔离调度。",
            "若 Boss 触发验证码、风控或浏览器环境异常，只影响本任务，不影响默认 requests/browser 日更。",
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[boss-assisted-cloud-sync] 摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_boss_assisted_cloud_sync(
        queries=parse_csv_list(args.queries, DEFAULT_QUERIES),
        cities=parse_csv_list(args.cities, DEFAULT_CITIES),
        validate_startup=bool(args.validate_startup),
    )
    return 1 if any(str(item.get("status") or "") == "failed" for item in list(result.get("results") or [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
