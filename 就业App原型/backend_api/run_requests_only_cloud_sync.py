from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "cloud_sync_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import init_database  # noqa: E402


DEFAULT_SOURCE_CODES = ["qdhr", "sdgxbys", "ncss24365", "jobmohrss"]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}


REQUESTS_ONLY_PRESETS: dict[str, dict[str, Any]] = {
    "qdhr": {
        "module_name": "qdhr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": ["销售", "实施", "质量", "工程师"],
        "cities": ["青岛"],
        "max_pages": 8,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 45,
            "sleep_seconds": 0.0,
        },
    },
    "sdgxbys": {
        "module_name": "sdgxbys_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": ["招聘", "运营", "工程师", "销售"],
        "cities": ["山东", "青岛", "济南"],
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
    },
    "ncss24365": {
        "module_name": "ncss24365_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": ["Java", "Python", "前端"],
        "cities": ["全国", "青岛", "济南", "北京", "上海"],
        "max_pages": 2,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
        },
    },
    "jobmohrss": {
        "module_name": "jobmohrss_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": ["Java", "Python", "前端"],
        "cities": ["全国", "青岛", "济南", "北京", "上海"],
        "max_pages": 2,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
            "search_type": "2",
        },
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run requests-only cloud sync presets.")
    parser.add_argument("--sources", help="Comma-separated source codes, or 'none' to skip all sources.")
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup, database initialization, and summary writing without running any source.",
    )
    return parser.parse_args(argv)


def resolve_sources(raw: str | None = None) -> list[str]:
    if raw is None:
        return list(DEFAULT_SOURCE_CODES)

    normalized_raw = str(raw).replace("\n", ",")
    items = [item.strip().lower() for item in normalized_raw.split(",")]
    filtered_items = [item for item in items if item]
    if not filtered_items:
        return []
    if any(item in DISABLED_SOURCE_MARKERS for item in filtered_items):
        return []

    unknown_items = [item for item in filtered_items if item not in REQUESTS_ONLY_PRESETS]
    if unknown_items:
        raise ValueError(f"未知的 CLOUD_SYNC_SOURCES 来源: {', '.join(unknown_items)}")

    deduped_items: list[str] = []
    for item in filtered_items:
        if item not in deduped_items:
            deduped_items.append(item)
    return deduped_items


def resolve_sources_from_env() -> list[str]:
    env_value = os.getenv("CLOUD_SYNC_SOURCES")
    return resolve_sources(env_value)


def load_runner(source_code: str):
    preset = REQUESTS_ONLY_PRESETS[source_code]
    module = importlib.import_module(str(preset["module_name"]))
    return getattr(module, str(preset["runner_name"]))


def emit_console(message: str) -> None:
    print(message, flush=True)


def run_cloud_sync(selected_sources: list[str] | None = None, validate_startup: bool = False) -> dict[str, Any]:
    emit_console("[cloud-sync] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    resolved_sources = list(selected_sources) if selected_sources is not None else resolve_sources_from_env()
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0

    if validate_startup:
        emit_console("[cloud-sync] 启动验证模式，不执行真实抓取")
        resolved_sources = []
    elif not resolved_sources:
        emit_console("[cloud-sync] 未选择任何来源，跳过抓取")

    for source_code in resolved_sources:
        preset = REQUESTS_ONLY_PRESETS[source_code]
        emit_console(f"[cloud-sync] 开始执行来源: {source_code}")
        try:
            runner = load_runner(source_code)
            result = runner(
                queries=list(preset["queries"]),
                cities=list(preset["cities"]),
                max_pages=int(preset["max_pages"]),
                source_options=dict(preset["source_options"]),
            )
            source_result = {
                "source_code": source_code,
                "status": "success",
                "total_fetched": int(result.get("total_fetched", 0) or 0),
                "new_to_db": int(result.get("new_to_db", 0) or 0),
                "updated_in_db": int(result.get("updated_in_db", 0) or 0),
                "details": result,
            }
            emit_console(
                f"[cloud-sync] 来源完成: {source_code} fetched={source_result['total_fetched']} new={source_result['new_to_db']} updated={source_result['updated_in_db']}"
            )
        except Exception as exc:
            source_result = {
                "source_code": source_code,
                "status": "failed",
                "error": str(exc),
                "total_fetched": 0,
                "new_to_db": 0,
                "updated_in_db": 0,
            }
            emit_console(f"[cloud-sync] 来源失败: {source_code} error={exc}")
        results.append(source_result)
        total_fetched += int(source_result.get("total_fetched", 0) or 0)
        total_new += int(source_result.get("new_to_db", 0) or 0)
        total_updated += int(source_result.get("updated_in_db", 0) or 0)

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "selected_sources": resolved_sources,
        "validate_startup": bool(validate_startup),
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "results": results,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[cloud-sync] 摘要已写入: {SUMMARY_PATH}")
    return summary


if __name__ == "__main__":
    args = parse_args()
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    result = run_cloud_sync(selected_sources=selected_sources, validate_startup=bool(args.validate_startup))
    print(json.dumps(result, ensure_ascii=False, indent=2))