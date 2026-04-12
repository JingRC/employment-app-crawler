from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "weak_source_weekly_repair_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import get_job_market_analytics, init_database  # noqa: E402


DEFAULT_SOURCE_CODES = ["qdhr", "qingdao_rc", "rcsd_talents", "sdgxbys"]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}
ANALYTICS_WARMUP_CONFIGS = [
    {
        "status": "active",
        "top_n": 12,
        "focus_source_code": "qdhr",
    }
]

WEEKLY_REPAIR_PRESETS: dict[str, dict[str, Any]] = {
    "qdhr": {
        "module_name": "qdhr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 10,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 45,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "market-delivery-core",
                "queries": ["销售", "实施", "质量"],
                "cities": ["青岛"],
            },
            {
                "label": "engineering-manufacturing-core",
                "queries": ["工程师", "研发", "机械"],
                "cities": ["青岛"],
            },
            {
                "label": "testing-market-core",
                "queries": ["测试", "市场"],
                "cities": ["青岛"],
            },
            {
                "label": "data-specialist-core",
                "queries": ["数据", "专员"],
                "cities": ["青岛"],
            },
        ],
        "note": "按 qdhr 高收益词池做周更回补，优先恢复 active 样本覆盖。",
    },
    "qingdao_rc": {
        "module_name": "qingdao_rc_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "list_only",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "pm-project-core",
                "queries": ["产品经理", "项目经理"],
                "cities": ["崂山区", "市北区", "西海岸新区"],
            },
            {
                "label": "support-delivery-core",
                "queries": ["技术支持", "实施", "运维"],
                "cities": ["崂山区", "市北区", "西海岸新区", "李沧区", "即墨区"],
            },
        ],
        "note": "围绕青岛地方官方源已验证区县和高收益业务词做周更修复。",
    },
    "rcsd_talents": {
        "module_name": "rcsd_talents_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 5,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "recruitment-core",
                "queries": ["招聘"],
                "cities": ["济南", "青岛", "烟台"],
            },
            {
                "label": "young-talent-core",
                "queries": ["优青"],
                "cities": ["济南", "青岛", "烟台"],
                "max_pages": 4,
            },
        ],
        "note": "优先回补人才山东在济南、青岛、烟台的招聘和优青公告样本。",
    },
    "sdgxbys": {
        "module_name": "sdgxbys_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 6,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "technical-core",
                "queries": ["技术", "运营", "管培"],
                "cities": ["山东"],
            },
            {
                "label": "sales-production-core",
                "queries": ["销售", "生产"],
                "cities": ["山东"],
                "max_pages": 5,
            },
        ],
        "note": "围绕山东全省泛岗高收益词做周更修复，避免城市定向空跑。",
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated weekly repair sync for weak sources.")
    parser.add_argument("--sources", help="Comma-separated source codes, or 'none' to skip all sources.")
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup, summary generation, and analytics warmup without running real crawls.",
    )
    return parser.parse_args(argv)


def emit_console(message: str) -> None:
    print(message, flush=True)


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

    unknown_items = [item for item in filtered_items if item not in WEEKLY_REPAIR_PRESETS]
    if unknown_items:
        raise ValueError(f"未知的 WEAK_SOURCE_WEEKLY_REPAIR 来源: {', '.join(unknown_items)}")

    deduped_items: list[str] = []
    for item in filtered_items:
        if item not in deduped_items:
            deduped_items.append(item)
    return deduped_items


def load_runner(source_code: str):
    preset = WEEKLY_REPAIR_PRESETS[source_code]
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
    merged_dict_fields: dict[str, dict[str, str]] = {
        "resolved_city_codes": {},
        "resolved_region_codes": {},
    }
    merged_list_fields: dict[str, list[str]] = {
        "fallback_to_national_locations": [],
        "empty_result_locations": [],
        "unsupported_locations": [],
    }
    request_trace: list[dict[str, Any]] = []
    request_summary: dict[str, int] = {}

    for run_result in run_results:
        merged["total_fetched"] += int(run_result.get("total_fetched") or 0)
        merged["new_to_db"] += int(run_result.get("new_to_db") or 0)
        merged["updated"] += int(
            run_result.get("updated")
            or run_result.get("updated_in_db")
            or run_result.get("updated_count")
            or 0
        )
        merged["sub_runs"].append(run_result)

        for field_name in merged_dict_fields:
            merged_dict_fields[field_name].update(dict(run_result.get(field_name) or {}))
        for field_name in merged_list_fields:
            for item in list(run_result.get(field_name) or []):
                normalized_item = str(item or "").strip()
                if normalized_item and normalized_item not in merged_list_fields[field_name]:
                    merged_list_fields[field_name].append(normalized_item)

        request_trace.extend(list(run_result.get("request_trace") or []))
        for key, value in dict(run_result.get("request_summary") or {}).items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            request_summary[normalized_key] = int(request_summary.get(normalized_key) or 0) + int(value or 0)

    for field_name, value in merged_dict_fields.items():
        if value:
            merged[field_name] = value
    for field_name, value in merged_list_fields.items():
        if value:
            merged[field_name] = value
    if request_trace:
        merged["request_trace"] = request_trace
    if request_summary:
        merged["request_summary"] = request_summary
    return merged


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


def run_weekly_repair_sync(
    selected_sources: list[str] | None = None,
    validate_startup: bool = False,
) -> dict[str, Any]:
    emit_console("[weak-source-weekly-repair] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    resolved_sources = list(selected_sources) if selected_sources is not None else resolve_sources(None)
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0

    if validate_startup:
        emit_console("[weak-source-weekly-repair] 启动验证模式，不执行真实抓取")
        resolved_sources = []
    elif not resolved_sources:
        emit_console("[weak-source-weekly-repair] 未选择任何来源，跳过抓取")

    for source_code in resolved_sources:
        preset = WEEKLY_REPAIR_PRESETS[source_code]
        emit_console(f"[weak-source-weekly-repair] 开始执行来源: {source_code}")
        try:
            runner = load_runner(source_code)
            run_results: list[dict[str, Any]] = []
            for run_config in build_preset_runs(source_code, preset):
                emit_console(
                    f"[weak-source-weekly-repair] 执行分组: {source_code}/{run_config['label']} queries={','.join(run_config['queries'])} cities={','.join(run_config['cities'])}"
                )
                run_result = runner(
                    queries=list(run_config["queries"]),
                    cities=list(run_config["cities"]),
                    max_pages=int(run_config["max_pages"]),
                    source_options=dict(run_config["source_options"]),
                )
                run_results.append(
                    {
                        **dict(run_result),
                        "run_label": run_config["label"],
                        "run_queries": list(run_config["queries"]),
                        "run_cities": list(run_config["cities"]),
                        "run_max_pages": int(run_config["max_pages"]),
                    }
                )
            result = merge_source_results(source_code, run_results)
            source_result = {
                "source_code": source_code,
                "status": "success",
                "total_fetched": int(result.get("total_fetched", 0) or 0),
                "new_to_db": int(result.get("new_to_db", 0) or 0),
                "updated_in_db": int(result.get("updated_in_db", result.get("updated", 0)) or 0),
                "details": result,
                "note": str(preset.get("note") or ""),
            }
            emit_console(
                f"[weak-source-weekly-repair] 来源完成: {source_code} fetched={source_result['total_fetched']} new={source_result['new_to_db']} updated={source_result['updated_in_db']}"
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
            emit_console(f"[weak-source-weekly-repair] 来源失败: {source_code} error={exc}")
        results.append(source_result)
        total_fetched += int(source_result.get("total_fetched", 0) or 0)
        total_new += int(source_result.get("new_to_db", 0) or 0)
        total_updated += int(source_result.get("updated_in_db", 0) or 0)

    emit_console("[weak-source-weekly-repair] 预热全国分析快照")
    analytics_warmup = warm_job_market_analytics_cache()

    finished_at = datetime.now(timezone.utc)
    overall_status = "success" if not any(str(item.get("status") or "") == "failed" for item in results) else "partial_failed"
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "validate_startup": bool(validate_startup),
        "overall_status": overall_status,
        "task_name": "弱来源周更修复",
        "selected_sources": resolved_sources,
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "results": results,
        "analytics_warmup": analytics_warmup,
        "notes": [
            "弱来源周更修复与默认日更主链路隔离调度，不会覆盖 requests/browser 主链路的成功口径。",
            "当前默认只覆盖 qdhr、qingdao_rc、rcsd_talents、sdgxbys 这类仅历史残留或增量偏弱但仍值得周期性回补的来源。",
            "Boss 与拉勾不纳入这条周更修复链路，避免登录态、验证码或浏览器风控拖垮低频修复任务。",
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[weak-source-weekly-repair] 摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    result = run_weekly_repair_sync(selected_sources=selected_sources, validate_startup=bool(args.validate_startup))
    return 1 if any(str(item.get("status") or "") == "failed" for item in list(result.get("results") or [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())