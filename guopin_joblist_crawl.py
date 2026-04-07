from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    import requests
except ImportError:
    requests = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
API_BASE_URL = "https://gp-api.iguopin.com"
WEB_BASE_URL = "https://www.iguopin.com"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "list_only",
    "api_page_size": 50,
    "district_targets": [],
    "use_district_targets_only": False,
    "request_timeout_seconds": 15.0,
}
REQUEST_HEADERS = {
    "Origin": WEB_BASE_URL,
    "Referer": f"{WEB_BASE_URL}/job/list",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}


class CrawlCancelledError(Exception):
    pass


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass


def emit_progress(progress_callback: Callable[[str, dict[str, Any]], None] | None, message: str, **context: Any) -> None:
    if progress_callback is not None:
        progress_callback(message, context)


def ensure_not_cancelled(
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    **context: Any,
) -> None:
    if should_stop_callback is not None and should_stop_callback():
        emit_progress(progress_callback, "收到取消信号，准备停止国聘采集", **context)
        raise CrawlCancelledError("crawl cancelled")


def safe_sleep(
    seconds: float,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    **context: Any,
) -> None:
    remaining = max(0.0, seconds)
    while remaining > 0:
        ensure_not_cancelled(should_stop_callback, progress_callback, **context)
        step = min(0.5, remaining)
        time.sleep(step)
        remaining -= step


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def normalize_queries(queries: list[str] | None) -> list[str]:
    values = [clean_text(item) for item in (queries or DEFAULT_QUERIES) if clean_text(item)]
    return values or list(DEFAULT_QUERIES)


def normalize_cities(cities: list[str] | None) -> list[str]:
    values: list[str] = []
    for item in (cities or DEFAULT_CITIES):
        city_name = clean_text(item)
        if city_name and city_name not in values:
            values.append(city_name)
    if not values:
        values = list(DEFAULT_CITIES)
    if "全国" in values:
        return ["全国", *[item for item in values if item != "全国"]]
    return values


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(DEFAULT_SOURCE_OPTIONS)
    options.update(source_options or {})
    detail_mode = clean_text(options.get("detail_mode") or DEFAULT_SOURCE_OPTIONS["detail_mode"]).lower() or "list_only"
    try:
        api_page_size = int(options.get("api_page_size") or DEFAULT_SOURCE_OPTIONS["api_page_size"])
    except (TypeError, ValueError):
        api_page_size = int(DEFAULT_SOURCE_OPTIONS["api_page_size"])
    try:
        request_timeout_seconds = float(options.get("request_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    except (TypeError, ValueError):
        request_timeout_seconds = float(DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    district_targets_raw = options.get("district_targets") or []
    if isinstance(district_targets_raw, str):
        district_targets = [clean_text(item) for item in re.split(r"[\n,，、;；]", district_targets_raw) if clean_text(item)]
    elif isinstance(district_targets_raw, (list, tuple, set)):
        district_targets = [clean_text(item) for item in district_targets_raw if clean_text(item)]
    else:
        district_targets = []
    use_district_targets_only_raw = options.get("use_district_targets_only")
    if isinstance(use_district_targets_only_raw, str):
        use_district_targets_only = clean_text(use_district_targets_only_raw).lower() in {"1", "true", "yes", "on"}
    else:
        use_district_targets_only = bool(use_district_targets_only_raw)
    deduped_district_targets: list[str] = []
    for item in district_targets:
        if item not in deduped_district_targets:
            deduped_district_targets.append(item)
    return {
        "detail_mode": detail_mode if detail_mode in {"list_only", "detail_api"} else "list_only",
        "api_page_size": max(10, min(api_page_size, 100)),
        "district_targets": deduped_district_targets,
        "use_district_targets_only": use_district_targets_only,
        "request_timeout_seconds": max(5.0, min(request_timeout_seconds, 60.0)),
    }


def ensure_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_job_id TEXT UNIQUE,
            title TEXT NOT NULL,
            company_name TEXT NOT NULL,
            city_name TEXT DEFAULT '',
            district_name TEXT DEFAULT '',
            salary_text TEXT DEFAULT '',
            degree_text TEXT DEFAULT '',
            experience_text TEXT DEFAULT '',
            brand_scale TEXT DEFAULT '',
            brand_stage TEXT DEFAULT '',
            job_type TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            official_apply_url TEXT DEFAULT '',
            description_text TEXT DEFAULT '',
            unique_hash TEXT UNIQUE,
            content_hash TEXT DEFAULT '',
            source_code TEXT DEFAULT '',
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_type TEXT NOT NULL DEFAULT 'new_job',
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            related_job_id INTEGER,
            related_company_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def build_session() -> requests.Session:
    if requests is None:
        raise RuntimeError("未安装 requests，无法执行国聘接口采集")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def split_city_district(area_text: str) -> tuple[str, str]:
    value = clean_text(area_text)
    if not value:
        return "", ""
    for separator in ["-", "·", "/", "|"]:
        if separator in value:
            city_name, district_name = value.split(separator, 1)
            return clean_text(city_name), clean_text(district_name)
    return value, ""


def city_matches(target_city: str, city_name: str) -> bool:
    normalized_target = clean_text(target_city)
    normalized_city = clean_text(city_name)
    if not normalized_target or normalized_target == "全国":
        return True
    return normalized_target == normalized_city


def simplify_area_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    suffixes = [
        "特别行政区",
        "壮族自治区",
        "回族自治区",
        "维吾尔自治区",
        "自治区",
        "自治州",
        "自治县",
        "地区",
        "盟",
        "省",
        "市",
        "县",
        "区",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return clean_text(text)


def build_area_aliases(*values: Any) -> set[str]:
    aliases: set[str] = set()
    for value in values:
        text = clean_text(value)
        simple = simplify_area_name(value)
        if text:
            aliases.add(text)
        if simple:
            aliases.add(simple)
    return aliases


def split_area_tokens(area_text: str) -> list[str]:
    value = clean_text(area_text)
    if not value:
        return []
    return [clean_text(item) for item in re.split(r"[\s\-·/|>＞]+", value) if clean_text(item)]


def fetch_district_tree(session: requests.Session, *, timeout_seconds: float) -> list[dict[str, Any]]:
    response = session.get(f"{API_BASE_URL}/api/base/districts/v1/tree", timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("code") or 0) != 200:
        raise RuntimeError(clean_text(payload.get("msg")) or "国聘地区树接口返回异常")
    data = payload.get("data")
    return list(data) if isinstance(data, list) else []


def resolve_city_district_code(city_name: str, district_tree: list[dict[str, Any]]) -> str | None:
    target = clean_text(city_name)
    if not target or target == "全国":
        return None
    target_tokens = split_area_tokens(target)

    for root in district_tree:
        if not isinstance(root, dict):
            continue
        provinces = root.get("children") or []
        for province in provinces:
            if not isinstance(province, dict):
                continue
            province_code = clean_text(province.get("value"))
            if not province_code:
                continue
            province_path = f"000000.{province_code}"
            province_aliases = build_area_aliases(province.get("label"), province.get("name"))
            is_special_province = bool(province.get("is_special"))
            if target in province_aliases:
                return province_path

            cities = province.get("children") or []
            for city in cities:
                if not isinstance(city, dict):
                    continue
                city_code = clean_text(city.get("value"))
                if not city_code:
                    continue
                city_aliases = build_area_aliases(city.get("label"), city.get("name"))
                if target in city_aliases:
                    if is_special_province or simplify_area_name(city.get("label")) == simplify_area_name(province.get("label")):
                        return province_path
                    return f"{province_path}.{city_code}"
                if len(target_tokens) >= 2 and target_tokens[-1] in city_aliases and target_tokens[0] in province_aliases:
                    if is_special_province or simplify_area_name(city.get("label")) == simplify_area_name(province.get("label")):
                        return province_path
                    return f"{province_path}.{city_code}"

                districts = city.get("children") or []
                for district in districts:
                    if not isinstance(district, dict):
                        continue
                    district_code = clean_text(district.get("value"))
                    if not district_code:
                        continue
                    district_aliases = build_area_aliases(district.get("label"), district.get("name"))
                    if target in district_aliases:
                        return f"{province_path}.{city_code}.{district_code}"
                    if len(target_tokens) == 2 and target_tokens[-1] in district_aliases and (
                        target_tokens[0] in city_aliases or target_tokens[0] in province_aliases
                    ):
                        return f"{province_path}.{city_code}.{district_code}"
                    if len(target_tokens) >= 3 and target_tokens[-1] in district_aliases and target_tokens[0] in province_aliases and target_tokens[-2] in city_aliases:
                        return f"{province_path}.{city_code}.{district_code}"

    return None


def build_salary_text(item: dict[str, Any]) -> str:
    if bool(item.get("is_negotiable")):
        return "面议"
    min_wage = int(item.get("min_wage") or 0)
    max_wage = int(item.get("max_wage") or 0)
    wage_unit = clean_text(item.get("wage_unit_cn") or "元/月")
    months = int(item.get("months") or 0)
    if min_wage > 0 and max_wage > 0:
        min_k = min_wage / 1000
        max_k = max_wage / 1000
        if min_k.is_integer():
            min_text = str(int(min_k))
        else:
            min_text = f"{min_k:.1f}".rstrip("0").rstrip(".")
        if max_k.is_integer():
            max_text = str(int(max_k))
        else:
            max_text = f"{max_k:.1f}".rstrip("0").rstrip(".")
        salary = f"{min_text}~{max_text}K"
    elif max_wage > 0:
        max_k = max_wage / 1000
        salary = f"{int(max_k) if max_k.is_integer() else max_k:.1f}K"
    else:
        salary = "面议"
    if wage_unit and wage_unit != "元/月":
        salary = f"{salary}{wage_unit}"
    if months > 0:
        salary = f"{salary}·{months}薪"
    return clean_text(salary)


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = detail_item or {}
    merged = dict(item)
    merged.update({key: value for key, value in detail.items() if value not in (None, "", [], {})})
    job_id = clean_text(merged.get("job_id"))
    company_id = clean_text(merged.get("company_id"))
    district_list = merged.get("district_list") or []
    area_text = ""
    if district_list and isinstance(district_list[0], dict):
        area_text = clean_text(district_list[0].get("area_cn"))
    city_name, district_name = split_city_district(area_text)
    company_info = merged.get("company_info") if isinstance(merged.get("company_info"), dict) else {}
    description_text = clean_text(merged.get("contents"))
    if clean_text(merged.get("apply_instruction")):
        description_text = clean_text(f"{description_text}\n{clean_text(merged.get('apply_instruction'))}")
    job_type_parts = [
        clean_text(merged.get("recruitment_type_cn")),
        clean_text(merged.get("nature_cn")),
    ]
    detail_url = f"{WEB_BASE_URL}/job/detail?id={job_id}" if job_id else f"{WEB_BASE_URL}/job/list"
    company_url = f"{WEB_BASE_URL}/company?id={company_id}" if company_id else ""
    brand_stage = clean_text(company_info.get("financing_stage_cn")) or clean_text(company_info.get("nature_cn"))
    tags = merged.get("job_tags_cn") if isinstance(merged.get("job_tags_cn"), list) else []
    if tags:
        tag_text = " / ".join(clean_text(tag) for tag in tags if clean_text(tag))
        if tag_text:
            description_text = clean_text(f"{tag_text}\n{description_text}")
    return {
        "source_job_id": job_id,
        "title": clean_text(merged.get("job_name")),
        "company_name": clean_text(merged.get("company_name")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": build_salary_text(merged),
        "degree_text": clean_text(merged.get("education_cn")),
        "experience_text": clean_text(merged.get("experience_cn")),
        "brand_scale": clean_text(company_info.get("scale_cn")),
        "brand_stage": brand_stage,
        "job_type": " / ".join(part for part in job_type_parts if part),
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": description_text,
        "company_url": company_url,
    }


def fetch_job_list_page(
    session: requests.Session,
    *,
    query: str,
    api_page_no: int,
    api_page_size: int,
    district_code: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    search_payload: dict[str, Any] = {"page": api_page_no, "page_size": api_page_size, "keyword": query}
    if district_code:
        search_payload["district"] = [district_code]

    response = session.post(
        f"{API_BASE_URL}/api/jobs/v1/recom-job",
        json={
            "search": search_payload,
            "recom": {"update_time": True, "company_nature": True, "hot_job": True},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("code") or 0) != 200:
        raise RuntimeError(clean_text(payload.get("msg")) or "国聘推荐列表接口返回异常")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    items = [item for item in (data.get("list") or []) if isinstance(item, dict) and clean_text(item.get("job_id"))]
    return {
        "total": int(data.get("total") or 0),
        "page": int(data.get("page") or api_page_no),
        "page_size": int(data.get("page_size") or api_page_size),
        "items": items,
    }


def fetch_job_detail(
    session: requests.Session,
    *,
    job_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not job_id:
        return {}
    response = session.get(
        f"{API_BASE_URL}/api/jobs/v1/info",
        params={"id": job_id},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("code") or 0) != 200:
        return {}
    return payload.get("data") if isinstance(payload.get("data"), dict) else {}


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "guopin") -> dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for item in jobs:
        job_id = clean_text(item.get("source_job_id"))
        title = clean_text(item.get("title"))
        company_name = clean_text(item.get("company_name"))
        city_name = clean_text(item.get("city_name"))
        if not job_id or not title or not company_name:
            continue

        unique_hash = hashlib.sha256(f"{source_code}|{job_id}".encode("utf-8")).hexdigest()[:32]
        content_text = "|".join(
            [
                title,
                clean_text(item.get("salary_text")),
                clean_text(item.get("degree_text")),
                clean_text(item.get("experience_text")),
                clean_text(item.get("description_text")),
            ]
        )
        content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()[:32]

        existing = conn.execute("SELECT id, content_hash FROM jobs WHERE unique_hash = ?", (unique_hash,)).fetchone()
        if existing is None:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    source_job_id, title, company_name, city_name, district_name,
                    salary_text, degree_text, experience_text, brand_scale, brand_stage,
                    job_type, source_url, official_apply_url, description_text,
                    unique_hash, content_hash, source_code, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active')
                """,
                (
                    job_id,
                    title,
                    company_name,
                    city_name,
                    clean_text(item.get("district_name")),
                    clean_text(item.get("salary_text")),
                    clean_text(item.get("degree_text")),
                    clean_text(item.get("experience_text")),
                    clean_text(item.get("brand_scale")),
                    clean_text(item.get("brand_stage")),
                    clean_text(item.get("job_type")),
                    clean_text(item.get("source_url")),
                    clean_text(item.get("official_apply_url")),
                    clean_text(item.get("description_text")),
                    unique_hash,
                    content_hash,
                    source_code,
                ),
            )
            if cursor.rowcount > 0:
                stats["new"] += 1
                conn.execute(
                    "INSERT INTO notifications (notification_type,title,content,related_job_id) VALUES ('new_job',?,?,?)",
                    ("新职位发现", f"{company_name} 发布了 {title}（{city_name}）", cursor.lastrowid),
                )
        elif existing["content_hash"] != content_hash:
            conn.execute(
                """
                UPDATE jobs
                SET title=?, company_name=?, city_name=?, district_name=?, salary_text=?, degree_text=?,
                    experience_text=?, brand_scale=?, brand_stage=?, job_type=?, source_url=?, official_apply_url=?,
                    description_text=?, content_hash=?, last_seen_at=CURRENT_TIMESTAMP, status='active'
                WHERE id=?
                """,
                (
                    title,
                    company_name,
                    city_name,
                    clean_text(item.get("district_name")),
                    clean_text(item.get("salary_text")),
                    clean_text(item.get("degree_text")),
                    clean_text(item.get("experience_text")),
                    clean_text(item.get("brand_scale")),
                    clean_text(item.get("brand_stage")),
                    clean_text(item.get("job_type")),
                    clean_text(item.get("source_url")),
                    clean_text(item.get("official_apply_url")),
                    clean_text(item.get("description_text")),
                    content_hash,
                    existing["id"],
                ),
            )
            stats["updated"] += 1
        else:
            conn.execute("UPDATE jobs SET last_seen_at=CURRENT_TIMESTAMP, status='active' WHERE id=?", (existing["id"],))
            stats["unchanged"] += 1

    conn.commit()
    conn.close()
    return stats


def collect_filtered_jobs(
    session: requests.Session,
    *,
    query: str,
    city_name: str,
    target_pages: int,
    target_page_size: int,
    detail_mode: str,
    api_page_size: int,
    district_code: str | None,
    timeout_seconds: float,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    matched_jobs: list[dict[str, Any]] = []
    logical_pages: list[list[dict[str, Any]]] = []
    seen_job_ids: set[str] = set()
    upstream_page_no = 1
    last_total = 0
    while upstream_page_no <= target_pages:
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=upstream_page_no)
        payload = fetch_job_list_page(
            session,
            query=query,
            api_page_no=upstream_page_no,
            api_page_size=api_page_size,
            district_code=district_code,
            timeout_seconds=timeout_seconds,
        )
        raw_items = list(payload.get("items") or [])
        last_total = int(payload.get("total") or last_total)
        if not raw_items:
            break

        page_jobs: list[dict[str, Any]] = []
        for raw_item in raw_items:
            job_id = clean_text(raw_item.get("job_id"))
            if not job_id or job_id in seen_job_ids:
                continue
            detail_item = {}
            if detail_mode == "detail_api":
                detail_item = fetch_job_detail(session, job_id=job_id, timeout_seconds=timeout_seconds)
            job = normalize_job_item(raw_item, detail_item)
            if not clean_text(job.get("title")) or not clean_text(job.get("company_name")):
                continue
            seen_job_ids.add(job_id)
            page_jobs.append(job)
            matched_jobs.append(job)
            if len(page_jobs) >= target_page_size:
                break

        emit_progress(
            progress_callback,
            (
                f"国聘 {query} - {city_name} 上游第 {upstream_page_no} 页完成："
                f"原始 {len(raw_items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条"
            ),
            query=query,
            city_name=city_name,
            page=upstream_page_no,
            source_code="guopin",
        )

        logical_pages.append(page_jobs[:target_page_size])

        current_page = int(payload.get("page") or upstream_page_no)
        current_page_size = max(1, int(payload.get("page_size") or api_page_size))
        if current_page * current_page_size >= last_total > 0:
            break
        upstream_page_no += 1

    return {
        "pages": logical_pages,
        "matched_jobs": matched_jobs,
        "api_pages": min(upstream_page_no, target_pages),
        "total": last_total,
    }


def run_incremental_update(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    max_pages: int = 2,
    page_size: int = 20,
    output_dir: Path | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    runtime_mode: str = "requests_only",
    source_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del output_dir, runtime_mode
    configure_stdio()
    ensure_db()
    if requests is None:
        raise RuntimeError("未安装 requests，无法执行国聘接口采集")

    normalized_source_options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries)
    district_targets = list(normalized_source_options["district_targets"])
    if normalized_source_options["use_district_targets_only"] and district_targets:
        normalized_cities = []
    elif cities:
        normalized_cities = normalize_cities(cities)
    elif district_targets:
        normalized_cities = []
    else:
        normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 50))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    upstream_pages_used = 0
    resolved_city_codes: dict[str, str] = {}
    unresolved_locations: list[str] = []
    unresolved_district_targets: list[str] = []
    request_trace: list[dict[str, Any]] = []
    fallback_to_national_locations: list[str] = []
    empty_result_locations: list[str] = []
    target_locations = list(normalized_cities)
    for area_name in district_targets:
        if area_name not in target_locations:
            target_locations.append(area_name)
    if not target_locations:
        target_locations = list(DEFAULT_CITIES)
    session = build_session()
    district_tree = fetch_district_tree(session, timeout_seconds=float(normalized_source_options["request_timeout_seconds"]))

    emit_progress(progress_callback, "国聘采集启动，模式 requests_api", source_code="guopin")
    for query in normalized_queries:
        for location_name in target_locations:
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=location_name, page=1)
            district_code = resolve_city_district_code(location_name, district_tree)
            is_district_target = location_name in district_targets
            trace_item: dict[str, Any] = {
                "query": query,
                "location_name": location_name,
                "district_code": district_code or "",
                "is_district_target": is_district_target,
                "status": "pending",
                "target_pages": target_pages,
                "api_page_size": int(normalized_source_options["api_page_size"]),
                "logical_pages": 0,
                "api_pages_used": 0,
                "upstream_total": 0,
                "fetched_count": 0,
                "new_count": 0,
                "updated_count": 0,
            }
            if location_name != "全国" and not district_code:
                if location_name not in unresolved_locations:
                    unresolved_locations.append(location_name)
                if is_district_target and location_name not in unresolved_district_targets:
                    unresolved_district_targets.append(location_name)
                    trace_item["status"] = "unresolved"
                    request_trace.append(trace_item)
                    emit_progress(
                        progress_callback,
                        f"国聘未能解析区县目标 {location_name}，已跳过该目标",
                        query=query,
                        city_name=location_name,
                        source_code="guopin",
                    )
                    continue
                trace_item["status"] = "fallback_national"
                if location_name not in fallback_to_national_locations:
                    fallback_to_national_locations.append(location_name)
                emit_progress(
                    progress_callback,
                    f"国聘未能解析地区 {location_name} 的 district code，回退为全国检索",
                    query=query,
                    city_name=location_name,
                    source_code="guopin",
                )
            elif district_code:
                resolved_city_codes[location_name] = district_code
                trace_item["status"] = "resolved"
            emit_progress(progress_callback, f"国聘开始抓取 {query} - {location_name}", query=query, city_name=location_name, page=1, source_code="guopin")
            collect_result = collect_filtered_jobs(
                session,
                query=query,
                city_name=location_name,
                target_pages=target_pages,
                target_page_size=target_page_size,
                detail_mode=str(normalized_source_options["detail_mode"]),
                api_page_size=int(normalized_source_options["api_page_size"]),
                district_code=district_code,
                timeout_seconds=float(normalized_source_options["request_timeout_seconds"]),
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            logical_pages = [page_jobs for page_jobs in (collect_result.get("pages") or []) if page_jobs]
            api_pages_used = int(collect_result.get("api_pages") or 0)
            upstream_pages_used += api_pages_used
            trace_item["api_pages_used"] = api_pages_used
            trace_item["upstream_total"] = int(collect_result.get("total") or 0)
            trace_item["logical_pages"] = len(logical_pages)
            if not logical_pages:
                trace_item["status"] = "empty"
                request_trace.append(trace_item)
                if location_name not in empty_result_locations:
                    empty_result_locations.append(location_name)
                emit_progress(progress_callback, f"国聘 {query} - {location_name} 未解析到职位", query=query, city_name=location_name, source_code="guopin")
                continue

            location_fetched = 0
            location_new = 0
            location_updated = 0
            for logical_page_no, page_jobs in enumerate(logical_pages, start=1):
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=location_name, page=logical_page_no)
                stats = save_to_db(page_jobs, source_code="guopin")
                total_fetched += len(page_jobs)
                total_new += stats["new"]
                total_updated += stats["updated"]
                location_fetched += len(page_jobs)
                location_new += stats["new"]
                location_updated += stats["updated"]
                emit_progress(
                    progress_callback,
                    f"国聘 {query} - {location_name} 第 {logical_page_no} 页完成：抓取 {len(page_jobs)} 条，新增 {stats['new']}，更新 {stats['updated']}",
                    query=query,
                    city_name=location_name,
                    page=logical_page_no,
                    source_code="guopin",
                )
                if logical_page_no >= target_pages:
                    break
            trace_item["fetched_count"] = location_fetched
            trace_item["new_count"] = location_new
            trace_item["updated_count"] = location_updated
            trace_item["status"] = trace_item["status"] if trace_item["status"] == "fallback_national" else "resolved"
            request_trace.append(trace_item)

    emit_progress(progress_callback, f"国聘采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条", source_code="guopin")
    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated": total_updated,
        "queries": len(normalized_queries),
        "cities": len(target_locations),
        "runtime_mode": "requests_only",
        "detail_mode": normalized_source_options["detail_mode"],
        "use_district_targets_only": bool(normalized_source_options["use_district_targets_only"]),
        "upstream_pages_used": upstream_pages_used,
        "resolved_city_codes": resolved_city_codes,
        "unresolved_locations": unresolved_locations,
        "unresolved_district_targets": unresolved_district_targets,
        "request_trace": request_trace,
        "request_summary": {
            "total_targets": len(request_trace),
            "resolved_targets": sum(1 for item in request_trace if item.get("status") == "resolved"),
            "fallback_targets": len(fallback_to_national_locations),
            "empty_targets": len(empty_result_locations),
            "unresolved_targets": len(unresolved_district_targets),
        },
        "fallback_to_national_locations": fallback_to_national_locations,
        "empty_result_locations": empty_result_locations,
    }