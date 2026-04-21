from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "high_inactive_source_repair_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import run_browser_cloud_sync as browser_cloud_sync  # noqa: E402
import run_requests_only_cloud_sync as requests_cloud_sync  # noqa: E402
from app.core import database as database_core  # noqa: E402
from app.core.job_sources import get_source_name  # noqa: E402


get_job_market_analytics = database_core.get_job_market_analytics
init_database = database_core.init_database
verify_pending_inactive_jobs = database_core.verify_pending_inactive_jobs


DEFAULT_SOURCE_CODES = ["job51", "ncss24365", "zhilian"]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}
DEFAULT_AUTO_SELECT_COUNT = 3
DEFAULT_VERIFY_TIMEOUT_SECONDS = 8.0

JOB51_HIGH_INACTIVE_TASK_GROUPS: list[dict[str, Any]] = [
    {
        "label": "metro-tech-core",
        "queries": ["Java", "Python", "前端", "测试"],
        "cities": ["北京", "上海", "广州", "深圳"],
        "max_pages": 2,
    },
    {
        "label": "metro-business-core",
        "queries": ["运营", "销售", "财务", "人事"],
        "cities": ["北京", "上海", "广州", "深圳"],
        "max_pages": 2,
    },
    {
        "label": "growth-tech-core",
        "queries": ["Java", "前端", "测试"],
        "cities": ["杭州", "南京", "武汉", "成都"],
        "max_pages": 2,
    },
    {
        "label": "growth-business-core",
        "queries": ["运营", "销售", "行政"],
        "cities": ["杭州", "南京", "武汉", "成都"],
        "max_pages": 2,
    },
    {
        "label": "regional-east-tech",
        "queries": ["Java", "Python", "前端", "测试"],
        "cities": ["苏州", "宁波", "青岛", "济南"],
        "max_pages": 2,
    },
    {
        "label": "regional-central-business",
        "queries": ["运营", "销售", "行政", "管培生"],
        "cities": ["郑州", "长沙", "重庆", "西安"],
        "max_pages": 2,
    },
    {
        "label": "growth-trainee-tail",
        "queries": ["管培生"],
        "cities": ["杭州", "南京", "武汉", "成都"],
        "max_pages": 1,
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run targeted repair for high inactive sources.")
    parser.add_argument("--sources", help="Comma-separated source codes, or 'none' to skip all sources.")
    parser.add_argument(
        "--auto-select-count",
        type=int,
        default=DEFAULT_AUTO_SELECT_COUNT,
        help="When --sources is omitted, auto-select up to this many sources with the highest pending inactive volume.",
    )
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup, summary generation, and analytics warmup without running real crawls.",
    )
    parser.add_argument(
        "--group-offset",
        type=int,
        default=0,
        help="Skip this many task groups before executing selected source runs.",
    )
    parser.add_argument(
        "--group-limit",
        type=int,
        help="Only execute up to this many task groups after label and offset filtering.",
    )
    parser.add_argument(
        "--group-labels",
        help="Comma-separated task-group labels to include before applying offset and limit.",
    )
    return parser.parse_args(argv)


def emit_console(message: str) -> None:
    print(message, flush=True)


def parse_group_labels(raw: str | None = None) -> list[str] | None:
    if raw is None:
        return None

    normalized_raw = str(raw).replace("\n", ",")
    labels = [item.strip() for item in normalized_raw.split(",") if item.strip()]
    return labels or None


def _clone_task_groups(task_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _select_task_groups(
    source_code: str,
    task_groups: list[dict[str, Any]],
    group_offset: int = 0,
    group_limit: int | None = None,
    group_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_offset = max(int(group_offset or 0), 0)
    normalized_limit = None if group_limit is None else int(group_limit)
    if normalized_limit is not None and normalized_limit < 1:
        raise ValueError("--group-limit 必须大于等于 1")

    available_labels = [str(group.get("label") or "").strip() for group in task_groups]
    selected_groups = list(task_groups)

    if group_labels:
        requested_labels = [label.strip() for label in group_labels if str(label).strip()]
        requested_label_set = {label.lower() for label in requested_labels}
        available_label_set = {label.lower() for label in available_labels if label}
        missing_labels = [label for label in requested_labels if label.lower() not in available_label_set]
        if missing_labels:
            raise ValueError(f"来源 {source_code} 未找到 task group: {', '.join(missing_labels)}")
        selected_groups = [
            group
            for group in task_groups
            if str(group.get("label") or "").strip().lower() in requested_label_set
        ]

    if normalized_offset:
        selected_groups = selected_groups[normalized_offset:]
    if normalized_limit is not None:
        selected_groups = selected_groups[:normalized_limit]

    if not selected_groups:
        available_text = ", ".join(label for label in available_labels if label) or "无"
        raise ValueError(f"来源 {source_code} 在当前分组选项下没有可执行分组；可选分组: {available_text}")
    return selected_groups


def _get_callable_parameter_names(func: Any) -> set[str]:
    try:
        return set(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return set()


def _normalize_source_codes(source_codes: list[str] | None = None) -> list[str]:
    normalized: list[str] = []
    for item in list(source_codes or []):
        source_code = str(item or "").strip().lower()
        if source_code and source_code not in normalized:
            normalized.append(source_code)
    return normalized


def _safe_summarize_pending_inactive_sources(
    limit: int = 10,
    source_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    summarize_func = getattr(database_core, "summarize_pending_inactive_sources", None)
    if callable(summarize_func):
        return list(summarize_func(limit=limit, source_codes=source_codes))

    normalized_limit = max(int(limit or 0), 0)
    normalized_source_codes = _normalize_source_codes(source_codes)
    if normalized_limit == 0:
        return []
    if source_codes is not None and not normalized_source_codes:
        return []

    where_clauses = [
        "status = 'inactive'",
        "COALESCE(offline_verification_status, '') = 'pending'",
    ]
    params: list[Any] = []
    if normalized_source_codes:
        placeholders = ", ".join(["?"] * len(normalized_source_codes))
        where_clauses.append(f"COALESCE(LOWER(source_code), '') IN ({placeholders})")
        params.extend(normalized_source_codes)

    with database_core.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(source_code, '') AS source_code,
                   COUNT(1) AS pending_count,
                   MIN(COALESCE(last_seen_at, '')) AS oldest_last_seen_at,
                   MAX(COALESCE(last_seen_at, '')) AS latest_last_seen_at
            FROM jobs
            WHERE {' AND '.join(where_clauses)}
            GROUP BY COALESCE(source_code, '')
            ORDER BY pending_count DESC, oldest_last_seen_at ASC, source_code ASC
            LIMIT ?
            """,
            (*params, normalized_limit),
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        source_code = str(row["source_code"] or "").strip().lower()
        if not source_code:
            continue
        items.append(
            {
                "source_code": source_code,
                "source_name": get_source_name(source_code),
                "pending_count": int(row["pending_count"] or 0),
                "oldest_last_seen_at": str(row["oldest_last_seen_at"] or ""),
                "latest_last_seen_at": str(row["latest_last_seen_at"] or ""),
            }
        )
    return items


def _merge_requests_source_results(source_code: str, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "source_code": source_code,
        "total_fetched": 0,
        "new_to_db": 0,
        "updated": 0,
        "sub_runs": [],
    }
    resolved_city_codes: dict[str, str] = {}
    fallback_locations: list[str] = []
    empty_locations: list[str] = []
    request_trace: list[dict[str, Any]] = []
    request_summary = {
        "total_targets": 0,
        "resolved_targets": 0,
        "fallback_targets": 0,
        "empty_targets": 0,
    }

    for run_result in run_results:
        merged["total_fetched"] += int(run_result.get("total_fetched") or 0)
        merged["new_to_db"] += int(run_result.get("new_to_db") or 0)
        merged["updated"] += int(run_result.get("updated") or run_result.get("updated_in_db") or 0)
        merged["sub_runs"].append(run_result)
        resolved_city_codes.update(dict(run_result.get("resolved_city_codes") or {}))
        for city in list(run_result.get("fallback_to_national_locations") or []):
            if city not in fallback_locations:
                fallback_locations.append(city)
        for city in list(run_result.get("empty_result_locations") or []):
            if city not in empty_locations:
                empty_locations.append(city)
        request_trace.extend(list(run_result.get("request_trace") or []))
        summary = dict(run_result.get("request_summary") or {})
        for key in request_summary:
            request_summary[key] += int(summary.get(key) or 0)

    if resolved_city_codes:
        merged["resolved_city_codes"] = resolved_city_codes
    if fallback_locations:
        merged["fallback_to_national_locations"] = fallback_locations
    if empty_locations:
        merged["empty_result_locations"] = empty_locations
    if request_trace:
        merged["request_trace"] = request_trace
        merged["request_summary"] = request_summary
    return merged


def _safe_merge_source_results(source_code: str, preset: dict[str, Any], run_results: list[dict[str, Any]]) -> dict[str, Any]:
    if str(preset.get("stage_code") or "") == "browser":
        return browser_cloud_sync.merge_source_results(source_code, run_results)

    merge_func = getattr(requests_cloud_sync, "merge_source_results", None)
    if callable(merge_func):
        return merge_func(source_code, run_results)
    return _merge_requests_source_results(source_code, run_results)


def _safe_get_job_market_analytics(**kwargs: Any) -> dict[str, Any]:
    if "refresh_stale" not in _get_callable_parameter_names(get_job_market_analytics):
        kwargs.pop("refresh_stale", None)
    return get_job_market_analytics(**kwargs)


def _safe_verify_pending_inactive_jobs(
    limit: int = 0,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
    source_codes: list[str] | None = None,
) -> dict[str, Any]:
    normalized_limit = max(int(limit or 0), 0)
    normalized_timeout = max(float(timeout_seconds or DEFAULT_VERIFY_TIMEOUT_SECONDS), 1.0)
    normalized_source_codes = _normalize_source_codes(source_codes)
    stats = {
        "verified_count": 0,
        "restored_count": 0,
        "confirmed_count": 0,
        "review_count": 0,
        "missing_url_count": 0,
        "limit": normalized_limit,
        "timeout_seconds": normalized_timeout,
    }
    if source_codes is not None:
        stats["selected_sources"] = list(normalized_source_codes)
    if normalized_limit == 0:
        return stats
    if source_codes is not None and not normalized_source_codes:
        return stats

    verify_params = _get_callable_parameter_names(verify_pending_inactive_jobs)
    if "source_codes" in verify_params:
        return verify_pending_inactive_jobs(
            limit=normalized_limit,
            timeout_seconds=normalized_timeout,
            source_codes=normalized_source_codes,
        )

    strong_verify_func = getattr(database_core, "_strong_verify_job_url", None)
    if not callable(strong_verify_func):
        return verify_pending_inactive_jobs(limit=normalized_limit, timeout_seconds=normalized_timeout)

    with database_core.get_connection() as conn:
        where_clauses = [
            "status = 'inactive'",
            "COALESCE(offline_verification_status, '') = 'pending'",
        ]
        params: list[Any] = []
        if normalized_source_codes:
            placeholders = ", ".join(["?"] * len(normalized_source_codes))
            where_clauses.append(f"COALESCE(LOWER(source_code), '') IN ({placeholders})")
            params.extend(normalized_source_codes)

        pending_rows = conn.execute(
            f"""
            SELECT id, source_url, official_apply_url
            FROM jobs
            WHERE {' AND '.join(where_clauses)}
            ORDER BY last_seen_at ASC, id ASC
            LIMIT ?
            """,
            (*params, normalized_limit),
        ).fetchall()
        if not pending_rows:
            return stats

        verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in pending_rows:
            candidate_url = str(row["official_apply_url"] or row["source_url"] or "")
            verification = strong_verify_func(candidate_url, normalized_timeout)
            verification_status = str(verification.get("verification_status") or "needs_review")
            verification_reason = str(verification.get("verification_reason") or "")
            stats["verified_count"] += 1

            if verification_status == "rechecked_online":
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'active',
                        last_seen_at = CURRENT_TIMESTAMP,
                        offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                stats["restored_count"] += 1
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                if verification_status == "confirmed_offline":
                    stats["confirmed_count"] += 1
                elif verification_status == "missing_url":
                    stats["missing_url_count"] += 1
                else:
                    stats["review_count"] += 1

        conn.commit()
    return stats


def get_high_inactive_repair_presets(reference_dt: datetime | None = None) -> dict[str, dict[str, Any]]:
    browser_presets = browser_cloud_sync.get_browser_cloud_presets(reference_dt)
    ncss24365_preset = dict(requests_cloud_sync.REQUESTS_ONLY_PRESETS["ncss24365"])
    job51_preset = dict(browser_presets["job51"])
    zhilian_preset = dict(browser_presets["zhilian"])

    return {
        "job51": {
            "stage_code": "browser",
            "stage_name": "Browser/API 修复",
            "module_name": str(job51_preset["module_name"]),
            "runner_name": str(job51_preset["runner_name"]),
            "runtime_mode": str(job51_preset["runtime_mode"]),
            "page_size": int(job51_preset["page_size"]),
            "max_pages": 2,
            "source_options": dict(job51_preset.get("source_options") or {}),
            "task_groups": _clone_task_groups(JOB51_HIGH_INACTIVE_TASK_GROUPS),
            "verify_limit": 48,
            "verify_timeout_seconds": 8.0,
            "note": "围绕 51job 高下架大户做更宽覆盖的专项回补，并在来源内优先批量复核 pending inactive。",
        },
        "ncss24365": {
            "stage_code": "requests",
            "stage_name": "Requests-only 修复",
            "module_name": str(ncss24365_preset["module_name"]),
            "runner_name": str(ncss24365_preset["runner_name"]),
            "max_pages": int(ncss24365_preset["max_pages"]),
            "source_options": dict(ncss24365_preset.get("source_options") or {}),
            "task_groups": _clone_task_groups(list(ncss24365_preset.get("task_groups") or [])),
            "verify_limit": 48,
            "verify_timeout_seconds": 8.0,
            "note": "围绕 24365 校招全国分组回补，并优先复核该来源的历史 pending inactive。",
        },
        "zhilian": {
            "stage_code": "browser",
            "stage_name": "Browser/API 修复",
            "module_name": str(zhilian_preset["module_name"]),
            "runner_name": str(zhilian_preset["runner_name"]),
            "runtime_mode": str(zhilian_preset["runtime_mode"]),
            "page_size": int(zhilian_preset["page_size"]),
            "max_pages": int(zhilian_preset["max_pages"]),
            "source_options": dict(zhilian_preset.get("source_options") or {}),
            "task_groups": _clone_task_groups(list(zhilian_preset.get("task_groups") or [])),
            "verify_limit": 18,
            "verify_timeout_seconds": 8.0,
            "note": "围绕智联已验证的京沪高收益分组回补，并补上该来源的批量待复核校验。",
        },
    }


def resolve_sources(raw: str | None = None) -> list[str]:
    presets = get_high_inactive_repair_presets()
    if raw is None:
        return list(DEFAULT_SOURCE_CODES)

    normalized_raw = str(raw).replace("\n", ",")
    items = [item.strip().lower() for item in normalized_raw.split(",")]
    filtered_items = [item for item in items if item]
    if not filtered_items:
        return []
    if any(item in DISABLED_SOURCE_MARKERS for item in filtered_items):
        return []

    unknown_items = [item for item in filtered_items if item not in presets]
    if unknown_items:
        raise ValueError(f"未知的 HIGH_INACTIVE_REPAIR 来源: {', '.join(unknown_items)}")

    deduped_items: list[str] = []
    for item in filtered_items:
        if item not in deduped_items:
            deduped_items.append(item)
    return deduped_items


def select_high_inactive_sources(
    auto_select_count: int = DEFAULT_AUTO_SELECT_COUNT,
    candidate_source_codes: list[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    normalized_count = max(int(auto_select_count or DEFAULT_AUTO_SELECT_COUNT), 1)
    candidates = list(candidate_source_codes or DEFAULT_SOURCE_CODES)
    snapshot = _safe_summarize_pending_inactive_sources(limit=max(normalized_count, len(candidates)), source_codes=candidates)
    selected_sources = [str(item.get("source_code") or "") for item in snapshot if str(item.get("source_code") or "")]
    for source_code in candidates:
        if len(selected_sources) >= normalized_count:
            break
        if source_code not in selected_sources:
            selected_sources.append(source_code)
    return selected_sources[:normalized_count], snapshot


def load_runner(source_code: str, preset: dict[str, Any]):
    module = importlib.import_module(str(preset["module_name"]))
    return getattr(module, str(preset["runner_name"]))


def build_preset_runs(
    source_code: str,
    preset: dict[str, Any],
    group_offset: int = 0,
    group_limit: int | None = None,
    group_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    task_groups = list(preset.get("task_groups") or [])
    base_run = {
        "max_pages": int(preset.get("max_pages") or 1),
        "source_options": dict(preset.get("source_options") or {}),
    }
    if preset.get("page_size") is not None:
        base_run["page_size"] = int(preset["page_size"])
    if preset.get("runtime_mode") is not None:
        base_run["runtime_mode"] = str(preset["runtime_mode"])

    if not task_groups:
        if max(int(group_offset or 0), 0) > 0 or group_limit is not None or group_labels:
            raise ValueError(f"来源 {source_code} 当前预设没有 task_groups，不能使用分组选项")
        return [
            {
                "label": source_code,
                "queries": list(preset.get("queries") or []),
                "cities": list(preset.get("cities") or []),
                **base_run,
            }
        ]

    runs: list[dict[str, Any]] = []
    selected_task_groups = _select_task_groups(
        source_code,
        task_groups,
        group_offset=group_offset,
        group_limit=group_limit,
        group_labels=group_labels,
    )
    for index, group in enumerate(selected_task_groups, start=1):
        run = {
            "label": str(group.get("label") or f"{source_code}-{index}"),
            "queries": list(group.get("queries") or []),
            "cities": list(group.get("cities") or []),
            "max_pages": int(group.get("max_pages") or base_run["max_pages"]),
            "source_options": dict(base_run["source_options"]),
        }
        if base_run.get("page_size") is not None:
            run["page_size"] = int(group.get("page_size") or base_run["page_size"])
        if base_run.get("runtime_mode") is not None:
            run["runtime_mode"] = str(group.get("runtime_mode") or base_run["runtime_mode"])
        runs.append(run)
    return runs


def merge_source_results(source_code: str, preset: dict[str, Any], run_results: list[dict[str, Any]]) -> dict[str, Any]:
    return _safe_merge_source_results(source_code, preset, run_results)


def warm_job_market_analytics_cache(selected_sources: list[str] | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    configs = [{"status": "active", "top_n": 12, "focus_source_code": None}]
    for source_code in list(selected_sources or DEFAULT_SOURCE_CODES)[:3]:
        configs.append({"status": "active", "top_n": 12, "focus_source_code": source_code})

    for config in configs:
        normalized_config = {
            "status": str(config.get("status") or "active"),
            "top_n": int(config.get("top_n") or 12),
            "focus_source_code": str(config.get("focus_source_code") or "").strip().lower() or None,
        }
        try:
            result = _safe_get_job_market_analytics(**normalized_config, refresh_stale=False)
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


def run_high_inactive_source_repair(
    selected_sources: list[str] | None = None,
    auto_select_count: int = DEFAULT_AUTO_SELECT_COUNT,
    validate_startup: bool = False,
    group_offset: int = 0,
    group_limit: int | None = None,
    group_labels: list[str] | None = None,
) -> dict[str, Any]:
    emit_console("[high-inactive-source-repair] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    normalized_group_offset = max(int(group_offset or 0), 0)
    normalized_group_limit = None if group_limit is None else int(group_limit)
    normalized_group_labels = list(group_labels or [])

    presets = get_high_inactive_repair_presets()
    auto_selected = selected_sources is None
    if auto_selected:
        resolved_sources, pending_source_snapshot = select_high_inactive_sources(
            auto_select_count=auto_select_count,
            candidate_source_codes=list(presets.keys()),
        )
    else:
        resolved_sources = list(selected_sources or [])
        pending_source_snapshot = _safe_summarize_pending_inactive_sources(
            limit=max(len(resolved_sources), 1),
            source_codes=resolved_sources,
        )

    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0
    total_verified = 0
    total_restored = 0
    total_confirmed = 0
    total_review = 0
    total_missing_url = 0

    if validate_startup:
        emit_console("[high-inactive-source-repair] 启动验证模式，不执行真实抓取")
        resolved_sources = []
    elif not resolved_sources:
        emit_console("[high-inactive-source-repair] 未选择任何来源，跳过抓取")

    for source_code in resolved_sources:
        preset = presets[source_code]
        emit_console(f"[high-inactive-source-repair] 开始执行来源: {source_code}")
        try:
            runner = load_runner(source_code, preset)
            try:
                signature = inspect.signature(runner)
            except (TypeError, ValueError):
                signature = None

            run_results: list[dict[str, Any]] = []
            selected_runs = build_preset_runs(
                source_code,
                preset,
                group_offset=normalized_group_offset,
                group_limit=normalized_group_limit,
                group_labels=normalized_group_labels,
            )
            for run_config in selected_runs:
                emit_console(
                    f"[high-inactive-source-repair] 执行分组: {source_code}/{run_config['label']} queries={','.join(run_config['queries'])} cities={','.join(run_config['cities'])}"
                )
                kwargs: dict[str, Any] = {
                    "queries": list(run_config["queries"]),
                    "cities": list(run_config["cities"]),
                    "max_pages": int(run_config["max_pages"]),
                }
                if run_config.get("page_size") is not None and (signature is None or "page_size" in signature.parameters):
                    kwargs["page_size"] = int(run_config["page_size"])
                if run_config.get("runtime_mode") is not None and (signature is None or "runtime_mode" in signature.parameters):
                    kwargs["runtime_mode"] = str(run_config["runtime_mode"])
                if signature is None or "source_options" in signature.parameters:
                    kwargs["source_options"] = dict(run_config.get("source_options") or {})

                run_result = runner(**kwargs)
                normalized_run_result = {
                    **dict(run_result),
                    "run_label": run_config["label"],
                    "run_queries": list(run_config["queries"]),
                    "run_cities": list(run_config["cities"]),
                    "run_max_pages": int(run_config["max_pages"]),
                }
                if run_config.get("page_size") is not None:
                    normalized_run_result["run_page_size"] = int(run_config["page_size"])
                if run_config.get("runtime_mode") is not None:
                    normalized_run_result["run_runtime_mode"] = str(run_config["runtime_mode"])
                run_results.append(normalized_run_result)

            merged_result = merge_source_results(source_code, preset, run_results)
            verify_stats = _safe_verify_pending_inactive_jobs(
                limit=int(preset.get("verify_limit") or 0),
                timeout_seconds=float(preset.get("verify_timeout_seconds") or DEFAULT_VERIFY_TIMEOUT_SECONDS),
                source_codes=[source_code],
            )

            source_result = {
                "source_code": source_code,
                "source_name": get_source_name(source_code),
                "stage_code": str(preset.get("stage_code") or ""),
                "stage_name": str(preset.get("stage_name") or ""),
                "status": "success",
                "total_fetched": int(merged_result.get("total_fetched") or 0),
                "new_to_db": int(merged_result.get("new_to_db") or 0),
                "updated_in_db": int(merged_result.get("updated_in_db", merged_result.get("updated", 0)) or 0),
                "verified_count": int(verify_stats.get("verified_count") or 0),
                "restored_count": int(verify_stats.get("restored_count") or 0),
                "confirmed_count": int(verify_stats.get("confirmed_count") or 0),
                "review_count": int(verify_stats.get("review_count") or 0),
                "missing_url_count": int(verify_stats.get("missing_url_count") or 0),
                "details": {
                    **merged_result,
                    "selected_group_labels": [str(run.get("run_label") or "") for run in run_results],
                    "offline_verification": verify_stats,
                },
                "note": str(preset.get("note") or ""),
            }
            emit_console(
                "[high-inactive-source-repair] 来源完成: "
                f"{source_code} fetched={source_result['total_fetched']} new={source_result['new_to_db']} "
                f"updated={source_result['updated_in_db']} verified={source_result['verified_count']} "
                f"restored={source_result['restored_count']}"
            )
        except Exception as exc:
            source_result = {
                "source_code": source_code,
                "source_name": get_source_name(source_code),
                "stage_code": str(preset.get("stage_code") or ""),
                "stage_name": str(preset.get("stage_name") or ""),
                "status": "failed",
                "error": str(exc),
                "total_fetched": 0,
                "new_to_db": 0,
                "updated_in_db": 0,
                "verified_count": 0,
                "restored_count": 0,
                "confirmed_count": 0,
                "review_count": 0,
                "missing_url_count": 0,
            }
            emit_console(f"[high-inactive-source-repair] 来源失败: {source_code} error={exc}")

        results.append(source_result)
        total_fetched += int(source_result.get("total_fetched") or 0)
        total_new += int(source_result.get("new_to_db") or 0)
        total_updated += int(source_result.get("updated_in_db") or 0)
        total_verified += int(source_result.get("verified_count") or 0)
        total_restored += int(source_result.get("restored_count") or 0)
        total_confirmed += int(source_result.get("confirmed_count") or 0)
        total_review += int(source_result.get("review_count") or 0)
        total_missing_url += int(source_result.get("missing_url_count") or 0)

    emit_console("[high-inactive-source-repair] 预热分析快照")
    analytics_warmup = warm_job_market_analytics_cache(resolved_sources)

    finished_at = datetime.now(timezone.utc)
    overall_status = "success" if not any(str(item.get("status") or "") == "failed" for item in results) else "partial_failed"
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "validate_startup": bool(validate_startup),
        "overall_status": overall_status,
        "task_name": "高下架来源专项修复",
        "auto_selected": auto_selected,
        "selected_sources": resolved_sources,
        "group_selection": {
            "group_offset": normalized_group_offset,
            "group_limit": normalized_group_limit,
            "group_labels": normalized_group_labels,
        },
        "pending_source_snapshot": pending_source_snapshot,
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "total_verified": total_verified,
        "total_restored": total_restored,
        "total_confirmed": total_confirmed,
        "total_review": total_review,
        "total_missing_url": total_missing_url,
        "results": results,
        "analytics_warmup": analytics_warmup,
        "notes": [
            "该链路专门针对 pending inactive 体量较大的来源做专项回补，不覆盖默认 requests/browser 日更摘要。",
            "每个来源抓取完成后会立即按 source_code 批量强校验 pending inactive，避免全局 oldest 策略长期轮不到下架大户。",
            "当前默认候选来源为 job51、ncss24365、zhilian；未显式传 --sources 时，会优先按 pending inactive 数量自动挑选。",
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[high-inactive-source-repair] 摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    group_labels = parse_group_labels(args.group_labels)
    result = run_high_inactive_source_repair(
        selected_sources=selected_sources,
        auto_select_count=max(int(args.auto_select_count or DEFAULT_AUTO_SELECT_COUNT), 1),
        validate_startup=bool(args.validate_startup),
        group_offset=max(int(args.group_offset or 0), 0),
        group_limit=args.group_limit,
        group_labels=group_labels,
    )
    return 1 if any(str(item.get("status") or "") == "failed" for item in list(result.get("results") or [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())