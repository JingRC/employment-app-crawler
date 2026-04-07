from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl
from urllib.parse import urlsplit
from urllib.parse import urlencode

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None

try:
    import requests
except ImportError:
    requests = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
BASE_URL = "https://sou.zhaopin.com/"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州"]
DEFAULT_WAIT_SECONDS = 8.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_SOURCE_OPTIONS = {
    "enable_request_probe": True,
    "prefer_request_pages": True,
    "probe_timeout_seconds": 8.0,
}

CITY_ALIASES = {
    "全国站": "全国",
    "北京市": "北京",
    "上海市": "上海",
    "广州市": "广州",
    "深圳市": "深圳",
    "杭州市": "杭州",
    "成都市": "成都",
    "武汉市": "武汉",
    "南京市": "南京",
    "苏州市": "苏州",
    "青岛市": "青岛",
    "济南市": "济南",
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
        emit_progress(progress_callback, "收到取消信号，准备停止智联招聘采集", **context)
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


def retry_delay(attempt: int) -> float:
    return RETRY_BACKOFF_SECONDS * attempt


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


def build_browser_options() -> ChromiumOptions:
    if ChromiumOptions is None:
        raise RuntimeError("未安装 DrissionPage，无法执行智联招聘浏览器采集")
    options = ChromiumOptions()
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument("--disable-gpu")
    options.set_argument("--window-size=1440,960")
    return options


def normalize_queries(queries: list[str] | None) -> list[str]:
    values = [str(item).strip() for item in (queries or DEFAULT_QUERIES) if str(item).strip()]
    return values or list(DEFAULT_QUERIES)


def normalize_cities(cities: list[str] | None) -> list[str]:
    raw_values = [str(item).strip() for item in (cities or DEFAULT_CITIES) if str(item).strip()]
    normalized: list[str] = []
    for item in raw_values:
        city_name = CITY_ALIASES.get(item, item)
        if city_name and city_name not in normalized:
            normalized.append(city_name)
    if not normalized:
        normalized = list(DEFAULT_CITIES)
    if "全国" in normalized:
        return ["全国", *[item for item in normalized if item != "全国"]]
    return normalized


def parse_bool_option(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(DEFAULT_SOURCE_OPTIONS)
    options.update(source_options or {})
    try:
        probe_timeout_seconds = float(options.get("probe_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["probe_timeout_seconds"])
    except (TypeError, ValueError):
        probe_timeout_seconds = DEFAULT_SOURCE_OPTIONS["probe_timeout_seconds"]
    return {
        "enable_request_probe": parse_bool_option(options.get("enable_request_probe"), DEFAULT_SOURCE_OPTIONS["enable_request_probe"]),
        "prefer_request_pages": parse_bool_option(options.get("prefer_request_pages"), DEFAULT_SOURCE_OPTIONS["prefer_request_pages"]),
        "probe_timeout_seconds": max(3.0, min(probe_timeout_seconds, 20.0)),
    }


def resolve_city_param(city_name: str) -> str:
    normalized_city = CITY_ALIASES.get(str(city_name or "").strip(), str(city_name or "").strip())
    if normalized_city in {"", "全国"}:
        return ""
    return normalized_city


def build_search_url(query: str, city_name: str, page_no: int) -> str:
    params: dict[str, Any] = {
        "kw": query,
        "p": page_no,
    }
    city_param = resolve_city_param(city_name)
    if city_param:
        params["jl"] = city_param
    return f"{BASE_URL}?{urlencode(params)}"


def extract_initial_state(page: Any) -> dict[str, Any]:
    payload = page.run_js("return window.__INITIAL_STATE__")
    return payload if isinstance(payload, dict) else {}


def extract_page_payload_from_state(state: dict[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in (state.get("positionList") or [])
        if isinstance(item, dict) and (item.get("jobId") or item.get("number") or item.get("jobDetailData"))
    ]
    return {
        "items": items,
        "count": int(state.get("positionCount") or len(items) or 0),
        "pages": int(state.get("pages") or 1),
        "page_index": int(state.get("pageIndex") or 0),
        "city_code": clean_text((state.get("displayParams") or {}).get("cityCode") or (state.get("currentCityInfo") or {}).get("code")),
    }


def parse_positions_api_response_body(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        payload = body
    else:
        try:
            payload = json.loads(str(body or "{}"))
        except json.JSONDecodeError:
            payload = {}
    data = payload.get("data") or {}
    items = [item for item in (data.get("list") or []) if isinstance(item, dict) and (item.get("jobId") or item.get("number") or item.get("jobDetailData"))]
    return {
        "items": items,
        "count": int(data.get("count") or len(items) or 0),
        "pages": int(data.get("pageCount") or data.get("pages") or 0),
        "page_index": 0,
        "city_code": "",
        "is_end_page": int(data.get("isEndPage") or 0) == 1,
    }


def extract_positions_api_payload(packet: Any) -> dict[str, Any]:
    response = getattr(packet, "response", None)
    body = getattr(response, "body", None)
    return parse_positions_api_response_body(body)


def build_cookie_header(page: Any) -> str:
    cookies = page.cookies(all_domains=True, all_info=False)
    if isinstance(cookies, dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if clean_text(key))
    return str(cookies or "")


def normalize_request_headers(headers: Any, *, cookie_header: str, referer: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if isinstance(headers, dict):
        iterator = headers.items()
    else:
        iterator = []
    for key, value in iterator:
        header_key = clean_text(key)
        header_value = clean_text(value)
        if not header_key or not header_value:
            continue
        if header_key.lower() in {"content-length", "host", "cookie"}:
            continue
        normalized[header_key] = header_value
    normalized.setdefault("Referer", referer)
    normalized.setdefault("Origin", "https://sou.zhaopin.com")
    normalized.setdefault("Accept", "application/json, text/plain, */*")
    normalized.setdefault(
        "User-Agent",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    if cookie_header:
        normalized["Cookie"] = cookie_header
    return normalized


def extract_positions_api_request_sample(packet: Any, page: Any, *, query: str, city_name: str, page_no: int) -> dict[str, Any]:
    request = getattr(packet, "request", None)
    request_url = clean_text(getattr(request, "url", ""))
    if not request_url:
        return {}
    post_data = getattr(request, "postData", None)
    cookie_header = build_cookie_header(page)
    referer = clean_text(getattr(page, "url", "")) or build_search_url(query, city_name, page_no)
    parsed_url = urlsplit(request_url)
    return {
        "method": clean_text(getattr(request, "method", "POST")) or "POST",
        "url": request_url,
        "query_params": dict(parse_qsl(parsed_url.query, keep_blank_values=True)),
        "headers": normalize_request_headers(getattr(request, "headers", None), cookie_header=cookie_header, referer=referer),
        "post_data": post_data if isinstance(post_data, dict) else {},
        "captured_page": page_no,
        "query": query,
        "city_name": city_name,
        "referer": referer,
        "cookie_header": cookie_header,
    }


def replay_positions_api_sample(sample: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    result = fetch_positions_with_request_sample(sample, timeout_seconds=timeout_seconds)
    payload = result.get("payload") if isinstance(result, dict) else {}
    if not result.get("ok"):
        return {"ok": False, "reason": clean_text(result.get("reason"))}
    return {
        "ok": bool(payload.get("items")),
        "items": len(payload.get("items") or []),
        "count": int(payload.get("count") or 0),
        "pages": int(payload.get("pages") or 0),
        "is_end_page": bool(payload.get("is_end_page")),
    }


def update_nested_page_fields(value: Any, target_page_no: int) -> Any:
    if isinstance(value, dict):
        updated: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"pageIndex", "pageNo", "pageNum", "currentPage", "page"}:
                updated[key] = target_page_no
            elif key == "p":
                updated[key] = target_page_no
            else:
                updated[key] = update_nested_page_fields(item, target_page_no)
        return updated
    if isinstance(value, list):
        return [update_nested_page_fields(item, target_page_no) for item in value]
    return value


def build_request_sample_for_page(sample: dict[str, Any], target_page_no: int) -> dict[str, Any]:
    cloned = dict(sample)
    post_data = sample.get("post_data") if isinstance(sample.get("post_data"), dict) else {}
    query_params = sample.get("query_params") if isinstance(sample.get("query_params"), dict) else {}
    cloned["post_data"] = update_nested_page_fields(post_data, target_page_no)
    cloned["query_params"] = update_nested_page_fields(query_params, target_page_no)
    request_url = clean_text(sample.get("url"))
    parsed_url = urlsplit(request_url)
    if parsed_url.scheme and parsed_url.netloc:
        rebuilt_query = urlencode(cloned["query_params"], doseq=True)
        cloned["url"] = parsed_url._replace(query=rebuilt_query).geturl()
    cloned["captured_page"] = target_page_no
    return cloned


def fetch_positions_with_request_sample(sample: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    if requests is None:
        return {"ok": False, "reason": "requests_not_installed"}
    request_url = clean_text(sample.get("url"))
    if not request_url:
        return {"ok": False, "reason": "missing_url"}
    headers = sample.get("headers") if isinstance(sample.get("headers"), dict) else {}
    post_data = sample.get("post_data") if isinstance(sample.get("post_data"), dict) else {}
    try:
        response = requests.post(
            request_url,
            headers=headers,
            json=post_data,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = parse_positions_api_response_body(response.json())
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": bool(payload.get("items")), "payload": payload}


def load_positions_api_page_via_request_sample(
    request_sample: dict[str, Any],
    *,
    target_page_no: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    updated_sample = build_request_sample_for_page(request_sample, target_page_no)
    result = fetch_positions_with_request_sample(updated_sample, timeout_seconds=timeout_seconds)
    if not result.get("ok"):
        return {"payload": {}, "request_sample": updated_sample, "reason": clean_text(result.get("reason"))}
    return {
        "payload": result.get("payload") if isinstance(result.get("payload"), dict) else {},
        "request_sample": updated_sample,
        "reason": "",
    }


def find_next_page_button(page: Any) -> Any:
    for locator in [
        "tag:a@@text()=下一页",
        "tag:span@@text()=下一页",
        "tag:button@@text()=下一页",
    ]:
        button = page.ele(locator, timeout=2)
        if button is not None:
            return button
    return None


def load_positions_api_page_via_click(
    page: Any,
    *,
    target_page_no: int,
    query: str,
    city_name: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    page.listen.start("search/positions")
    button = find_next_page_button(page)
    if button is None:
        return {}
    button.click()
    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=target_page_no)
    packets = list(page.listen.steps(count=10, timeout=4))
    for packet in reversed(packets):
        request = getattr(packet, "request", None)
        request_url = str(getattr(request, "url", ""))
        if "search/positions" in request_url:
            payload = extract_positions_api_payload(packet)
            if payload.get("items"):
                return {
                    "payload": payload,
                    "request_sample": extract_positions_api_request_sample(
                        packet,
                        page,
                        query=query,
                        city_name=city_name,
                        page_no=target_page_no,
                    ),
                }
    return {}


def load_search_items_with_retry(
    page: Any,
    query: str,
    city_name: str,
    page_no: int,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    last_count = 0
    last_pages = 1
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        page.get(build_search_url(query, city_name, page_no))
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        state_payload = extract_page_payload_from_state(extract_initial_state(page))
        items = list(state_payload["items"])
        last_count = int(state_payload["count"])
        last_pages = int(state_payload["pages"])
        current_page = int(state_payload["page_index"])
        if items and current_page == page_no:
            return items, last_count, last_pages
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"智联招聘 {query} - {city_name} 第 {page_no} 页解析失败，准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
    return [], last_count, last_pages


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def build_job_url(item: dict[str, Any]) -> str:
    detail = item.get("jobDetailData") or {}
    base = ((detail.get("position") or {}).get("base") or {}) if isinstance(detail, dict) else {}
    for candidate in [item.get("positionURL"), item.get("positionUrl"), item.get("redirectUrl"), base.get("positionUrl")]:
        url = clean_text(candidate)
        if url.startswith("http"):
            return url.replace("jobs.zhaopin.com", "www.zhaopin.com/jobdetail")
    position_number = clean_text(item.get("number") or base.get("positionNumber"))
    if position_number:
        return f"https://www.zhaopin.com/jobdetail/{position_number}.htm"
    job_id = clean_text(item.get("jobId") or base.get("positionId"))
    if job_id:
        return f"https://www.zhaopin.com/jobdetail/{job_id}.htm"
    return ""


def normalize_job_item(item: dict[str, Any]) -> dict[str, Any]:
    detail = item.get("jobDetailData") or {}
    position = (detail.get("position") or {}) if isinstance(detail, dict) else {}
    base = (position.get("base") or {}) if isinstance(position, dict) else {}
    desc = (position.get("desc") or {}) if isinstance(position, dict) else {}
    work_location = (position.get("workLocation") or {}) if isinstance(position, dict) else {}
    staff = detail.get("staff") or {}
    feature_server = item.get("featureServer") or {}

    title = clean_text(item.get("name") or base.get("positionName"))
    company_name = clean_text(item.get("companyName"))
    city_name = clean_text(item.get("workCity"))
    district_name = clean_text(item.get("cityDistrict") or work_location.get("address"))
    salary_text = clean_text(item.get("salary60") or base.get("salary") or item.get("salaryReal"))
    degree_text = clean_text(item.get("education") or base.get("education"))
    experience_text = clean_text(item.get("workingExp") or base.get("positionWorkingExp"))
    brand_scale = clean_text(item.get("companySize"))
    brand_stage = clean_text((item.get("financingStage") or {}).get("name"))

    tag_values: list[str] = []
    for candidate in [
        clean_text(base.get("workType")),
        clean_text(item.get("workMode")),
        clean_text(item.get("propertyName")),
        clean_text(item.get("industryName")),
    ]:
        if candidate and candidate not in tag_values:
            tag_values.append(candidate)
    for label in (desc.get("labels") or [])[:6]:
        label_text = clean_text(label)
        if label_text and label_text not in tag_values:
            tag_values.append(label_text)

    description_parts: list[str] = []
    description = clean_text(desc.get("description"))
    if description:
        description_parts.append(description)
    label_text = "、".join(clean_text(label) for label in (desc.get("labels") or []) if clean_text(label))
    if label_text:
        description_parts.append(f"技能标签：{label_text}")
    address_text = clean_text(work_location.get("workAddress") or work_location.get("address"))
    if address_text:
        description_parts.append(f"工作地点：{address_text}")
    staff_name = clean_text(staff.get("staffName"))
    staff_job = clean_text(staff.get("hrJob"))
    if staff_name or staff_job:
        description_parts.append(f"招聘方：{staff_name} {staff_job}".strip())
    reply_rate = feature_server.get("staffReplyRate30d")
    if reply_rate not in {None, ""}:
        try:
            description_parts.append(f"30天回复率：{float(reply_rate) * 100:.0f}%")
        except (TypeError, ValueError):
            pass

    source_job_id = clean_text(item.get("number") or base.get("positionNumber") or item.get("jobId") or base.get("positionId"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "company_name": company_name,
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": salary_text,
        "degree_text": degree_text,
        "experience_text": experience_text,
        "brand_scale": brand_scale,
        "brand_stage": brand_stage,
        "job_type": " / ".join(tag_values),
        "source_url": build_job_url(item),
        "official_apply_url": build_job_url(item),
        "description_text": "\n\n".join(part for part in description_parts if part),
        "source_code": "zhilian",
        "status": "active",
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "zhilian") -> dict[str, int]:
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


def run_incremental_update(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    max_pages: int = 2,
    page_size: int = 20,
    output_dir: Path | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    runtime_mode: str = "browser",
    source_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del output_dir, runtime_mode
    configure_stdio()
    ensure_db()

    if ChromiumPage is None:
        raise RuntimeError("未安装 DrissionPage，无法执行智联招聘浏览器采集")

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    normalized_source_options = normalize_source_options(source_options)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 30))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_probe_attempts = 0
    request_probe_successes = 0
    request_page_attempts = 0
    request_page_successes = 0
    seen_page_signatures: set[tuple[str, str, str]] = set()
    seen_job_ids: set[str] = set()
    probed_keys: set[tuple[str, str]] = set()
    resolved_city_codes: dict[str, str] = {}
    request_samples: dict[str, dict[str, Any]] = {}
    zhilian_request_trace: list[dict[str, Any]] = []

    options = build_browser_options()
    page = ChromiumPage(options)
    try:
        emit_progress(progress_callback, "智联招聘采集启动，模式 browser_intercept_api")
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_fetched = 0
                city_new = 0
                city_updated = 0
                city_request_probe_attempts = 0
                city_request_probe_successes = 0
                city_request_page_attempts = 0
                city_request_page_successes = 0
                pages_completed = 0
                stop_reason = ""
                captured_request_sample = False
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                emit_progress(progress_callback, f"智联招聘开始抓取 {query} - {city_name} 第 1 页", query=query, city_name=city_name, page=1)
                list_items, total_items, total_pages = load_search_items_with_retry(
                    page,
                    query,
                    city_name,
                    1,
                    should_stop_callback,
                    progress_callback,
                )
                first_state_payload = extract_page_payload_from_state(extract_initial_state(page))
                if first_state_payload.get("city_code"):
                    resolved_city_codes[city_name] = str(first_state_payload["city_code"])
                for page_no in range(1, target_pages + 1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                    if page_no > 1:
                        emit_progress(progress_callback, f"智联招聘开始抓取 {query} - {city_name} 第 {page_no} 页", query=query, city_name=city_name, page=page_no)
                        request_sample_key = f"{query}|{city_name}"
                        api_result: dict[str, Any] = {}
                        request_sample = request_samples.get(request_sample_key) or {}
                        if page_no > 2 and request_sample and normalized_source_options["prefer_request_pages"]:
                            request_page_attempts += 1
                            city_request_page_attempts += 1
                            api_result = load_positions_api_page_via_request_sample(
                                request_sample,
                                target_page_no=page_no,
                                timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                            )
                            api_payload = api_result.get("payload") if isinstance(api_result, dict) else {}
                            if api_payload.get("items"):
                                request_page_successes += 1
                                city_request_page_successes += 1
                                request_samples[request_sample_key] = api_result.get("request_sample") or request_sample
                                emit_progress(
                                    progress_callback,
                                    f"智联招聘 {query} - {city_name} 第 {page_no} 页 requests 直连成功",
                                    query=query,
                                    city_name=city_name,
                                    page=page_no,
                                )
                            else:
                                emit_progress(
                                    progress_callback,
                                    (
                                        f"智联招聘 {query} - {city_name} 第 {page_no} 页 requests 直连失败，"
                                        f"回退浏览器：{clean_text(api_result.get('reason')) or '未返回职位'}"
                                    ),
                                    query=query,
                                    city_name=city_name,
                                    page=page_no,
                                )
                                api_result = {}
                        if not api_result:
                            api_result = load_positions_api_page_via_click(
                                page,
                                target_page_no=page_no,
                                query=query,
                                city_name=city_name,
                                should_stop_callback=should_stop_callback,
                                progress_callback=progress_callback,
                            )
                        api_payload = api_result.get("payload") if isinstance(api_result, dict) else {}
                        if api_payload.get("items"):
                            list_items = list(api_payload["items"])
                            if api_payload.get("count"):
                                total_items = int(api_payload["count"])
                            if api_payload.get("pages"):
                                total_pages = int(api_payload["pages"])
                            request_sample = api_result.get("request_sample") if isinstance(api_result, dict) else {}
                            if request_sample:
                                captured_request_sample = True
                                request_samples[request_sample_key] = request_sample
                            probe_key = (query, city_name)
                            if (
                                request_sample
                                and normalized_source_options["enable_request_probe"]
                                and probe_key not in probed_keys
                            ):
                                probed_keys.add(probe_key)
                                request_probe_attempts += 1
                                city_request_probe_attempts += 1
                                probe_result = replay_positions_api_sample(
                                    request_sample,
                                    timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                                )
                                if probe_result.get("ok"):
                                    request_probe_successes += 1
                                    city_request_probe_successes += 1
                                    emit_progress(
                                        progress_callback,
                                        (
                                            f"智联招聘 {query} - {city_name} requests 复放探针成功："
                                            f"第 {page_no} 页样本可复放，返回 {probe_result.get('items', 0)} 条"
                                        ),
                                        query=query,
                                        city_name=city_name,
                                        page=page_no,
                                    )
                                else:
                                    emit_progress(
                                        progress_callback,
                                        (
                                            f"智联招聘 {query} - {city_name} requests 复放探针失败："
                                            f"{clean_text(probe_result.get('reason')) or '未返回职位'}"
                                        ),
                                        query=query,
                                        city_name=city_name,
                                        page=page_no,
                                    )
                        else:
                            state_payload = extract_page_payload_from_state(extract_initial_state(page))
                            list_items = list(state_payload["items"])
                            if state_payload.get("count"):
                                total_items = int(state_payload["count"])
                            if state_payload.get("pages"):
                                total_pages = int(state_payload["pages"])
                    if not list_items:
                        stop_reason = "empty"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 第 {page_no} 页未解析到职位", query=query, city_name=city_name, page=page_no)
                        break

                    page_signature = (query, city_name, "|".join(clean_text(item.get("jobId") or item.get("number")) for item in list_items[:5]))
                    if page_signature in seen_page_signatures:
                        stop_reason = "duplicate_page"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 第 {page_no} 页出现重复分页签名，提前结束", query=query, city_name=city_name, page=page_no)
                        break
                    seen_page_signatures.add(page_signature)

                    page_jobs = [normalize_job_item(item) for item in list_items[:target_page_size]]
                    page_jobs = [job for job in page_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
                    if not page_jobs:
                        stop_reason = "empty_normalized"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 第 {page_no} 页没有可入库职位", query=query, city_name=city_name, page=page_no)
                        break

                    all_seen_before_page = all(clean_text(job.get("source_job_id")) in seen_job_ids for job in page_jobs)
                    stats = save_to_db(page_jobs, source_code="zhilian")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    city_fetched += len(page_jobs)
                    city_new += stats["new"]
                    city_updated += stats["updated"]
                    pages_completed += 1
                    seen_job_ids.update(clean_text(job.get("source_job_id")) for job in page_jobs if clean_text(job.get("source_job_id")))
                    emit_progress(
                        progress_callback,
                        f"智联招聘 {query} - {city_name} 第 {page_no} 页完成：抓取 {len(page_jobs)} / 总数 {total_items}，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                    )

                    if page_no >= max(1, total_pages):
                        stop_reason = "end_page"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 已到最后一页，共 {total_pages} 页", query=query, city_name=city_name, page=page_no)
                        break
                    if city_fetched >= total_items > 0:
                        stop_reason = "covered_total"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 已覆盖该检索结果总数 {total_items}", query=query, city_name=city_name, page=page_no)
                        break
                    if all_seen_before_page:
                        stop_reason = "all_seen"
                        emit_progress(progress_callback, f"智联招聘 {query} - {city_name} 第 {page_no} 页全部为已处理职位，提前结束", query=query, city_name=city_name, page=page_no)
                        break

                if not stop_reason:
                    stop_reason = "target_pages_reached"
                zhilian_request_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "city_code": str(resolved_city_codes.get(city_name) or ""),
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "total_items": int(total_items or 0),
                        "fetched_count": city_fetched,
                        "new_count": city_new,
                        "updated_count": city_updated,
                        "request_probe_attempts": city_request_probe_attempts,
                        "request_probe_successes": city_request_probe_successes,
                        "request_page_attempts": city_request_page_attempts,
                        "request_page_successes": city_request_page_successes,
                        "captured_request_sample": captured_request_sample,
                    }
                )

        emit_progress(progress_callback, f"智联招聘采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条")
        return {
            "total_fetched": total_fetched,
            "new_to_db": total_new,
            "updated": total_updated,
            "queries": len(normalized_queries),
            "cities": len(normalized_cities),
            "runtime_mode": "browser",
            "detail_mode": "intercept_api",
            "resolved_city_codes": resolved_city_codes,
            "request_probe_attempts": request_probe_attempts,
            "request_probe_successes": request_probe_successes,
            "request_page_attempts": request_page_attempts,
            "request_page_successes": request_page_successes,
            "captured_request_samples": len(request_samples),
            "zhilian_request_trace": zhilian_request_trace,
        }
    finally:
        try:
            page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    result = run_incremental_update()
    print(json.dumps(result, ensure_ascii=False))