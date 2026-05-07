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
SUMMARY_PATH = DATA_DIR / "unverified_jobs_check_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import init_database, verify_unverified_active_jobs  # noqa: E402
from app.core.job_sources import get_source_name  # noqa: E402


DEFAULT_SOURCE_CODES = [
    "ncss24365", "job51", "liepin", "zhilian", "boss_dp", "boss", "guopin", "shixiseng",
    "chenhr", "qdhr", "buildhr", "jobmohrss", "healthr", "healthr_doctor",
    "qingdao_rc", "sdgxbys", "sdgxbys_campus", "qlrc", "rcsd_talents", "wuba",
    "lagou", "niuke_campus", "yingjiesheng", "dxy_job", "gaoxiaojob", "jobonline",
    "jxhg_chenhr", "mhg_chenhr", "sysh_chenhr", "newenergy_chenhr", "sales_chenhr",
    "doctor_healthr", "pha_healthr", "env_buildhr", "construct_buildhr",
]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}
DEFAULT_LIMIT = 200
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_WORKERS = 8


def emit_console(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验活跃但从未验证过的职位 URL 是否仍在线。")
    parser.add_argument("--sources", help="Comma-separated source codes, or 'none' to skip all sources.")
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup, database initialization, and summary writing without real verification.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max jobs to check per run (default: {DEFAULT_LIMIT}).")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Timeout per URL request in seconds.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of parallel workers for URL verification (default: {DEFAULT_WORKERS}).")
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

    deduped: list[str] = []
    for item in filtered_items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def run_check(
    selected_sources: list[str] | None = None,
    validate_startup: bool = False,
    limit: int = DEFAULT_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    emit_console("[unverified-jobs-check] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    resolved_sources = list(selected_sources) if selected_sources is not None else resolve_sources(None)
    started_at = datetime.now(timezone.utc)

    if validate_startup:
        emit_console("[unverified-jobs-check] 启动验证模式，不执行真实校验")
        summary = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "validate_startup": True,
            "task_name": "未校验职位 URL 健康检查（启动验证）",
            "selected_sources": resolved_sources,
            "limit": limit,
            "timeout_seconds": timeout_seconds,
            "checked_count": 0,
            "confirmed_offline_count": 0,
            "still_online_count": 0,
            "candidate_count": 0,
        }
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        emit_console(f"[unverified-jobs-check] 摘要已写入: {SUMMARY_PATH}")
        return summary

    if not resolved_sources:
        emit_console("[unverified-jobs-check] 未选择任何来源，跳过校验")
        summary = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "validate_startup": False,
            "task_name": "未校验职位 URL 健康检查（无来源）",
            "selected_sources": [],
            "limit": limit,
            "timeout_seconds": timeout_seconds,
            "checked_count": 0,
            "confirmed_offline_count": 0,
            "still_online_count": 0,
            "candidate_count": 0,
        }
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    emit_console(f"[unverified-jobs-check] 开始校验，来源: {', '.join(resolved_sources)}, limit={limit}, timeout={timeout_seconds}s")

    result = verify_unverified_active_jobs(
        limit=limit,
        timeout_seconds=timeout_seconds,
        source_codes=resolved_sources,
        workers=workers,
    )

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "validate_startup": False,
        "task_name": "未校验职位 URL 健康检查",
        "selected_sources": resolved_sources,
        "limit": limit,
        "timeout_seconds": timeout_seconds,
        **{k: v for k, v in result.items()},
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(
        f"[unverified-jobs-check] 完成: checked={result.get('checked_count', 0)} "
        f"offline={result.get('confirmed_offline_count', 0)} "
        f"online={result.get('still_online_count', 0)}"
    )
    emit_console(f"[unverified-jobs-check] 摘要已写入: {SUMMARY_PATH}")
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    result = run_check(
        selected_sources=selected_sources,
        validate_startup=bool(args.validate_startup),
        limit=int(args.limit),
        timeout_seconds=float(args.timeout),
        workers=int(args.workers),
    )
    checked = int(result.get("checked_count", 0))
    if checked == 0:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
