from __future__ import annotations

import argparse
import importlib
import inspect
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
SUMMARY_PATH = DATA_DIR / "browser_cloud_sync_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import init_database  # noqa: E402


DEFAULT_SOURCE_CODES = ["zhilian", "job51", "liepin", "shixiseng", "guopin"]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}

BROWSER_CLOUD_ALWAYS_ON_CITY_GROUPS: list[dict[str, Any]] = [
    {"label": "always-on-core", "cities": ["北京", "上海", "广州", "深圳"]},
    {"label": "always-on-growth", "cities": ["杭州", "南京", "武汉", "成都"]},
]

BROWSER_CLOUD_ROTATION_WINDOW_SIZE = 2

BROWSER_CLOUD_WEEKLY_ROTATION_GROUPS: list[dict[str, Any]] = [
    {"label": "north-capitals", "cities": ["天津", "石家庄", "太原", "济南", "郑州"]},
    {"label": "northeast-capitals", "cities": ["沈阳", "长春", "哈尔滨", "呼和浩特", "银川"]},
    {"label": "central-belt", "cities": ["合肥", "南昌", "长沙", "福州", "厦门"]},
    {"label": "southwest-capitals", "cities": ["重庆", "贵阳", "昆明", "南宁", "海口"]},
    {"label": "west-capitals", "cities": ["西安", "兰州", "西宁", "乌鲁木齐", "拉萨"]},
    {"label": "public-service-belt", "cities": ["苏州", "宁波", "珠海", "东莞", "佛山"]},
]

ZHILIAN_DAILY_QUERIES = ["Java", "Python", "前端", "测试", "产品经理", "运营", "销售", "数据分析"]
JOB51_DAILY_QUERIES = ["Java", "Python", "运营", "销售"]
LIEPIN_DAILY_QUERIES = ["Java", "Python", "前端", "产品经理", "数据分析", "算法", "运营", "财务"]
SHIXISENG_DAILY_QUERIES = ["Java", "前端", "产品", "运营", "测试", "设计", "数据分析", "市场"]
GUOPIN_DAILY_QUERIES = ["软件开发", "数据分析", "财务", "行政", "管培生", "人力资源"]
ZHILIAN_PRIORITY_TASK_GROUPS: list[dict[str, Any]] = [
    {
        "label": "beijing-priority-products-sales",
        "queries": ["产品经理", "销售"],
        "cities": ["北京"],
        "max_pages": 3,
    },
    {
        "label": "beijing-priority-data-analysis",
        "queries": ["数据分析"],
        "cities": ["北京"],
        "max_pages": 2,
    },
    {
        "label": "shanghai-priority-products-sales",
        "queries": ["产品经理", "销售"],
        "cities": ["上海"],
        "max_pages": 4,
    },
    {
        "label": "shanghai-priority-data-analysis",
        "queries": ["数据分析"],
        "cities": ["上海"],
        "max_pages": 2,
    },
]


def get_week_rotation_index(reference_dt: datetime | None = None) -> int:
    cycle_length = len(BROWSER_CLOUD_WEEKLY_ROTATION_GROUPS)
    if cycle_length <= 0:
        return 0
    current_dt = reference_dt or datetime.now(timezone.utc)
    return (int(current_dt.isocalendar().week) - 1) % cycle_length


def build_browser_cloud_city_groups(reference_dt: datetime | None = None) -> list[dict[str, Any]]:
    groups = [
        {"label": str(group["label"]), "cities": list(group["cities"]), "rotation_kind": "always_on"}
        for group in BROWSER_CLOUD_ALWAYS_ON_CITY_GROUPS
    ]
    if not BROWSER_CLOUD_WEEKLY_ROTATION_GROUPS:
        return groups

    reference = reference_dt or datetime.now(timezone.utc)
    base_rotation_index = get_week_rotation_index(reference)
    cycle_length = len(BROWSER_CLOUD_WEEKLY_ROTATION_GROUPS)
    active_indices: list[int] = []
    for offset in range(max(1, int(BROWSER_CLOUD_ROTATION_WINDOW_SIZE or 1))):
        active_index = (base_rotation_index + offset) % cycle_length
        if active_index not in active_indices:
            active_indices.append(active_index)

    for active_index in active_indices:
        rotation_group = BROWSER_CLOUD_WEEKLY_ROTATION_GROUPS[active_index]
        groups.append(
            {
                "label": f"weekly-{active_index + 1:02d}-{rotation_group['label']}",
                "cities": list(rotation_group["cities"]),
                "rotation_kind": "weekly_rotation",
                "rotation_week_index": active_index,
                "rotation_seed_week": int(reference.isocalendar().week),
            }
        )
    return groups


def build_source_task_groups(queries: list[str], city_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": str(group.get("label") or "group"),
            "queries": list(queries),
            "cities": list(group.get("cities") or []),
        }
        for group in city_groups
    ]


def clone_task_groups(task_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cloned_groups: list[dict[str, Any]] = []
    for group in task_groups:
        cloned_group = {
            "label": str(group.get("label") or "group"),
            "queries": list(group.get("queries") or []),
            "cities": list(group.get("cities") or []),
        }
        if group.get("max_pages") is not None:
            cloned_group["max_pages"] = int(group["max_pages"])
        if group.get("page_size") is not None:
            cloned_group["page_size"] = int(group["page_size"])
        if group.get("runtime_mode") is not None:
            cloned_group["runtime_mode"] = str(group["runtime_mode"])
        cloned_groups.append(cloned_group)
    return cloned_groups


BROWSER_CLOUD_PRESET_TEMPLATES: dict[str, dict[str, Any]] = {
    "zhilian": {
        "module_name": "zhilian_joblist_crawl",
        "runner_name": "run_incremental_update",
        "runtime_mode": "browser",
        "page_size": 30,
        "max_pages": 2,
        "source_options": {
            "enable_request_probe": True,
            "prefer_request_pages": True,
            "probe_timeout_seconds": 8,
        },
    },
    "job51": {
        "module_name": "job51_joblist_crawl",
        "runner_name": "run_incremental_update",
        "runtime_mode": "browser",
        "page_size": 30,
        "max_pages": 1,
        "source_options": {
            "enable_request_probe": True,
            "prefer_request_pages": True,
            "probe_timeout_seconds": 8,
        },
    },
    "liepin": {
        "module_name": "liepin_joblist_crawl",
        "runner_name": "run_incremental_update",
        "runtime_mode": "browser",
        "page_size": 20,
        "max_pages": 2,
        "source_options": {
            "city_mode": "precise_if_supported",
            "enable_request_probe": True,
            "probe_timeout_seconds": 8,
        },
    },
    "shixiseng": {
        "module_name": "shixiseng_joblist_crawl",
        "runner_name": "run_incremental_update",
        "runtime_mode": "api",
        "page_size": 30,
        "max_pages": 2,
        "source_options": {
            "track": "campus",
            "detail_workers": 4,
            "detail_rate_per_second": 1.5,
            "include_campus_home_modules": True,
            "campus_hotintern_city": "推荐",
            "campus_hotcompany_industry": "推荐",
        },
        "task_groups": [
            {"label": "metro-campus", "queries": list(SHIXISENG_DAILY_QUERIES), "cities": ["北京", "上海", "深圳", "广州"]},
            {"label": "new-first-tier-campus", "queries": list(SHIXISENG_DAILY_QUERIES), "cities": ["杭州", "成都", "武汉", "南京"]},
            {"label": "regional-campus", "queries": list(SHIXISENG_DAILY_QUERIES), "cities": ["西安", "重庆", "天津", "长沙"]},
            {"label": "emerging-campus", "queries": list(SHIXISENG_DAILY_QUERIES), "cities": ["苏州", "合肥", "青岛", "郑州"]},
        ],
    },
    "guopin": {
        "module_name": "guopin_joblist_crawl",
        "runner_name": "run_incremental_update",
        "runtime_mode": "api",
        "page_size": 50,
        "max_pages": 2,
        "source_options": {
            "detail_mode": "detail_api",
            "api_page_size": 50,
            "district_targets": [],
            "use_district_targets_only": False,
            "request_timeout_seconds": 15.0,
        },
        "task_groups": [
            {"label": "east-public", "queries": list(GUOPIN_DAILY_QUERIES), "cities": ["北京", "上海", "杭州", "南京"]},
            {"label": "south-public", "queries": list(GUOPIN_DAILY_QUERIES), "cities": ["广州", "深圳", "成都", "武汉"]},
            {"label": "northwest-public", "queries": list(GUOPIN_DAILY_QUERIES), "cities": ["西安", "重庆", "天津", "长沙"]},
        ],
    },
}


def get_browser_cloud_presets(reference_dt: datetime | None = None) -> dict[str, dict[str, Any]]:
    city_groups = build_browser_cloud_city_groups(reference_dt)
    presets: dict[str, dict[str, Any]] = {}
    for source_code, template in BROWSER_CLOUD_PRESET_TEMPLATES.items():
        preset = dict(template)
        preset["source_options"] = dict(template.get("source_options") or {})
        if source_code == "zhilian":
            preset["task_groups"] = clone_task_groups(ZHILIAN_PRIORITY_TASK_GROUPS)
        elif source_code == "job51":
            preset["task_groups"] = build_source_task_groups(list(JOB51_DAILY_QUERIES), city_groups)
        elif source_code == "liepin":
            preset["task_groups"] = build_source_task_groups(list(LIEPIN_DAILY_QUERIES), city_groups)
        else:
            preset["task_groups"] = clone_task_groups(list(template.get("task_groups") or []))
        presets[source_code] = preset
    return presets


BROWSER_CLOUD_PRESETS = get_browser_cloud_presets()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run browser/API cloud sync presets.")
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

    unknown_items = [item for item in filtered_items if item not in BROWSER_CLOUD_PRESET_TEMPLATES]
    if unknown_items:
        raise ValueError(f"未知的 BROWSER_CLOUD_SOURCES 来源: {', '.join(unknown_items)}")

    deduped_items: list[str] = []
    for item in filtered_items:
        if item not in deduped_items:
            deduped_items.append(item)
    return deduped_items


def resolve_sources_from_env() -> list[str]:
    env_value = os.getenv("BROWSER_CLOUD_SOURCES")
    return resolve_sources(env_value)


def load_runner(source_code: str):
    preset = get_browser_cloud_presets()[source_code]
    module = importlib.import_module(str(preset["module_name"]))
    return getattr(module, str(preset["runner_name"]))


def build_preset_runs(source_code: str, preset: dict[str, Any]) -> list[dict[str, Any]]:
    task_groups = list(preset.get("task_groups") or [])
    if not task_groups:
        return [
            {
                "label": source_code,
                "queries": list(preset["queries"]),
                "cities": list(preset["cities"]),
                "max_pages": int(preset["max_pages"]),
                "page_size": int(preset["page_size"]),
                "runtime_mode": str(preset["runtime_mode"]),
                "source_options": dict(preset["source_options"]),
            }
        ]

    runs: list[dict[str, Any]] = []
    for index, group in enumerate(task_groups, start=1):
        runs.append(
            {
                "label": str(group.get("label") or f"{source_code}-{index}"),
                "queries": list(group.get("queries") or []),
                "cities": list(group.get("cities") or []),
                "max_pages": int(group.get("max_pages") or preset["max_pages"]),
                "page_size": int(group.get("page_size") or preset["page_size"]),
                "runtime_mode": str(group.get("runtime_mode") or preset["runtime_mode"]),
                "source_options": dict(preset["source_options"]),
            }
        )
    return runs


def merge_source_results(source_code: str, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "source_code": source_code,
        "total_fetched": 0,
        "new_to_db": 0,
        "updated": 0,
        "sub_runs": [],
    }
    for run_result in run_results:
        merged["total_fetched"] += int(run_result.get("total_fetched") or 0)
        merged["new_to_db"] += int(run_result.get("new_to_db") or 0)
        merged["updated"] += int(run_result.get("updated") or run_result.get("updated_in_db") or 0)
        merged["sub_runs"].append(run_result)
        for key, value in run_result.items():
            if key in {"total_fetched", "new_to_db", "updated", "updated_in_db", "sub_runs"}:
                continue
            merged.setdefault(key, value)
    return merged


def emit_console(message: str) -> None:
    print(message, flush=True)


def run_cloud_sync(selected_sources: list[str] | None = None, validate_startup: bool = False) -> dict[str, Any]:
    emit_console("[browser-cloud-sync] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    presets = get_browser_cloud_presets()
    active_city_groups = build_browser_cloud_city_groups()
    resolved_sources = list(selected_sources) if selected_sources is not None else resolve_sources_from_env()
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0

    if validate_startup:
        emit_console("[browser-cloud-sync] 启动验证模式，不执行真实抓取")
        resolved_sources = []
    elif not resolved_sources:
        emit_console("[browser-cloud-sync] 未选择任何来源，跳过抓取")

    for source_code in resolved_sources:
        preset = presets[source_code]
        emit_console(f"[browser-cloud-sync] 开始执行来源: {source_code}")
        try:
            runner = load_runner(source_code)
            run_results: list[dict[str, Any]] = []
            signature = None
            try:
                signature = inspect.signature(runner)
            except (TypeError, ValueError):
                signature = None
            for run_config in build_preset_runs(source_code, preset):
                emit_console(
                    f"[browser-cloud-sync] 执行分组: {source_code}/{run_config['label']} runtime={run_config['runtime_mode']} queries={','.join(run_config['queries'])} cities={','.join(run_config['cities'])}"
                )
                kwargs: dict[str, Any] = {
                    "queries": list(run_config["queries"]),
                    "cities": list(run_config["cities"]),
                    "max_pages": int(run_config["max_pages"]),
                }
                if signature is None or "page_size" in signature.parameters:
                    kwargs["page_size"] = int(run_config["page_size"])
                if signature is None or "runtime_mode" in signature.parameters:
                    kwargs["runtime_mode"] = str(run_config["runtime_mode"])
                if signature is not None and "source_options" in signature.parameters:
                    kwargs["source_options"] = dict(run_config["source_options"])

                run_result = runner(**kwargs)
                run_results.append(
                    {
                        **dict(run_result),
                        "run_label": run_config["label"],
                        "run_queries": list(run_config["queries"]),
                        "run_cities": list(run_config["cities"]),
                        "run_max_pages": int(run_config["max_pages"]),
                        "run_page_size": int(run_config["page_size"]),
                        "run_runtime_mode": str(run_config["runtime_mode"]),
                    }
                )
            result = merge_source_results(source_code, run_results)
            total_fetched += int(result.get("total_fetched") or 0)
            total_new += int(result.get("new_to_db") or 0)
            total_updated += int(result.get("updated") or 0)
            results.append(
                {
                    "source_code": source_code,
                    "status": "success",
                    "total_fetched": int(result.get("total_fetched") or 0),
                    "new_to_db": int(result.get("new_to_db") or 0),
                    "updated_in_db": int(result.get("updated") or 0),
                    "details": result,
                }
            )
            emit_console(
                f"[browser-cloud-sync] 来源完成: {source_code} fetched={result.get('total_fetched', 0)} new={result.get('new_to_db', 0)} updated={result.get('updated', 0)}"
            )
        except Exception as exc:
            emit_console(f"[browser-cloud-sync] 来源失败: {source_code} error={exc}")
            results.append(
                {
                    "source_code": source_code,
                    "status": "failed",
                    "error": str(exc),
                    "total_fetched": 0,
                    "new_to_db": 0,
                    "updated_in_db": 0,
                }
            )

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "selected_sources": resolved_sources,
        "active_city_groups": active_city_groups,
        "rotation_week_index": get_week_rotation_index(finished_at),
        "validate_startup": bool(validate_startup),
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "results": results,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[browser-cloud-sync] 摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    result = run_cloud_sync(selected_sources=selected_sources, validate_startup=bool(args.validate_startup))
    failed = [item for item in result.get("results", []) if item.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())