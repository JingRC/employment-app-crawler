from __future__ import annotations

import inspect
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

from app.core.job_sources import get_source_info, list_source_catalog

CODE_ROOT = Path(__file__).resolve().parents[4]

SOURCE_SCRIPTS: dict[str, Path] = {
    "boss": CODE_ROOT / "zhipin_joblist_crawl.py",
    "boss_dp": CODE_ROOT / "zhipin_dp_crawl_v2.py",
    "guopin": CODE_ROOT / "guopin_joblist_crawl.py",
    "jobmohrss": CODE_ROOT / "jobmohrss_joblist_crawl.py",
    "lagou": CODE_ROOT / "lagou_joblist_crawl.py",
    "liepin": CODE_ROOT / "liepin_joblist_crawl.py",
    "ncss24365": CODE_ROOT / "ncss24365_joblist_crawl.py",
    "qdhr": CODE_ROOT / "qdhr_joblist_crawl.py",
    "qingdao_rc": CODE_ROOT / "qingdao_rc_joblist_crawl.py",
    "rcsd_talents": CODE_ROOT / "rcsd_talents_joblist_crawl.py",
    "sdgxbys": CODE_ROOT / "sdgxbys_joblist_crawl.py",
    "sdgxbys_campus": CODE_ROOT / "sdgxbys_campus_joblist_crawl.py",
    "job51": CODE_ROOT / "job51_joblist_crawl.py",
    "shixiseng": CODE_ROOT / "shixiseng_joblist_crawl.py",
    "zhilian": CODE_ROOT / "zhilian_joblist_crawl.py",
}


def _load_source_module(source_code: str) -> Any:
    script_path = SOURCE_SCRIPTS.get(source_code)
    if script_path is None:
        raise RuntimeError(f"暂不支持来源: {source_code}")
    if not script_path.exists():
        raise RuntimeError(f"来源脚本不存在: {script_path}")

    spec = importlib.util.spec_from_file_location(f"crawler_runtime_{source_code}", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载来源脚本: {script_path}")

    module = importlib.util.module_from_spec(spec)
    code_root_text = str(CODE_ROOT)
    inserted_code_root = False
    if code_root_text not in sys.path:
        sys.path.insert(0, code_root_text)
        inserted_code_root = True
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted_code_root:
            try:
                sys.path.remove(code_root_text)
            except ValueError:
                pass
    return module


def list_crawl_sources(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    return list_source_catalog(include_disabled=include_disabled)


def load_source_module(source_code: str) -> Any:
    return _load_source_module(source_code)


def run_incremental_crawl_for_sources(
    sources: list[str],
    queries: list[str],
    cities: list[str],
    max_pages: int,
    page_size: int,
    runtime_mode: str,
    source_options: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    normalized_sources: list[str] = []
    for source in sources:
        source_code = (source or "").strip().lower()
        if source_code and source_code not in normalized_sources:
            normalized_sources.append(source_code)

    if not normalized_sources:
        normalized_sources = ["boss_dp"]

    total_fetched = 0
    new_to_db = 0
    source_results: list[dict[str, Any]] = []
    source_details: dict[str, dict[str, Any]] = {}
    normalized_source_options = dict(source_options or {})
    success_source_count = 0
    failed_source_count = 0
    skipped_source_count = 0
    source_failure_messages: list[str] = []

    for source_code in normalized_sources:
        source_info = get_source_info(source_code)
        source_name = str(source_info.get("source_name") or source_code)
        if not source_info.get("enabled", False):
            skipped_source_count += 1
            source_results.append(
                {
                    "source_code": source_code,
                    "source_name": source_name,
                    "status": "skipped",
                    "reason": str(source_info.get("description") or "来源未启用"),
                    "total_fetched": 0,
                    "new_to_db": 0,
                    "result": {},
                }
            )
            source_details[source_code] = {}
            if progress_callback is not None:
                progress_callback(
                    f"来源 {source_name} 已跳过：{source_info.get('description') or '来源未启用'}",
                    {"source_code": source_code},
                )
            continue

        if progress_callback is not None:
            progress_callback(f"开始执行来源 {source_name}", {"source_code": source_code})
        try:
            module = _load_source_module(source_code)
            kwargs: dict[str, Any] = {
                "queries": queries,
                "cities": cities,
                "max_pages": max_pages,
                "page_size": page_size,
                "runtime_mode": runtime_mode,
                "progress_callback": progress_callback,
                "should_stop_callback": should_stop_callback,
            }
            try:
                signature = inspect.signature(module.run_incremental_update)
            except (TypeError, ValueError):
                signature = None
            if signature is not None and "source_options" in signature.parameters:
                kwargs["source_options"] = dict(normalized_source_options.get(source_code) or {})

            result = module.run_incremental_update(**kwargs)
            normalized_result = dict(result) if isinstance(result, dict) else {}
            fetched = int(normalized_result.get("total_fetched", 0)) if normalized_result else 0
            created = int(normalized_result.get("new_to_db", 0)) if normalized_result else 0
            total_fetched += fetched
            new_to_db += created
            success_source_count += 1
            source_details[source_code] = normalized_result
            source_results.append(
                {
                    "source_code": source_code,
                    "source_name": source_name,
                    "status": "success",
                    "total_fetched": fetched,
                    "new_to_db": created,
                    "result": normalized_result,
                }
            )

            if progress_callback is not None:
                progress_callback(
                    f"来源 {source_name} 执行完成：新增 {created} 条，抓取 {fetched} 条",
                    {"source_code": source_code},
                )
        except Exception as exc:
            if exc.__class__.__name__ == "CrawlCancelledError":
                raise
            failed_source_count += 1
            failure_message = str(exc)
            source_failure_messages.append(f"{source_name}: {failure_message}")
            failure_result = {
                "error": failure_message,
                "exception_type": exc.__class__.__name__,
            }
            source_details[source_code] = failure_result
            source_results.append(
                {
                    "source_code": source_code,
                    "source_name": source_name,
                    "status": "failed",
                    "reason": failure_message,
                    "total_fetched": 0,
                    "new_to_db": 0,
                    "result": failure_result,
                }
            )
            if progress_callback is not None:
                progress_callback(
                    f"来源 {source_name} 执行失败：{failure_message}",
                    {"source_code": source_code},
                )

    aggregated_result = {
        "total_fetched": total_fetched,
        "new_to_db": new_to_db,
        "sources": source_results,
        "source_details": source_details,
        "success_sources": success_source_count,
        "failed_sources": failed_source_count,
        "skipped_sources": skipped_source_count,
        "has_failures": failed_source_count > 0,
        "source_failure_messages": source_failure_messages,
    }

    for source_code in normalized_sources:
        detail = source_details.get(source_code) or {}
        for key, value in detail.items():
            if key in {"total_fetched", "new_to_db", "sources", "source_details"}:
                continue
            aggregated_result.setdefault(key, value)

    return aggregated_result