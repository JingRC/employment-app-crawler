from app.core.database import (
    create_notification,
    get_featured_company_detail,
    get_job_detail,
    get_job_market_analytics,
    list_featured_companies,
    list_featured_company_filter_options,
    list_favorite_companies,
    list_job_filter_options,
    list_jobs,
    list_notifications,
    mark_notification_read,
    restore_job_to_active,
    save_favorite_company,
    verify_job_offline_status,
)


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


def query_job_notification_timeline(job_id: int, limit: int = 20) -> dict:
    result = list_notifications(
        page=1,
        page_size=max(int(limit or 20), 1),
        related_job_id=job_id,
    )
    return {"items": list(result.get("items") or [])}


def set_notification_read(notification_id: int) -> bool:
    return mark_notification_read(notification_id)


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
