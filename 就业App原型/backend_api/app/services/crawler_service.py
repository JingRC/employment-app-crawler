from __future__ import annotations

import threading
import traceback
from datetime import datetime
from typing import Any

from app.core.database import (
    get_app_state_value,
    mark_stale_jobs_inactive,
    set_app_state_value,
    set_job_stale_hours,
    verify_pending_inactive_jobs,
    verify_recent_active_jobs_safely,
)
from app.services.crawler_adapters import run_incremental_crawl_for_sources


class CrawlCancelledError(Exception):
    pass

_DEFAULT_STATUS: dict[str, Any] = {
    "task_id": "",
    "status": "idle",
    "is_running": False,
    "message": "尚未开始增量更新",
    "started_at": "",
    "finished_at": "",
    "cancel_requested": False,
    "config": {},
    "last_result": {},
    "error": "",
    "current_city_name": "",
    "current_query": "",
    "logs": [],
    "recent_tasks": [],
}
_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = dict(_DEFAULT_STATUS)
_CANCEL_EVENT = threading.Event()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time_text(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _copy_status() -> dict[str, Any]:
    with _STATUS_LOCK:
        return {
            **_STATUS,
            "config": dict(_STATUS.get("config", {})),
            "last_result": dict(_STATUS.get("last_result", {})),
            "logs": list(_STATUS.get("logs", [])),
            "recent_tasks": list(_STATUS.get("recent_tasks", [])),
        }


def _update_status(**kwargs: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(kwargs)


def _append_log(
    message: str,
    *,
    city_name: str = "",
    query: str = "",
    page: int = 0,
    source_code: str = "",
    branch: str = "",
    branch_label: str = "",
    debug_snapshot_path: str = "",
) -> None:
    with _STATUS_LOCK:
        logs = list(_STATUS.get("logs", []))
        logs.append(
            {
                "timestamp": _now_text(),
                "message": message,
                "city_name": city_name,
                "query": query,
                "page": page,
                "source_code": source_code,
                "branch": branch,
                "branch_label": branch_label,
                "debug_snapshot_path": debug_snapshot_path,
            }
        )
        _STATUS["logs"] = logs[-30:]
        if city_name:
            _STATUS["current_city_name"] = city_name
        if query:
            _STATUS["current_query"] = query


def _push_recent_task(item: dict[str, Any]) -> None:
    with _STATUS_LOCK:
        recent_tasks = list(_STATUS.get("recent_tasks", []))
        recent_tasks.insert(0, item)
        _STATUS["recent_tasks"] = recent_tasks[:8]


def _snapshot_logs() -> list[dict[str, Any]]:
    with _STATUS_LOCK:
        return list(_STATUS.get("logs", []))


def get_crawl_status() -> dict[str, Any]:
    return _copy_status()


def cancel_incremental_crawl() -> dict[str, Any]:
    current = _copy_status()
    if not current["is_running"]:
        return current

    _CANCEL_EVENT.set()
    _update_status(
        status="cancelling",
        cancel_requested=True,
        message="已发送取消请求，等待当前步骤安全退出",
    )
    _append_log("收到前端取消请求")
    return _copy_status()


def start_safe_verify_task(
    *,
    limit: int,
    timeout_seconds: float,
    recent_active_hours: int,
    cooldown_hours: int = 12,
    auto_only: bool = False,
) -> dict[str, Any]:
    current = _copy_status()
    if current["is_running"]:
        return current

    normalized_cooldown_hours = max(int(cooldown_hours or 12), 1)
    last_finished_at = _parse_time_text(get_app_state_value("safe_verify_last_finished_at", ""))
    if auto_only and last_finished_at is not None:
        elapsed_seconds = (datetime.now() - last_finished_at).total_seconds()
        cooldown_seconds = normalized_cooldown_hours * 3600
        if elapsed_seconds < cooldown_seconds:
            return {
                **current,
                "message": f"慢速安全校验未到触发窗口，距下次自动校验还需约 {max(int((cooldown_seconds - elapsed_seconds) / 3600), 0)} 小时",
                "config": {
                    "task_kind": "safe_verify",
                    "cooldown_hours": normalized_cooldown_hours,
                    "auto_only": True,
                },
                "last_result": {
                    **dict(current.get("last_result", {})),
                    "task_kind": "safe_verify",
                    "auto_skipped": True,
                    "cooldown_hours": normalized_cooldown_hours,
                    "last_finished_at": last_finished_at.strftime("%Y-%m-%d %H:%M:%S"),
                },
            }

    _CANCEL_EVENT.clear()
    task_id = datetime.now().strftime("safe-verify-%Y%m%d-%H%M%S")
    config = {
        "task_kind": "safe_verify",
        "limit": max(int(limit or 0), 1),
        "timeout_seconds": max(float(timeout_seconds or 1.0), 1.0),
        "recent_active_hours": max(int(recent_active_hours or 1), 1),
        "cooldown_hours": normalized_cooldown_hours,
        "auto_only": bool(auto_only),
    }
    _update_status(
        task_id=task_id,
        status="running",
        is_running=True,
        message=("正在执行启动后慢速安全校验" if auto_only else "正在执行慢速安全校验"),
        started_at=_now_text(),
        finished_at="",
        cancel_requested=False,
        config=config,
        last_result={},
        error="",
        current_city_name="",
        current_query="",
        logs=[],
    )
    _append_log("慢速安全校验任务已创建，等待后台执行")
    worker = threading.Thread(
        target=_run_safe_verify_task,
        args=(task_id, config),
        daemon=True,
        name=task_id,
    )
    worker.start()
    return _copy_status()


def start_incremental_crawl(
    sources: list[str],
    queries: list[str],
    cities: list[str],
    max_pages: int,
    page_size: int,
    runtime_mode: str,
    stale_after_hours: int = 72,
    source_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = _copy_status()
    if current["is_running"]:
        return current

    _CANCEL_EVENT.clear()

    task_id = datetime.now().strftime("crawl-%Y%m%d-%H%M%S")
    config = {
        "task_kind": "incremental",
        "sources": sources,
        "queries": queries,
        "cities": cities,
        "max_pages": max_pages,
        "page_size": page_size,
        "runtime_mode": runtime_mode,
        "stale_after_hours": max(int(stale_after_hours or 72), 1),
        "source_options": dict(source_options or {}),
    }
    _update_status(
        task_id=task_id,
        status="running",
        is_running=True,
        message=f"增量更新进行中：{len(cities)} 个城市，{len(queries)} 个关键词",
        started_at=_now_text(),
        finished_at="",
        cancel_requested=False,
        config=config,
        last_result={},
        error="",
        current_city_name="",
        current_query="",
        logs=[],
    )
    _append_log("任务已创建，等待后台执行")

    worker = threading.Thread(
        target=_run_incremental_crawl,
        args=(task_id, config),
        daemon=True,
        name=task_id,
    )
    worker.start()
    return _copy_status()


def _run_safe_verify_task(task_id: str, config: dict[str, Any]) -> None:
    try:
        _append_log("慢速安全校验后台线程已启动")
        stats = verify_recent_active_jobs_safely(
            limit=int(config.get("limit") or 12),
            timeout_seconds=float(config.get("timeout_seconds") or 6.0),
            recent_active_hours=int(config.get("recent_active_hours") or 24 * 14),
        )
        result = {
            "task_kind": "safe_verify",
            **stats,
        }
        finished_at = _now_text()
        set_app_state_value("safe_verify_last_finished_at", finished_at)
        completion_message = (
            f"慢速安全校验完成：校验 {int(stats.get('checked_count', 0))} 条"
            f"，确认下架 {int(stats.get('confirmed_offline_count', 0))} 条"
            f"，仍在线 {int(stats.get('still_online_count', 0))} 条"
        )
        _update_status(
            task_id=task_id,
            status="success",
            is_running=False,
            message=completion_message,
            finished_at=finished_at,
            cancel_requested=False,
            last_result=result,
            error="",
        )
        _append_log(completion_message)
        final_status = _copy_status()
        _push_recent_task(
            {
                "task_id": task_id,
                "status": "success",
                "message": final_status["message"],
                "started_at": final_status["started_at"],
                "finished_at": final_status["finished_at"],
                "config": config,
                "result": result,
                "logs": _snapshot_logs(),
            }
        )
    except Exception as exc:
        _update_status(
            task_id=task_id,
            status="failed",
            is_running=False,
            message="慢速安全校验失败",
            finished_at=_now_text(),
            cancel_requested=False,
            error=f"{exc}\n{traceback.format_exc(limit=8)}",
            last_result={"task_kind": "safe_verify"},
        )
        _append_log(f"慢速安全校验失败: {exc}")
        failure_status = _copy_status()
        _push_recent_task(
            {
                "task_id": task_id,
                "status": "failed",
                "message": failure_status["message"],
                "started_at": failure_status["started_at"],
                "finished_at": failure_status["finished_at"],
                "config": config,
                "result": dict(failure_status.get("last_result", {})),
                "logs": _snapshot_logs(),
            }
        )


def _run_incremental_crawl(task_id: str, config: dict[str, Any]) -> None:
    try:
        _append_log("后台线程已启动")

        def progress_callback(message: str, context: dict[str, Any]) -> None:
            _append_log(
                message,
                city_name=str(context.get("city_name") or ""),
                query=str(context.get("query") or ""),
                page=int(context.get("page") or 0),
                source_code=str(context.get("source_code") or ""),
                branch=str(context.get("branch") or ""),
                branch_label=str(context.get("branch_label") or ""),
                debug_snapshot_path=str(context.get("debug_snapshot_path") or ""),
            )

        def should_stop_callback() -> bool:
            return _CANCEL_EVENT.is_set()

        result = run_incremental_crawl_for_sources(
            sources=list(config.get("sources") or ["boss_dp"]),
            queries=config["queries"],
            cities=config["cities"],
            max_pages=config["max_pages"],
            page_size=config["page_size"],
            runtime_mode=config["runtime_mode"],
            source_options=dict(config.get("source_options") or {}),
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
        )
        stale_after_hours = max(int(config.get("stale_after_hours") or 72), 1)
        set_job_stale_hours(stale_after_hours)
        offline_stats = mark_stale_jobs_inactive(stale_after_hours=stale_after_hours)
        strong_check_stats = verify_pending_inactive_jobs(source_codes=list(config.get("sources") or []))
        if isinstance(result, dict):
            result.update(offline_stats)
            result.update(
                {
                    "offline_verified_count": int(strong_check_stats.get("verified_count", 0)),
                    "offline_restored_count": int(strong_check_stats.get("restored_count", 0)),
                    "offline_confirmed_count": int(strong_check_stats.get("confirmed_count", 0)),
                    "offline_review_count": int(strong_check_stats.get("review_count", 0)),
                    "offline_missing_url_count": int(strong_check_stats.get("missing_url_count", 0)),
                    "offline_strong_check_limit": int(strong_check_stats.get("limit", 0)),
                    "offline_strong_check_timeout_seconds": float(strong_check_stats.get("timeout_seconds", 0.0)),
                    "offline_strong_check_sources": list(strong_check_stats.get("selected_sources") or []),
                }
            )
        inactive_marked = int(offline_stats.get("inactive_marked", 0))
        restored_count = int(strong_check_stats.get("restored_count", 0))
        failed_sources = int(result.get("failed_sources", 0)) if isinstance(result, dict) else 0
        success_sources = int(result.get("success_sources", 0)) if isinstance(result, dict) else 0
        completion_status = "success"
        completion_message = f"增量更新完成：新增 {int(result.get('new_to_db', 0))} 条，抓取 {int(result.get('total_fetched', 0))} 条"
        if inactive_marked > 0:
            completion_message += f"，检测下架 {inactive_marked} 条"
        if restored_count > 0:
            completion_message += f"，强校验恢复 {restored_count} 条"
        if failed_sources > 0:
            completion_message += f"，失败来源 {failed_sources} 个"
            if success_sources <= 0 and int(result.get("total_fetched", 0)) <= 0:
                completion_status = "failed"
                completion_message = f"增量更新失败：{failed_sources} 个来源执行失败"
        failure_summary = "；".join((result.get("source_failure_messages") or [])[:5]) if isinstance(result, dict) else ""
        _update_status(
            task_id=task_id,
            status=completion_status,
            is_running=False,
            message=completion_message,
            finished_at=_now_text(),
            cancel_requested=False,
            last_result=result if isinstance(result, dict) else {},
            error=failure_summary,
        )
        _append_log("任务执行完成")
        if failed_sources > 0:
            _append_log(f"来源执行失败汇总：{failure_summary or failed_sources}")
        if inactive_marked > 0:
            _append_log(
                f"岗位下架检测完成：标记 {inactive_marked} 条为 inactive",
            )
        if int(strong_check_stats.get("verified_count", 0)) > 0:
            _append_log(
                "岗位下架强校验完成："
                f"校验 {int(strong_check_stats.get('verified_count', 0))} 条 / "
                f"恢复 {int(strong_check_stats.get('restored_count', 0))} 条 / "
                f"确认下架 {int(strong_check_stats.get('confirmed_count', 0))} 条 / "
                f"待人工复核 {int(strong_check_stats.get('review_count', 0))} 条 / "
                f"缺少链接 {int(strong_check_stats.get('missing_url_count', 0))} 条"
            )
        final_status = _copy_status()
        _push_recent_task(
            {
                "task_id": task_id,
                "status": completion_status,
                "message": final_status["message"],
                "started_at": final_status["started_at"],
                "finished_at": final_status["finished_at"],
                "config": config,
                "result": result if isinstance(result, dict) else {},
                "logs": _snapshot_logs(),
            }
        )
    except Exception as exc:
        if exc.__class__.__name__ == "CrawlCancelledError":
            _update_status(
                task_id=task_id,
                status="cancelled",
                is_running=False,
                message="增量更新已取消",
                finished_at=_now_text(),
                cancel_requested=False,
                error="",
            )
            _append_log("任务已取消")
            cancelled_status = _copy_status()
            _push_recent_task(
                {
                    "task_id": task_id,
                    "status": "cancelled",
                    "message": cancelled_status["message"],
                    "started_at": cancelled_status["started_at"],
                    "finished_at": cancelled_status["finished_at"],
                    "config": config,
                    "result": dict(cancelled_status.get("last_result", {})),
                    "logs": _snapshot_logs(),
                }
            )
            return
        _update_status(
            task_id=task_id,
            status="failed",
            is_running=False,
            message="增量更新失败",
            finished_at=_now_text(),
            cancel_requested=False,
            error=f"{exc}\n{traceback.format_exc(limit=8)}",
        )
        _append_log(f"任务执行失败: {exc}")
        failure_status = _copy_status()
        _push_recent_task(
            {
                "task_id": task_id,
                "status": "failed",
                "message": failure_status["message"],
                "started_at": failure_status["started_at"],
                "finished_at": failure_status["finished_at"],
                "config": config,
                "result": {},
                "logs": _snapshot_logs(),
            }
        )
    finally:
        _CANCEL_EVENT.clear()
