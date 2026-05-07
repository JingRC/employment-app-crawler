import json
from datetime import datetime
from pathlib import Path

from app.core.database import (
    create_notification,
    import_dxy_job_featured_companies,
    get_featured_company_detail,
    get_notification_stats,
    import_niuke_campus_featured_companies,
    import_yingjiesheng_featured_companies,
    get_job_detail,
    get_job_market_analytics,
    list_job_change_events,
    list_featured_companies,
    list_featured_company_filter_options,
    list_favorite_companies,
    list_favorite_jobs,
    list_job_filter_options,
    list_jobs,
    list_notifications,
    list_saved_searches,
    mark_all_notifications_read,
    mark_notification_read,
    update_saved_search,
    remove_favorite_job,
    delete_saved_search,
    restore_job_to_active,
    create_saved_search,
    save_favorite_company,
    save_favorite_job,
    verify_job_offline_status,
)


BACKEND_API_DIR = Path(__file__).resolve().parents[2]
CLOUD_SYNC_DATA_DIR = BACKEND_API_DIR / "data"
DAILY_CLOUD_SYNC_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "daily_cloud_sync_last_result.json"
REQUESTS_CLOUD_SYNC_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "cloud_sync_last_result.json"
BROWSER_CLOUD_SYNC_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "browser_cloud_sync_last_result.json"
PRIORITY_MARKET_EXPANSION_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "priority_market_expansion_last_result.json"
FOLLOWUP_MARKET_EXPANSION_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "followup_market_expansion_last_result.json"
BOSS_ASSISTED_CLOUD_SYNC_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "boss_assisted_cloud_sync_last_result.json"
WEAK_SOURCE_WEEKLY_REPAIR_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "weak_source_weekly_repair_last_result.json"
HIGH_INACTIVE_SOURCE_REPAIR_SUMMARY_PATH = CLOUD_SYNC_DATA_DIR / "high_inactive_source_repair_last_result.json"


def _load_json_summary(summary_path: Path) -> dict | None:
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "started_at": "",
            "finished_at": "",
            "results": [],
            "load_error": str(exc),
        }


def _derive_stage_status(summary: dict | None, results: list[dict]) -> str:
    if not summary:
        return "missing"
    if summary.get("load_error"):
        return "failed"
    if summary.get("overall_status"):
        return str(summary.get("overall_status") or "missing")
    if bool(summary.get("validate_startup")) and not results:
        return "validated"
    failed_count = sum(1 for item in results if str(item.get("status") or "") == "failed")
    if failed_count and failed_count == len(results):
        return "failed"
    if failed_count:
        return "partial_failed"
    if results:
        return "success"
    return "missing"


def _build_stage_summary(stage_code: str, stage_name: str, summary: dict | None) -> dict:
    if not summary:
        return {
            "stage_code": stage_code,
            "stage_name": stage_name,
            "status": "missing",
            "available": False,
            "started_at": "",
            "finished_at": "",
            "total_fetched": 0,
            "total_new": 0,
            "total_updated": 0,
            "source_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "results": [],
        }

    raw_results = list(summary.get("results") or [])
    finished_at = str(summary.get("finished_at") or "")
    normalized_results: list[dict] = []
    for item in raw_results:
        normalized_results.append(
            {
                "stage_code": stage_code,
                "stage_name": stage_name,
                "source_code": str(item.get("source_code") or ""),
                "status": str(item.get("status") or "unknown"),
                "total_fetched": int(item.get("total_fetched") or 0),
                "new_to_db": int(item.get("new_to_db") or 0),
                "updated_in_db": int(item.get("updated_in_db") or 0),
                "note": str(item.get("error") or item.get("note") or ""),
                "finished_at": finished_at,
            }
        )

    failed_count = sum(1 for item in normalized_results if item.get("status") == "failed")
    success_count = sum(1 for item in normalized_results if item.get("status") == "success")
    return {
        "stage_code": stage_code,
        "stage_name": stage_name,
        "status": _derive_stage_status(summary, normalized_results),
        "available": not bool(summary.get("load_error")) and (bool(raw_results) or bool(summary.get("finished_at")) or bool(summary.get("validate_startup"))),
        "started_at": str(summary.get("started_at") or ""),
        "finished_at": finished_at,
        "total_fetched": int(summary.get("total_fetched") or 0),
        "total_new": int(summary.get("total_new") or 0),
        "total_updated": int(summary.get("total_updated") or 0),
        "source_count": len(normalized_results),
        "success_count": success_count,
        "failed_count": failed_count,
        "results": normalized_results,
    }


def _normalize_market_expansion_result_items(summary: dict | None) -> list[dict]:
    raw_results = list((summary or {}).get("results") or [])
    finished_at = str((summary or {}).get("finished_at") or "")
    grouped: dict[str, dict] = {}

    for item in raw_results:
        phase_key = str(item.get("phase_key") or "").strip()
        raw_label = str(item.get("label") or phase_key or "扩量批次").strip()
        phase_label = raw_label.split(" / 关键词组", 1)[0].strip() or raw_label or phase_key or "扩量批次"
        group_key = phase_key or phase_label
        bucket = grouped.setdefault(
            group_key,
            {
                "phase_key": phase_key,
                "phase_label": phase_label,
                "statuses": [],
                "batch_count": 0,
                "failed_batches": 0,
                "success_batches": 0,
                "total_fetched": 0,
                "new_to_db": 0,
                "updated_in_db": 0,
                "max_attempts": 0,
                "last_message": "",
            },
        )
        status = str(item.get("status") or "unknown")
        bucket["statuses"].append(status)
        bucket["batch_count"] += 1
        if status == "failed":
            bucket["failed_batches"] += 1
        elif status == "success":
            bucket["success_batches"] += 1
        bucket["total_fetched"] += int(item.get("total_fetched") or 0)
        bucket["new_to_db"] += int(item.get("new_to_db") or 0)
        bucket["updated_in_db"] += int(item.get("updated_in_db") or 0)
        bucket["max_attempts"] = max(bucket["max_attempts"], int(item.get("attempts") or 0))
        message = str(item.get("error") or item.get("message") or "").strip()
        if message:
            bucket["last_message"] = message

    normalized_items: list[dict] = []
    for bucket in grouped.values():
        failed_batches = int(bucket["failed_batches"])
        success_batches = int(bucket["success_batches"])
        if failed_batches and success_batches:
            status = "partial_failed"
        elif failed_batches:
            status = "failed"
        elif success_batches:
            status = "success"
        else:
            status = "unknown"

        note_parts = [
            f"批次 {int(bucket['batch_count'])}",
            f"成功 {success_batches}",
            f"失败 {failed_batches}",
        ]
        if int(bucket["max_attempts"]) > 1:
            note_parts.append(f"最高重试 {int(bucket['max_attempts'])} 次")
        if str(bucket["phase_key"] or "").strip():
            note_parts.append(f"phase={str(bucket['phase_key'])}")
        if str(bucket["last_message"] or "").strip():
            note_parts.append(str(bucket["last_message"]))

        normalized_items.append(
            {
                "stage_code": "",
                "stage_name": "",
                "source_code": str(bucket["phase_label"] or bucket["phase_key"] or "扩量阶段"),
                "status": status,
                "total_fetched": int(bucket["total_fetched"]),
                "new_to_db": int(bucket["new_to_db"]),
                "updated_in_db": int(bucket["updated_in_db"]),
                "note": " / ".join(note_parts),
                "finished_at": finished_at,
            }
        )

    normalized_items.sort(key=lambda item: (0 if item.get("status") == "failed" else 1, -int(item.get("new_to_db") or 0), str(item.get("source_code") or "")))
    return normalized_items


def _build_market_expansion_stage_summary(stage_code: str, stage_name: str, summary: dict | None) -> dict:
    if not summary:
        return _build_stage_summary(stage_code, stage_name, summary)

    normalized_results = _normalize_market_expansion_result_items(summary)
    for item in normalized_results:
        item["stage_code"] = stage_code
        item["stage_name"] = stage_name

    if summary.get("load_error"):
        status = "failed"
    elif summary.get("blocked_by_status"):
        status = "failed"
    elif bool(summary.get("dry_run")) and not normalized_results:
        status = "validated"
    else:
        status = _derive_stage_status(summary, normalized_results)

    failed_count = sum(1 for item in normalized_results if item.get("status") in {"failed", "partial_failed"})
    success_count = sum(1 for item in normalized_results if item.get("status") == "success")
    return {
        "stage_code": stage_code,
        "stage_name": stage_name,
        "status": status,
        "available": not bool(summary.get("load_error")) and (bool(summary.get("results")) or bool(summary.get("finished_at")) or bool(summary.get("dry_run")) or bool(summary.get("blocked_by_status"))),
        "started_at": str(summary.get("started_at") or ""),
        "finished_at": str(summary.get("finished_at") or ""),
        "total_fetched": int(summary.get("total_fetched") or 0),
        "total_new": int(summary.get("total_new") or 0),
        "total_updated": int(summary.get("total_updated") or 0),
        "source_count": len(normalized_results),
        "success_count": success_count,
        "failed_count": failed_count,
        "results": normalized_results,
    }


def query_jobs(
    keyword: str | None,
    city_name: str | None,
    internship_only: bool,
    source_code: str | None,
    status: str | None,
    offline_verification_status: str | None,
    salary_min_k: float | None,
    salary_max_k: float | None,
    degree_text: str | None,
    experience_text: str | None,
    sort_by: str | None,
    page: int,
    page_size: int,
) -> dict:
    return list_jobs(
        keyword=keyword,
        city_name=city_name,
        internship_only=internship_only,
        source_code=source_code,
        status=status,
        offline_verification_status=offline_verification_status,
        salary_min_k=salary_min_k,
        salary_max_k=salary_max_k,
        degree_text=degree_text,
        experience_text=experience_text,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )


def query_job_filter_options(
    status: str | None = "active",
    offline_verification_status: str | None = None,
) -> dict:
    return list_job_filter_options(status=status, offline_verification_status=offline_verification_status)


def query_job_market_analytics(
    status: str | None = "active",
    top_n: int = 12,
    focus_source_code: str | None = None,
) -> dict:
    return get_job_market_analytics(
        status=status,
        top_n=top_n,
        focus_source_code=focus_source_code,
        refresh_stale=False,
    )


def query_cloud_sync_dashboard() -> dict:
    daily_summary = _load_json_summary(DAILY_CLOUD_SYNC_SUMMARY_PATH)
    requests_summary = None
    browser_summary = None
    priority_market_expansion_summary = _load_json_summary(PRIORITY_MARKET_EXPANSION_SUMMARY_PATH)
    followup_market_expansion_summary = _load_json_summary(FOLLOWUP_MARKET_EXPANSION_SUMMARY_PATH)
    if daily_summary:
        nested_requests = daily_summary.get("requests_summary")
        nested_browser = daily_summary.get("browser_summary")
        requests_summary = nested_requests if isinstance(nested_requests, dict) else None
        browser_summary = nested_browser if isinstance(nested_browser, dict) else None
    if requests_summary is None:
        requests_summary = _load_json_summary(REQUESTS_CLOUD_SYNC_SUMMARY_PATH)
    if browser_summary is None:
        browser_summary = _load_json_summary(BROWSER_CLOUD_SYNC_SUMMARY_PATH)
    boss_assisted_summary = _load_json_summary(BOSS_ASSISTED_CLOUD_SYNC_SUMMARY_PATH)
    weak_source_weekly_repair_summary = _load_json_summary(WEAK_SOURCE_WEEKLY_REPAIR_SUMMARY_PATH)
    high_inactive_source_repair_summary = _load_json_summary(HIGH_INACTIVE_SOURCE_REPAIR_SUMMARY_PATH)

    stage_summaries = [
        _build_stage_summary("requests", "Requests-only 日更", requests_summary),
        _build_stage_summary("browser", "Browser/API 日更", browser_summary),
    ]
    if priority_market_expansion_summary:
        stage_summaries.append(
            _build_market_expansion_stage_summary("market_expansion_priority", "全国整合扩量 · 第一波主平台", priority_market_expansion_summary)
        )
    if followup_market_expansion_summary:
        stage_summaries.append(
            _build_market_expansion_stage_summary("market_expansion_followup", "全国整合扩量 · 第二波官方与垂直源", followup_market_expansion_summary)
        )
    if weak_source_weekly_repair_summary:
        stage_summaries.append(_build_stage_summary("weak_source_weekly_repair", "弱来源周更修复", weak_source_weekly_repair_summary))
    if high_inactive_source_repair_summary:
        stage_summaries.append(_build_stage_summary("high_inactive_source_repair", "高下架来源专项修复", high_inactive_source_repair_summary))
    stage_summaries.append(_build_stage_summary("boss_assisted", "Boss 辅助任务", boss_assisted_summary))
    source_results: list[dict] = []
    for stage_summary in stage_summaries:
        source_results.extend(list(stage_summary.get("results") or []))
    source_results.sort(
        key=lambda item: (
            0 if str(item.get("status") or "") == "failed" else 1,
            str(item.get("stage_code") or ""),
            str(item.get("source_code") or ""),
        )
    )

    automation_scope = daily_summary.get("automation_scope") if isinstance(daily_summary, dict) else {}
    automation_notes = list((automation_scope or {}).get("notes") or [])
    if weak_source_weekly_repair_summary:
        for note in list((weak_source_weekly_repair_summary or {}).get("notes") or []):
            normalized_note = str(note or "").strip()
            if normalized_note and normalized_note not in automation_notes:
                automation_notes.append(normalized_note)
    if high_inactive_source_repair_summary:
        for note in list((high_inactive_source_repair_summary or {}).get("notes") or []):
            normalized_note = str(note or "").strip()
            if normalized_note and normalized_note not in automation_notes:
                automation_notes.append(normalized_note)
    if priority_market_expansion_summary or followup_market_expansion_summary:
        expansion_note = "全国整合扩量会逐批调用 crawler 增量接口，每批仍沿用 stale_after_hours 与强校验逻辑，因此会同步做下架检测与待确认岗位复核。"
        if expansion_note not in automation_notes:
            automation_notes.append(expansion_note)
    if boss_assisted_summary:
        boss_note = "Boss 辅助任务与默认日更主链路隔离调度，失败不会阻塞 requests/browser 主链路。"
        if boss_note not in automation_notes:
            automation_notes.append(boss_note)

    return {
        "latest_daily_status": str((daily_summary or {}).get("overall_status") or (daily_summary or {}).get("status") or "missing"),
        "latest_daily_finished_at": str((daily_summary or {}).get("finished_at") or ""),
        "latest_daily_total_fetched": int((daily_summary or {}).get("total_fetched") or 0),
        "latest_daily_total_new": int((daily_summary or {}).get("total_new") or 0),
        "latest_daily_total_updated": int((daily_summary or {}).get("total_updated") or 0),
        "failed_sources": [str(item) for item in list((daily_summary or {}).get("failed_sources") or []) if str(item)],
        "automation_notes": automation_notes,
        "assisted_only_sources": [str(item) for item in list((automation_scope or {}).get("assisted_only_sources") or []) if str(item)],
        "stage_summaries": stage_summaries,
        "source_results": source_results,
    }


def query_job_detail(job_id: int) -> dict | None:
    return get_job_detail(job_id)


def manually_verify_job(job_id: int, action_source: str = "manual") -> dict | None:
    detail = verify_job_offline_status(job_id)
    if detail is None:
        return None

    title = f"已手动复核岗位：{detail.get('title', '')}"
    content = (
        f"{detail.get('company_name', '')} / {detail.get('title', '')}，"
        f"复核结果：{detail.get('offline_verification_reason', '') or detail.get('offline_verification_status', '')}"
    )
    create_notification(
        notification_type="job_batch_verify" if action_source == "batch" else "job_manual_verify",
        title=title,
        content=content,
        related_job_id=int(detail.get("job_id") or 0) or None,
        related_company_id=int(detail.get("company_id") or 0) or None,
    )
    return detail


def manually_restore_job(job_id: int, action_source: str = "manual") -> dict | None:
    detail = restore_job_to_active(job_id)
    if detail is None:
        return None

    title = f"已人工恢复岗位：{detail.get('title', '')}"
    content = f"{detail.get('company_name', '')} / {detail.get('title', '')} 已从回收站恢复到在库列表"
    create_notification(
        notification_type="job_batch_restore" if action_source == "batch" else "job_manual_restore",
        title=title,
        content=content,
        related_job_id=int(detail.get("job_id") or 0) or None,
        related_company_id=int(detail.get("company_id") or 0) or None,
    )
    return detail


def create_favorite_company(company_id: int, company_name: str) -> dict:
    return save_favorite_company(company_id=company_id, company_name=company_name)


def query_favorite_companies(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    return list_favorite_companies(keyword=keyword, page=page, page_size=page_size)


def create_favorite_job(job_id: int) -> dict | None:
    return save_favorite_job(job_id=job_id)


def query_favorite_jobs(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    return list_favorite_jobs(keyword=keyword, page=page, page_size=page_size)


def delete_favorite_job(job_id: int) -> bool:
    return remove_favorite_job(job_id=job_id)


def create_saved_search_subscription(
    keyword: str = "",
    city_name: str = "",
    filters: dict | None = None,
    enabled: bool = True,
    notify_frequency: str = "daily",
) -> dict:
    return create_saved_search(
        keyword=keyword,
        city_name=city_name,
        filters=filters,
        enabled=enabled,
        notify_frequency=notify_frequency,
    )


def query_saved_searches(keyword: str | None = None, page: int = 1, page_size: int = 10) -> dict:
    return list_saved_searches(keyword=keyword, page=page, page_size=page_size)


def patch_saved_search_subscription(
    search_id: int,
    *,
    enabled: bool | None = None,
    notify_frequency: str | None = None,
    keyword: str | None = None,
    city_name: str | None = None,
    filters: dict | None = None,
) -> dict | None:
    return update_saved_search(
        search_id,
        enabled=enabled,
        notify_frequency=notify_frequency,
        keyword=keyword,
        city_name=city_name,
        filters=filters,
    )


def remove_saved_search_subscription(search_id: int) -> bool:
    return delete_saved_search(search_id)


def query_featured_companies(
    keyword: str | None = None,
    board_code: str | None = None,
    company_type: str | None = None,
    group_name: str | None = None,
    city_name: str | None = None,
    industry: str | None = None,
    module_name: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    return list_featured_companies(
        keyword=keyword,
        board_code=board_code,
        company_type=company_type,
        group_name=group_name,
        city_name=city_name,
        industry=industry,
        module_name=module_name,
        page=page,
        page_size=page_size,
    )


def query_featured_company_filter_options() -> dict:
    return list_featured_company_filter_options()


def query_featured_company_detail(featured_company_id: int, jobs_limit: int = 20) -> dict | None:
    return get_featured_company_detail(featured_company_id=featured_company_id, jobs_limit=jobs_limit)


def import_niuke_campus_featured_topics() -> dict:
    return import_niuke_campus_featured_companies()


def import_yingjiesheng_featured_topics() -> dict:
    return import_yingjiesheng_featured_companies()


def import_dxy_job_featured_topics() -> dict:
    return import_dxy_job_featured_companies()


def query_notifications(
    page: int,
    page_size: int,
    notification_type: str | None = None,
    action_source: str | None = None,
    unread_only: bool = False,
    related_job_id: int | None = None,
) -> dict:
    return list_notifications(
        page=page,
        page_size=page_size,
        notification_type=notification_type,
        action_source=action_source,
        unread_only=unread_only,
        related_job_id=related_job_id,
    )


def _parse_timeline_created_at(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.min


def query_job_notification_timeline(job_id: int, limit: int = 20) -> dict:
    result = list_notifications(
        page=1,
        page_size=max(int(limit or 20), 1),
        related_job_id=job_id,
    )
    events = list_job_change_events(job_id=job_id, limit=limit)
    items = list(result.get("items") or [])
    timeline = [
        {
            "entry_kind": "notification",
            "created_at": str(item.get("created_at") or ""),
            "title": str(item.get("title") or ""),
            "content": str(item.get("content") or ""),
            "notification_type": str(item.get("notification_type") or ""),
            "action_source": str(item.get("action_source") or ""),
            "action_source_name": str(item.get("action_source_name") or ""),
            "event_type": "",
            "source_code": "",
            "source_name": "",
            "is_read": bool(item.get("is_read")),
        }
        for item in items
    ]
    timeline.extend(
        {
            "entry_kind": "event",
            "created_at": str(event.get("created_at") or ""),
            "title": str(event.get("change_summary") or ""),
            "content": str(event.get("change_summary") or ""),
            "notification_type": "",
            "action_source": "",
            "action_source_name": "",
            "event_type": str(event.get("event_type") or ""),
            "source_code": str(event.get("source_code") or ""),
            "source_name": str(event.get("source_name") or ""),
            "is_read": False,
        }
        for event in events
    )
    timeline.sort(
        key=lambda item: (_parse_timeline_created_at(str(item.get("created_at") or "")), str(item.get("entry_kind") or "")),
        reverse=True,
    )
    return {"items": items, "events": events, "timeline": timeline}


def set_notification_read(notification_id: int) -> bool:
    return mark_notification_read(notification_id)


def set_all_notifications_read() -> int:
    return mark_all_notifications_read()


def query_notification_stats() -> dict:
    return get_notification_stats()


def add_notification(
    notification_type: str,
    title: str,
    content: str,
    related_job_id: int | None = None,
    related_company_id: int | None = None,
) -> dict:
    return create_notification(
        notification_type=notification_type,
        title=title,
        content=content,
        related_job_id=related_job_id,
        related_company_id=related_company_id,
    )


def batch_verify_jobs(job_ids: list[int]) -> dict:
    normalized_job_ids = []
    seen: set[int] = set()
    for job_id in job_ids:
        normalized = int(job_id)
        if normalized <= 0 or normalized in seen:
            continue
        seen.add(normalized)
        normalized_job_ids.append(normalized)

    items = []
    failed_job_ids = []
    restored_count = 0
    for job_id in normalized_job_ids:
        detail = manually_verify_job(job_id, action_source="batch")
        if detail is None:
            failed_job_ids.append(job_id)
            continue
        if str(detail.get("status") or "") == "active":
            restored_count += 1
        items.append(detail)

    return {
        "requested_count": len(normalized_job_ids),
        "success_count": len(items),
        "failed_count": len(failed_job_ids),
        "restored_count": restored_count,
        "items": items,
        "failed_job_ids": failed_job_ids,
    }


def batch_restore_jobs(job_ids: list[int]) -> dict:
    normalized_job_ids = []
    seen: set[int] = set()
    for job_id in job_ids:
        normalized = int(job_id)
        if normalized <= 0 or normalized in seen:
            continue
        seen.add(normalized)
        normalized_job_ids.append(normalized)

    items = []
    failed_job_ids = []
    for job_id in normalized_job_ids:
        detail = manually_restore_job(job_id, action_source="batch")
        if detail is None:
            failed_job_ids.append(job_id)
            continue
        items.append(detail)

    return {
        "requested_count": len(normalized_job_ids),
        "success_count": len(items),
        "failed_count": len(failed_job_ids),
        "restored_count": len(items),
        "items": items,
        "failed_job_ids": failed_job_ids,
    }
