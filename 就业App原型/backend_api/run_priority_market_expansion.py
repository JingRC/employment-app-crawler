from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_SUMMARY_PATH = DATA_DIR / "priority_market_expansion_last_result.json"
DEFAULT_CHECKPOINT_PATH = DATA_DIR / "priority_market_expansion_checkpoint.json"


@dataclass(frozen=True)
class ExpansionPhase:
    key: str
    label: str
    source: str
    queries: list[str]
    cities: list[str]
    city_group_size: int
    query_group_size: int
    max_pages: int
    page_size: int
    runtime_mode: str
    source_options: dict[str, Any]


EXPANSION_CITIES_ALL = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆", "天津", "长沙", "郑州", "济南",
    "苏州", "宁波", "青岛", "厦门", "合肥", "福州", "南昌", "沈阳", "长春", "哈尔滨", "昆明", "贵阳", "南宁",
]
EXPANSION_CITIES_PREMIUM = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆", "天津", "长沙", "苏州", "宁波", "青岛", "厦门",
]
EXPANSION_CITIES_SHIXISENG = ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "西安", "重庆", "天津", "长沙", "苏州", "合肥", "青岛", "郑州"]
EXPANSION_CITIES_GUOPIN = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆", "天津", "长沙"]
EXPANSION_CITIES_NCSS24365 = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京", "重庆", "天津", "长沙", "郑州", "济南",
    "苏州", "宁波", "青岛", "厦门", "合肥", "福州", "南昌", "沈阳", "长春", "哈尔滨", "昆明", "贵阳", "南宁",
]
EXPANSION_CITIES_VERTICAL_HEALTH = ["全国", "北京", "上海", "广州", "深圳", "杭州", "武汉", "成都"]
EXPANSION_CITIES_VERTICAL_HEALTH_DOCTOR = ["全国", "北京", "上海", "广州", "武汉", "成都", "西安"]
EXPANSION_CITIES_VERTICAL_BUILDHR = ["全国", "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "重庆", "天津", "西安"]
EXPANSION_CITIES_VERTICAL_CHENHR = ["全国", "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "天津", "青岛", "济南"]
EXPANSION_CITIES_QLRC = ["山东", "青岛", "济南", "烟台", "潍坊", "临沂", "淄博", "济宁"]
ZHILIAN_BEIJING_PRIORITY_QUERIES = ["产品经理", "销售", "数据分析"]
ZHILIAN_SHANGHAI_PRIORITY_QUERIES = ["产品经理", "销售", "数据分析"]


PHASES: list[ExpansionPhase] = [
    ExpansionPhase(
        key="zhilian-beijing-priority",
        label="智联北京高收益深挖",
        source="zhilian",
        queries=ZHILIAN_BEIJING_PRIORITY_QUERIES,
        cities=["北京"],
        city_group_size=1,
        query_group_size=2,
        max_pages=4,
        page_size=30,
        runtime_mode="browser",
        source_options={
            "zhilian": {
                "enable_request_probe": True,
                "prefer_request_pages": True,
                "probe_timeout_seconds": 8,
            }
        },
    ),
    ExpansionPhase(
        key="zhilian-shanghai-priority",
        label="智联上海高收益深挖",
        source="zhilian",
        queries=ZHILIAN_SHANGHAI_PRIORITY_QUERIES,
        cities=["上海"],
        city_group_size=1,
        query_group_size=2,
        max_pages=6,
        page_size=30,
        runtime_mode="browser",
        source_options={
            "zhilian": {
                "enable_request_probe": True,
                "prefer_request_pages": True,
                "probe_timeout_seconds": 8,
            }
        },
    ),
    ExpansionPhase(
        key="job51-general",
        label="51job 综合岗扩容",
        source="job51",
        queries=["Java", "Python", "前端", "测试", "运营", "销售", "财务", "人事", "行政", "管培生"],
        cities=EXPANSION_CITIES_ALL,
        city_group_size=6,
        query_group_size=2,
        max_pages=2,
        page_size=30,
        runtime_mode="browser",
        source_options={
            "job51": {
                "enable_request_probe": True,
                "prefer_request_pages": True,
                "probe_timeout_seconds": 8,
            }
        },
    ),
    ExpansionPhase(
        key="liepin-mid-senior",
        label="猎聘中高端补样本",
        source="liepin",
        queries=["Java", "Python", "前端", "产品经理", "数据分析", "算法", "运营", "财务"],
        cities=EXPANSION_CITIES_PREMIUM,
        city_group_size=4,
        query_group_size=2,
        max_pages=2,
        page_size=20,
        runtime_mode="browser",
        source_options={
            "liepin": {
                "city_mode": "precise_if_supported",
                "enable_request_probe": True,
                "probe_timeout_seconds": 8,
            }
        },
    ),
    ExpansionPhase(
        key="shixiseng-campus",
        label="实习僧实习校招补量",
        source="shixiseng",
        queries=["Java", "前端", "产品", "运营", "测试", "设计", "数据分析", "市场"],
        cities=EXPANSION_CITIES_SHIXISENG,
        city_group_size=4,
        query_group_size=2,
        max_pages=2,
        page_size=30,
        runtime_mode="api",
        source_options={
            "shixiseng": {
                "track": "campus",
                "detail_workers": 4,
                "detail_rate_per_second": 1.5,
                "include_campus_home_modules": True,
                "campus_hotintern_city": "推荐",
                "campus_hotcompany_industry": "推荐",
            }
        },
    ),
    ExpansionPhase(
        key="guopin-public",
        label="国聘央国企补量",
        source="guopin",
        queries=["软件开发", "数据分析", "财务", "行政", "管培生", "人力资源"],
        cities=EXPANSION_CITIES_GUOPIN,
        city_group_size=4,
        query_group_size=2,
        max_pages=2,
        page_size=50,
        runtime_mode="api",
        source_options={
            "guopin": {
                "detail_mode": "detail_api",
                "api_page_size": 50,
                "district_targets": [],
                "use_district_targets_only": False,
            }
        },
    ),
    ExpansionPhase(
        key="ncss24365-campus-official",
        label="24365 官方校招补量",
        source="ncss24365",
        queries=["Java", "Python", "前端", "测试", "产品经理", "数据分析", "管培生", "运营"],
        cities=EXPANSION_CITIES_NCSS24365,
        city_group_size=6,
        query_group_size=2,
        max_pages=2,
        page_size=30,
        runtime_mode="api",
        source_options={
            "ncss24365": {
                "detail_mode": "detail_html",
            }
        },
    ),
    ExpansionPhase(
        key="healthr-national-vertical",
        label="医药英才网全国补量",
        source="healthr",
        queries=["销售", "推广", "工程师", "渠道"],
        cities=EXPANSION_CITIES_VERTICAL_HEALTH,
        city_group_size=2,
        query_group_size=2,
        max_pages=2,
        page_size=20,
        runtime_mode="requests_only",
        source_options={
            "healthr": {
                "detail_mode": "detail_html",
                "request_timeout_seconds": 25,
            }
        },
    ),
    ExpansionPhase(
        key="healthr-doctor-national",
        label="医药英才网医疗卫生补量",
        source="healthr_doctor",
        queries=["医生", "护士", "医师", "内科", "外科"],
        cities=EXPANSION_CITIES_VERTICAL_HEALTH_DOCTOR,
        city_group_size=3,
        query_group_size=2,
        max_pages=2,
        page_size=20,
        runtime_mode="requests_only",
        source_options={
            "healthr_doctor": {
                "detail_mode": "detail_html",
                "request_timeout_seconds": 25,
            }
        },
    ),
    ExpansionPhase(
        key="buildhr-national-cost",
        label="建筑英才网全国补量",
        source="buildhr",
        queries=["建筑师", "预算员", "造价工程师", "BIM工程师", "项目经理", "结构工程师"],
        cities=EXPANSION_CITIES_VERTICAL_BUILDHR,
        city_group_size=3,
        query_group_size=2,
        max_pages=2,
        page_size=20,
        runtime_mode="requests_only",
        source_options={
            "buildhr": {
                "detail_mode": "detail_html",
                "request_timeout_seconds": 25,
            }
        },
    ),
    ExpansionPhase(
        key="chenhr-national-chemcore",
        label="化工英才网全国补量",
        source="chenhr",
        queries=["研发工程师", "工艺工程师", "设备工程师", "安全工程师", "生产经理", "化工"],
        cities=EXPANSION_CITIES_VERTICAL_CHENHR,
        city_group_size=3,
        query_group_size=2,
        max_pages=2,
        page_size=20,
        runtime_mode="requests_only",
        source_options={
            "chenhr": {
                "detail_mode": "detail_html",
                "request_timeout_seconds": 25,
            }
        },
    ),
    ExpansionPhase(
        key="qlrc-shandong-market",
        label="齐鲁人才网山东补量",
        source="qlrc",
        queries=["工程师", "销售", "运营", "技术员"],
        cities=EXPANSION_CITIES_QLRC,
        city_group_size=4,
        query_group_size=2,
        max_pages=4,
        page_size=20,
        runtime_mode="requests_only",
        source_options={
            "qlrc": {
                "detail_mode": "detail_html",
                "request_timeout_seconds": 30,
            }
        },
    ),
]


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    normalized = max(1, int(chunk_size or 1))
    return [items[index:index + normalized] for index in range(0, len(items), normalized)]


def build_plan(selected_phase_keys: list[str]) -> list[dict[str, Any]]:
    selected = [phase for phase in PHASES if phase.key in selected_phase_keys]
    plan: list[dict[str, Any]] = []
    for phase in selected:
        city_groups = chunked(list(phase.cities), phase.city_group_size)
        query_groups = chunked(list(phase.queries), phase.query_group_size)
        for query_index, queries in enumerate(query_groups, start=1):
            for city_index, cities in enumerate(city_groups, start=1):
                plan.append(
                    {
                        "phase_key": phase.key,
                        "label": f"{phase.label} / 关键词组 {query_index} / 城市组 {city_index}",
                        "config": {
                            "sources": [phase.source],
                            "queries": list(queries),
                            "cities": list(cities),
                            "max_pages": phase.max_pages,
                            "page_size": phase.page_size,
                            "runtime_mode": phase.runtime_mode,
                            "stale_after_hours": 72,
                            "source_options": json.loads(json.dumps(phase.source_options)),
                        },
                    }
                )
    return plan


def api_request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(f"{base_url.rstrip('/')}{path}", data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"请求失败: {exc}") from exc


def get_status(base_url: str) -> dict[str, Any]:
    response = api_request(base_url, "GET", "/api/crawler/status")
    return response.get("data") or {}


def wait_until_idle(base_url: str, poll_seconds: float = 2.5) -> dict[str, Any]:
    while True:
        data = get_status(base_url)
        status = str(data.get("status") or "").strip().lower()
        if status not in {"running", "cancelling"}:
            return data
        time.sleep(max(0.5, poll_seconds))


def write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_checkpoint(checkpoint: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_start_batch(
    requested_start_batch: int,
    selected_phase_keys: list[str],
    base_url: str,
    resume: bool,
    checkpoint_path: Path,
) -> int:
    start_batch = max(1, int(requested_start_batch or 1))
    if not resume:
        return start_batch

    checkpoint = load_json(checkpoint_path)
    if not checkpoint:
        log("未找到可恢复的检查点，按指定批次启动。")
        return start_batch

    checkpoint_phases = [str(item).strip() for item in checkpoint.get("selected_phases") or [] if str(item).strip()]
    checkpoint_base_url = str(checkpoint.get("base_url") or "").strip()
    next_batch = int(checkpoint.get("next_batch") or start_batch)
    if checkpoint_phases != selected_phase_keys or checkpoint_base_url != base_url:
        log("检查点与当前 phases 或 base_url 不一致，忽略自动恢复。")
        return start_batch

    resumed_batch = max(start_batch, next_batch)
    log(f"检测到检查点，自动从第 {resumed_batch} 批继续。")
    return resumed_batch


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run priority market expansion batches against the local crawler API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API base URL.")
    parser.add_argument(
        "--phases",
        default="zhilian-beijing-priority,zhilian-shanghai-priority,job51-general,liepin-mid-senior,shixiseng-campus,guopin-public",
        help="Comma-separated phase keys. Defaults to the six main platform phases.",
    )
    parser.add_argument("--max-batches", type=int, default=0, help="Optional cap on the number of batches to run.")
    parser.add_argument("--start-batch", type=int, default=1, help="1-based batch index to start from.")
    parser.add_argument("--resume", action="store_true", help="Resume from the local checkpoint when phases and base_url match.")
    parser.add_argument("--max-retries", type=int, default=1, help="Retry count for a failed batch before moving on.")
    parser.add_argument("--summary-path", default=str(DEFAULT_SUMMARY_PATH), help="Path to the JSON summary file.")
    parser.add_argument("--checkpoint-path", default=str(DEFAULT_CHECKPOINT_PATH), help="Path to the JSON checkpoint file.")
    parser.add_argument("--poll-seconds", type=float, default=2.5, help="Polling interval when waiting for a batch to finish.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue remaining batches after a failed batch.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned batches without submitting them.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary_path = Path(str(args.summary_path or DEFAULT_SUMMARY_PATH)).expanduser().resolve()
    checkpoint_path = Path(str(args.checkpoint_path or DEFAULT_CHECKPOINT_PATH)).expanduser().resolve()
    selected_phase_keys = [item.strip() for item in str(args.phases or "").split(",") if item.strip()]
    available_phase_keys = {phase.key for phase in PHASES}
    invalid_phase_keys = [item for item in selected_phase_keys if item not in available_phase_keys]
    if invalid_phase_keys:
        print(f"无效 phase: {', '.join(invalid_phase_keys)}", file=sys.stderr)
        return 2

    full_plan = build_plan(selected_phase_keys)
    total_plan_count = len(full_plan)
    start_batch = resolve_start_batch(args.start_batch, selected_phase_keys, args.base_url, args.resume, checkpoint_path)
    plan = full_plan
    if start_batch > 1:
        plan = plan[start_batch - 1 :]
    if args.max_batches and args.max_batches > 0:
        plan = plan[: args.max_batches]

    summary: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "selected_phases": selected_phase_keys,
        "start_batch": start_batch,
        "total_plan_count": total_plan_count,
        "batch_count": len(plan),
        "results": [],
        "dry_run": bool(args.dry_run),
        "max_retries": max(0, int(args.max_retries or 0)),
    }

    if start_batch > total_plan_count and total_plan_count > 0:
        log(f"起始批次 {start_batch} 已超过总批次数 {total_plan_count}，无需继续执行。")
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary["completed"] = 0
        summary["failed"] = 0
        summary["total_fetched"] = 0
        summary["total_new"] = 0
        write_summary(summary, summary_path)
        write_checkpoint({
            "base_url": args.base_url,
            "selected_phases": selected_phase_keys,
            "total_plan_count": total_plan_count,
            "next_batch": start_batch,
            "finished": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, checkpoint_path)
        return 0

    if args.dry_run:
        log(f"dry-run：共生成 {len(plan)} 个批次。")
        for index, batch in enumerate(plan, start=start_batch):
            config = batch["config"]
            log(f"[{index}/{start_batch + len(plan) - 1}] {batch['label']} -> 来源 {','.join(config['sources'])} / 关键词 {','.join(config['queries'])} / 城市 {','.join(config['cities'])}")
        write_summary(summary, summary_path)
        return 0

    current_status = get_status(args.base_url)
    current_state = str(current_status.get("status") or "").strip().lower()
    if current_state in {"running", "cancelling"}:
        log(f"后台当前为 {current_state}，请等待现有任务结束后再启动优先扩量。")
        summary["blocked_by_status"] = current_state
        write_summary(summary, summary_path)
        return 1

    total_fetched = 0
    total_new = 0
    completed = 0
    failed = 0
    max_retries = max(0, int(args.max_retries or 0))

    write_checkpoint(
        {
            "base_url": args.base_url,
            "selected_phases": selected_phase_keys,
            "total_plan_count": total_plan_count,
            "start_batch": start_batch,
            "next_batch": start_batch,
            "completed": completed,
            "failed": failed,
            "total_fetched": total_fetched,
            "total_new": total_new,
            "finished": False,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        checkpoint_path,
    )

    log(f"准备执行 {len(plan)} 个主平台优先批次。")
    for relative_index, batch in enumerate(plan, start=1):
        absolute_index = start_batch + relative_index - 1
        config = batch["config"]
        attempts = 0
        item_summary: dict[str, Any] | None = None
        while attempts <= max_retries:
            attempts += 1
            if attempts == 1:
                log(f"[{absolute_index}/{total_plan_count}] 提交 {batch['label']}，来源 {','.join(config['sources'])}，关键词 {','.join(config['queries'])}，城市 {','.join(config['cities'])}。")
            else:
                log(f"[{absolute_index}/{total_plan_count}] 第 {attempts} 次重试 {batch['label']}。")

            write_checkpoint(
                {
                    "base_url": args.base_url,
                    "selected_phases": selected_phase_keys,
                    "total_plan_count": total_plan_count,
                    "start_batch": start_batch,
                    "current_batch": absolute_index,
                    "next_batch": absolute_index,
                    "current_label": batch["label"],
                    "current_attempt": attempts,
                    "completed": completed,
                    "failed": failed,
                    "total_fetched": total_fetched,
                    "total_new": total_new,
                    "finished": False,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                checkpoint_path,
            )

            try:
                api_request(args.base_url, "POST", "/api/crawler/jobs/incremental", config)
                result = wait_until_idle(args.base_url, poll_seconds=args.poll_seconds)
                status = str(result.get("status") or "").strip().lower()
            except Exception as exc:
                result = {"status": "failed", "message": "批次提交失败", "error": str(exc), "last_result": {}}
                status = "failed"

            last_result = result.get("last_result") or {}
            fetched_count = int(last_result.get("total_fetched") or 0)
            new_count = int(last_result.get("new_to_db") or 0)
            item_summary = {
                "absolute_batch": absolute_index,
                "label": batch["label"],
                "phase_key": batch["phase_key"],
                "status": status,
                "attempts": attempts,
                "total_fetched": fetched_count,
                "new_to_db": new_count,
                "message": str(result.get("message") or "").strip(),
                "error": str(result.get("error") or "").strip(),
            }
            if status == "success":
                total_fetched += fetched_count
                total_new += new_count
                completed += 1
                log(f"[{absolute_index}/{total_plan_count}] 完成，抓取 {fetched_count} 条，新增 {new_count} 条。")
                break

            if attempts <= max_retries:
                log(f"[{absolute_index}/{total_plan_count}] 失败：{item_summary['error'] or item_summary['message'] or '未知错误'}；准备重试。")
            else:
                failed += 1
                log(f"[{absolute_index}/{total_plan_count}] 失败：{item_summary['error'] or item_summary['message'] or '未知错误'}")

        if item_summary is None:
            item_summary = {
                "absolute_batch": absolute_index,
                "label": batch["label"],
                "phase_key": batch["phase_key"],
                "status": "failed",
                "attempts": attempts,
                "total_fetched": 0,
                "new_to_db": 0,
                "message": "未生成批次结果",
                "error": "未生成批次结果",
            }
        summary["results"].append(item_summary)

        next_batch = absolute_index + 1
        write_checkpoint(
            {
                "base_url": args.base_url,
                "selected_phases": selected_phase_keys,
                "total_plan_count": total_plan_count,
                "start_batch": start_batch,
                "last_batch": item_summary,
                "next_batch": next_batch,
                "completed": completed,
                "failed": failed,
                "total_fetched": total_fetched,
                "total_new": total_new,
                "finished": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            checkpoint_path,
        )
        if item_summary["status"] != "success" and not args.continue_on_error:
            break

    summary.update(
        {
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "completed": completed,
            "failed": failed,
            "total_fetched": total_fetched,
            "total_new": total_new,
        }
    )
    write_summary(summary, summary_path)
    write_checkpoint(
        {
            "base_url": args.base_url,
            "selected_phases": selected_phase_keys,
            "total_plan_count": total_plan_count,
            "start_batch": start_batch,
            "next_batch": start_batch + len(plan),
            "completed": completed,
            "failed": failed,
            "total_fetched": total_fetched,
            "total_new": total_new,
            "finished": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        checkpoint_path,
    )
    log(f"执行结束：成功 {completed} 批，失败 {failed} 批，累计抓取 {total_fetched} 条，新增 {total_new} 条。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())