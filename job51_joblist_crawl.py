from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
BASE_URL = "https://we.51job.com/pc/search"
CITY_DICT_URL = "https://js.51jobcdn.com/in/js/2023/dd/dd_city.json"
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
        emit_progress(progress_callback, "收到取消信号，准备停止前程无忧采集", **context)
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
        raise RuntimeError("未安装 DrissionPage，无法执行前程无忧浏览器采集")
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


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def fetch_city_code_map() -> dict[str, str]:
    response = requests.get(CITY_DICT_URL, params={"t": int(time.time())}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    city_map: dict[str, str] = {"全国": ""}

    def visit(items: list[dict[str, Any]]) -> None:
        for item in items:
            value = clean_text(item.get("value"))
            code = clean_text(item.get("code"))
            if value and code and value not in city_map:
                city_map[value] = code
            children = item.get("items") or []
            if isinstance(children, list) and children:
                visit([child for child in children if isinstance(child, dict)])

    visit([item for item in (payload.get("items") or []) if isinstance(item, dict)])
    return city_map


def build_search_url(query: str, city_code: str) -> str:
    params: dict[str, Any] = {"keyword": query}
    if city_code:
        params["jobArea"] = city_code
    return f"{BASE_URL}?{urlencode(params)}"


def parse_list_response_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"items": [], "page_num": 1, "total_count": 0}
    result = body.get("resultbody") or {}
    job_info = result.get("job") or {}
    return {
        "items": [item for item in (job_info.get("items") or []) if isinstance(item, dict)],
        "page_num": 1,
        "total_count": int(job_info.get("totalCount") or job_info.get("total") or 0),
    }


def extract_list_payload(packet: Any) -> dict[str, Any]:
    response = getattr(packet, "response", None)
    body = getattr(response, "body", None)
    payload = parse_list_response_body(body)
    request = getattr(packet, "request", None)
    request_url = str(getattr(request, "url", ""))
    page_num = 1
    if "pageNum=" in request_url:
        try:
            page_num = int(request_url.split("pageNum=", 1)[1].split("&", 1)[0])
        except ValueError:
            page_num = 1
    return {
        "items": list(payload.get("items") or []),
        "page_num": page_num,
        "total_count": int(payload.get("total_count") or 0),
    }


def build_cookie_header(page: Any) -> str:
    cookies = page.cookies(all_domains=True, all_info=False)
    if isinstance(cookies, dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if clean_text(key))
    return str(cookies or "")


def parse_cookie_string(cookie_value: str) -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    for chunk in str(cookie_value or "").split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = clean_text(key)
        value = clean_text(value)
        if key:
            cookie_map[key] = value
    return cookie_map


def extract_cookie_map(page: Any) -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    cookies = page.cookies(all_domains=True, all_info=False)
    if isinstance(cookies, dict):
        for key, value in cookies.items():
            cookie_key = clean_text(key)
            cookie_value = clean_text(value)
            if cookie_key:
                cookie_map[cookie_key] = cookie_value
    elif isinstance(cookies, list):
        for item in cookies:
            if not isinstance(item, dict):
                continue
            cookie_key = clean_text(item.get("name"))
            cookie_value = clean_text(item.get("value"))
            if cookie_key:
                cookie_map[cookie_key] = cookie_value
    else:
        cookie_map.update(parse_cookie_string(str(cookies or "")))
    try:
        document_cookie = clean_text(page.run_js("return document.cookie"))
    except Exception:
        document_cookie = ""
    cookie_map.update(parse_cookie_string(document_cookie))
    return cookie_map


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
    normalized.setdefault("Origin", "https://we.51job.com")
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


def extract_list_request_sample(packet: Any, page: Any, *, query: str, city_code: str) -> dict[str, Any]:
    request = getattr(packet, "request", None)
    request_url = clean_text(getattr(request, "url", ""))
    if not request_url:
        return {}
    referer = clean_text(getattr(page, "url", "")) or build_search_url(query, city_code)
    return {
        "method": clean_text(getattr(request, "method", "GET")) or "GET",
        "url": request_url,
        "headers": normalize_request_headers(getattr(request, "headers", None), cookie_header=build_cookie_header(page), referer=referer),
        "query": query,
        "city_code": city_code,
        "referer": referer,
    }


def build_request_sample_for_page(sample: dict[str, Any], target_page_no: int) -> dict[str, Any]:
    cloned = dict(sample)
    request_url = clean_text(sample.get("url"))
    if not request_url:
        return cloned
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(request_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["pageNum"] = str(target_page_no)
    cloned["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))
    return cloned


def replay_list_api_sample(sample: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    return replay_list_api_sample_with_session(sample, timeout_seconds=timeout_seconds)


def build_preheated_session(page: Any, sample: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    headers = dict(sample.get("headers") or {}) if isinstance(sample.get("headers"), dict) else {}
    headers.pop("Cookie", None)
    headers.pop("cookie", None)
    session.headers.update(headers)
    cookie_map = extract_cookie_map(page)
    if not cookie_map:
        cookie_map = parse_cookie_string(clean_text((sample.get("headers") or {}).get("Cookie") or (sample.get("headers") or {}).get("cookie")))
    if cookie_map:
        session.cookies.update(cookie_map)
    return session


def replay_list_api_sample_with_session(
    sample: dict[str, Any],
    *,
    timeout_seconds: float,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    request_url = clean_text(sample.get("url"))
    if not request_url:
        return {"ok": False, "reason": "missing_url"}
    headers = sample.get("headers") if isinstance(sample.get("headers"), dict) else {}
    try:
        client = session or requests
        response = client.get(request_url, headers=headers if session is None else None, timeout=timeout_seconds)
        response.raise_for_status()
        try:
            response_json = response.json()
        except ValueError:
            return {
                "ok": False,
                "reason": "non_json_response",
                "status_code": int(getattr(response, "status_code", 0) or 0),
                "content_type": clean_text(response.headers.get("Content-Type")),
                "body_preview": clean_text(response.text)[:120],
            }
        payload = parse_list_response_body(response_json)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    return {
        "ok": bool(payload.get("items")),
        "items": len(payload.get("items") or []),
        "items_payload": list(payload.get("items") or []),
        "total_count": int(payload.get("total_count") or 0),
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "content_type": clean_text(response.headers.get("Content-Type")),
        "reason": "empty_items" if not payload.get("items") else "",
        "body_preview": "",
    }


def replay_list_api_sample_with_browser_prewarm(page: Any, sample: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    session = build_preheated_session(page, sample)
    result = replay_list_api_sample_with_session(sample, timeout_seconds=timeout_seconds, session=session)
    result["browser_cookie_count"] = len(session.cookies)
    return result


def load_page_via_request_sample(
    page: Any,
    request_sample: dict[str, Any],
    *,
    target_page_no: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    updated_sample = build_request_sample_for_page(request_sample, target_page_no)
    result = replay_list_api_sample_with_browser_prewarm(page, updated_sample, timeout_seconds=timeout_seconds)
    if not result.get("ok"):
        return {"payload": {}, "request_sample": updated_sample, "reason": clean_text(result.get("reason")), "probe": result}
    payload = {
        "items": list((result.get("items_payload") or [])),
        "page_num": target_page_no,
        "total_count": int(result.get("total_count") or 0),
    }
    return {"payload": payload, "request_sample": updated_sample, "reason": "", "probe": result}


def capture_current_page_payload(
    page: Any,
    *,
    query: str,
    city_code: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query)
        page.listen.start("search-pc")
        page.get(build_search_url(query, city_code))
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, page=1)
        packets = list(page.listen.steps(count=40, timeout=4))
        for packet in reversed(packets):
            request = getattr(packet, "request", None)
            request_url = str(getattr(request, "url", ""))
            if "api/job/search-pc" in request_url:
                payload = extract_list_payload(packet)
                if payload.get("items"):
                    payload["request_sample"] = extract_list_request_sample(packet, page, query=query, city_code=city_code)
                    return payload
        if attempt < MAX_RETRIES:
            emit_progress(progress_callback, f"前程无忧 {query} 首屏接口未命中，准备第 {attempt + 1} 次重试", query=query, page=1)
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, page=1)
    return {"items": [], "page_num": 1, "total_count": 0}


def load_page_via_click(
    page: Any,
    *,
    target_page_no: int,
    query: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, page=target_page_no)
    button = None
    for locator in [f"tag:li@@text()={target_page_no}", f"tag:span@@text()={target_page_no}", f"tag:a@@text()={target_page_no}"]:
        button = page.ele(locator, timeout=1)
        if button is not None:
            break
    if button is None:
        return {"items": [], "page_num": target_page_no - 1, "total_count": 0}
    page.listen.start("search-pc")
    button.click()
    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, page=target_page_no)
    packets = list(page.listen.steps(count=40, timeout=4))
    for packet in reversed(packets):
        request = getattr(packet, "request", None)
        request_url = str(getattr(request, "url", ""))
        if "api/job/search-pc" in request_url:
            payload = extract_list_payload(packet)
            if payload.get("items"):
                payload["request_sample"] = extract_list_request_sample(packet, page, query=query, city_code="")
                return payload
    return {"items": [], "page_num": target_page_no - 1, "total_count": 0}


def split_city_district(item: dict[str, Any]) -> tuple[str, str]:
    detail = item.get("jobAreaLevelDetail") or {}
    city_name = clean_text(detail.get("cityString"))
    district_name = clean_text(detail.get("districtString"))
    if city_name or district_name:
        return city_name, district_name
    area_text = clean_text(item.get("jobAreaString"))
    if "·" in area_text:
        city_text, district_text = area_text.split("·", 1)
        return clean_text(city_text), clean_text(district_text)
    return area_text, ""


def normalize_job_item(item: dict[str, Any]) -> dict[str, Any]:
    city_name, district_name = split_city_district(item)

    tag_values: list[str] = []
    for candidate in [clean_text(item.get("termStr")), clean_text(item.get("industryType1Str")), clean_text(item.get("industryType2Str"))]:
        if candidate and candidate not in tag_values:
            tag_values.append(candidate)
    for label in (item.get("jobTags") or [])[:10]:
        label_text = clean_text(label)
        if label_text and label_text not in tag_values:
            tag_values.append(label_text)

    description_parts: list[str] = []
    job_desc = clean_text(item.get("jobDescribe"))
    if job_desc:
        description_parts.append(job_desc)
    hr_name = clean_text(item.get("hrName"))
    hr_position = clean_text(item.get("hrPosition"))
    if hr_name or hr_position:
        description_parts.append(f"招聘方：{hr_name} {hr_position}".strip())
    hr_labels = [clean_text(label) for label in (item.get("hrLabels") or []) if clean_text(label)]
    if hr_labels:
        description_parts.append(f"HR标签：{'、'.join(hr_labels)}")
    welfare_labels = [clean_text((label or {}).get("chineseTitle")) for label in (item.get("jobWelfareCodeDataList") or []) if clean_text((label or {}).get("chineseTitle"))]
    if welfare_labels:
        description_parts.append(f"福利：{'、'.join(welfare_labels[:12])}")

    return {
        "source_job_id": clean_text(item.get("jobId")),
        "title": clean_text(item.get("jobName")),
        "company_name": clean_text(item.get("fullCompanyName") or item.get("companyName")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(item.get("provideSalaryString")),
        "degree_text": clean_text(item.get("degreeString")),
        "experience_text": clean_text(item.get("workYearString")),
        "brand_scale": clean_text(item.get("companySizeString")),
        "brand_stage": clean_text(item.get("companyTypeString")),
        "job_type": " / ".join(tag_values),
        "source_url": clean_text(item.get("jobHref")),
        "official_apply_url": clean_text(item.get("jobHref")),
        "description_text": "\n\n".join(part for part in description_parts if part),
        "source_code": "job51",
        "status": "active",
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "job51") -> dict[str, int]:
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
        raise RuntimeError("未安装 DrissionPage，无法执行前程无忧浏览器采集")

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    normalized_source_options = normalize_source_options(source_options)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 30))
    city_code_map = fetch_city_code_map()

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_probe_attempts = 0
    request_probe_successes = 0
    preheated_probe_attempts = 0
    preheated_probe_successes = 0
    request_page_attempts = 0
    request_page_successes = 0
    seen_page_signatures: set[tuple[str, str, str]] = set()
    seen_job_ids: set[str] = set()
    resolved_city_codes: dict[str, str] = {}
    captured_request_samples: dict[str, dict[str, Any]] = {}
    request_ready_keys: set[str] = set()
    job51_request_trace: list[dict[str, Any]] = []

    options = build_browser_options()
    page = ChromiumPage(options)
    try:
        emit_progress(progress_callback, "前程无忧采集启动，模式 browser_intercept_api")
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_code = clean_text(city_code_map.get(city_name))
                city_fetched = 0
                city_new = 0
                city_updated = 0
                city_request_probe_attempts = 0
                city_request_probe_successes = 0
                city_preheated_probe_attempts = 0
                city_preheated_probe_successes = 0
                city_request_page_attempts = 0
                city_request_page_successes = 0
                pages_completed = 0
                stop_reason = ""
                captured_request_sample = False
                resolved_city_codes[city_name] = city_code
                emit_progress(progress_callback, f"前程无忧开始抓取 {query} - {city_name} 第 1 页", query=query, city_name=city_name, page=1)
                current_payload = capture_current_page_payload(
                    page,
                    query=query,
                    city_code=city_code,
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                initial_request_sample = current_payload.get("request_sample") if isinstance(current_payload, dict) else {}
                if initial_request_sample:
                    captured_request_sample = True
                    captured_request_samples[f"{query}|{city_name}"] = initial_request_sample
                    if normalized_source_options["enable_request_probe"]:
                        request_probe_attempts += 1
                        city_request_probe_attempts += 1
                        probe_result = replay_list_api_sample(
                            initial_request_sample,
                            timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                        )
                        if probe_result.get("ok"):
                            request_probe_successes += 1
                            city_request_probe_successes += 1
                            emit_progress(
                                progress_callback,
                                f"前程无忧 {query} - {city_name} requests 复放探针成功：返回 {probe_result.get('items', 0)} 条",
                                query=query,
                                city_name=city_name,
                                page=1,
                            )
                        else:
                            emit_progress(
                                progress_callback,
                                (
                                    f"前程无忧 {query} - {city_name} requests 复放探针失败：{clean_text(probe_result.get('reason')) or '未返回职位'}；"
                                    f"status={probe_result.get('status_code', 0)}；content_type={clean_text(probe_result.get('content_type')) or '-'}；"
                                    f"body={clean_text(probe_result.get('body_preview')) or '-'}"
                                ),
                                query=query,
                                city_name=city_name,
                                page=1,
                            )
                            if clean_text(probe_result.get("reason")) == "non_json_response":
                                preheated_probe_attempts += 1
                                city_preheated_probe_attempts += 1
                                warmed_result = replay_list_api_sample_with_browser_prewarm(
                                    page,
                                    initial_request_sample,
                                    timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                                )
                                if warmed_result.get("ok"):
                                    preheated_probe_successes += 1
                                    city_preheated_probe_successes += 1
                                    request_ready_keys.add(f"{query}|{city_name}")
                                    emit_progress(
                                        progress_callback,
                                        (
                                            f"前程无忧 {query} - {city_name} 预热 Cookie 后 requests 复放成功："
                                            f"返回 {warmed_result.get('items', 0)} 条，browser_cookies={warmed_result.get('browser_cookie_count', 0)}"
                                        ),
                                        query=query,
                                        city_name=city_name,
                                        page=1,
                                    )
                                else:
                                    emit_progress(
                                        progress_callback,
                                        (
                                            f"前程无忧 {query} - {city_name} 预热 Cookie 后仍失败：{clean_text(warmed_result.get('reason')) or '未返回职位'}；"
                                            f"status={warmed_result.get('status_code', 0)}；content_type={clean_text(warmed_result.get('content_type')) or '-'}；"
                                            f"body={clean_text(warmed_result.get('body_preview')) or '-'}；browser_cookies={warmed_result.get('browser_cookie_count', 0)}"
                                        ),
                                        query=query,
                                        city_name=city_name,
                                        page=1,
                                    )
                total_count = int(current_payload.get("total_count") or 0)
                for page_no in range(1, target_pages + 1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                    if page_no > 1:
                        emit_progress(progress_callback, f"前程无忧开始抓取 {query} - {city_name} 第 {page_no} 页", query=query, city_name=city_name, page=page_no)
                        request_key = f"{query}|{city_name}"
                        request_sample = captured_request_samples.get(request_key) or {}
                        request_result: dict[str, Any] = {}
                        if (
                            normalized_source_options["prefer_request_pages"]
                            and request_key in request_ready_keys
                            and request_sample
                            and page_no in {2, 3}
                        ):
                            request_page_attempts += 1
                            city_request_page_attempts += 1
                            request_result = load_page_via_request_sample(
                                page,
                                request_sample,
                                target_page_no=page_no,
                                timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                            )
                            request_payload = request_result.get("payload") if isinstance(request_result, dict) else {}
                            if request_payload.get("items"):
                                request_page_successes += 1
                                city_request_page_successes += 1
                                current_payload = request_payload
                                captured_request_samples[request_key] = request_result.get("request_sample") or request_sample
                                captured_request_sample = True
                                emit_progress(
                                    progress_callback,
                                    f"前程无忧 {query} - {city_name} 第 {page_no} 页 requests 直连成功",
                                    query=query,
                                    city_name=city_name,
                                    page=page_no,
                                )
                            else:
                                emit_progress(
                                    progress_callback,
                                    (
                                        f"前程无忧 {query} - {city_name} 第 {page_no} 页 requests 直连失败，回退浏览器："
                                        f"{clean_text(request_result.get('reason')) or '未返回职位'}"
                                    ),
                                    query=query,
                                    city_name=city_name,
                                    page=page_no,
                                )
                                request_result = {}
                        if not request_result:
                            current_payload = load_page_via_click(
                                page,
                                target_page_no=page_no,
                                query=query,
                                should_stop_callback=should_stop_callback,
                                progress_callback=progress_callback,
                            )
                        if current_payload.get("total_count"):
                            total_count = int(current_payload["total_count"])
                    request_sample = current_payload.get("request_sample") if isinstance(current_payload, dict) else {}
                    if request_sample:
                        captured_request_sample = True
                        captured_request_samples[f"{query}|{city_name}"] = request_sample
                    raw_items = list(current_payload.get("items") or [])
                    if not raw_items:
                        stop_reason = "empty"
                        emit_progress(progress_callback, f"前程无忧 {query} - {city_name} 第 {page_no} 页未解析到职位", query=query, city_name=city_name, page=page_no)
                        break

                    page_signature = (query, city_name, "|".join(clean_text(item.get("jobId")) for item in raw_items[:5]))
                    if page_signature in seen_page_signatures:
                        stop_reason = "duplicate_page"
                        emit_progress(progress_callback, f"前程无忧 {query} - {city_name} 第 {page_no} 页出现重复分页签名，提前结束", query=query, city_name=city_name, page=page_no)
                        break
                    seen_page_signatures.add(page_signature)

                    page_jobs = [normalize_job_item(item) for item in raw_items[:target_page_size]]
                    page_jobs = [job for job in page_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
                    if not page_jobs:
                        stop_reason = "empty_normalized"
                        emit_progress(progress_callback, f"前程无忧 {query} - {city_name} 第 {page_no} 页没有可入库职位", query=query, city_name=city_name, page=page_no)
                        break

                    all_seen_before_page = all(clean_text(job.get("source_job_id")) in seen_job_ids for job in page_jobs)
                    stats = save_to_db(page_jobs, source_code="job51")
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
                        f"前程无忧 {query} - {city_name} 第 {page_no} 页完成：抓取 {len(page_jobs)} / 总数 {total_count}，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                    )
                    if all_seen_before_page:
                        stop_reason = "all_seen"
                        emit_progress(progress_callback, f"前程无忧 {query} - {city_name} 第 {page_no} 页全部为已处理职位，提前结束", query=query, city_name=city_name, page=page_no)
                        break

                if not stop_reason:
                    stop_reason = "target_pages_reached"
                job51_request_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "city_code": city_code,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "total_items": total_count,
                        "fetched_count": city_fetched,
                        "new_count": city_new,
                        "updated_count": city_updated,
                        "request_probe_attempts": city_request_probe_attempts,
                        "request_probe_successes": city_request_probe_successes,
                        "preheated_probe_attempts": city_preheated_probe_attempts,
                        "preheated_probe_successes": city_preheated_probe_successes,
                        "request_page_attempts": city_request_page_attempts,
                        "request_page_successes": city_request_page_successes,
                        "captured_request_sample": captured_request_sample,
                    }
                )

        emit_progress(progress_callback, f"前程无忧采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条")
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
            "preheated_probe_attempts": preheated_probe_attempts,
            "preheated_probe_successes": preheated_probe_successes,
            "request_page_attempts": request_page_attempts,
            "request_page_successes": request_page_successes,
            "captured_request_samples": len(captured_request_samples),
            "job51_request_trace": job51_request_trace,
        }
    finally:
        try:
            page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    result = run_incremental_update()
    print(json.dumps(result, ensure_ascii=False))