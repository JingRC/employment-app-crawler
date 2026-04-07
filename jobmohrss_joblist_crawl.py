from __future__ import annotations

import hashlib
import html
import json
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

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
WEB_BASE_URL = "http://job.mohrss.gov.cn"
LIST_URL = f"{WEB_BASE_URL}/cjobs/jobinfolist/listJobinfolist"
DETAIL_URL_TEMPLATE = WEB_BASE_URL + "/cjobs/jobinfolist/cb21/showgw?id={job_id}"
DEFAULT_QUERIES = ["Java", "Python", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "青岛"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 15.0,
    "sleep_seconds": 0.0,
    "search_type": "2",
}
REQUEST_HEADERS = {
    "Referer": f"{WEB_BASE_URL}/cjobs/jobinfolist/listJobinfolistIndex",
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
        emit_progress(progress_callback, "收到取消信号，准备停止中国公共招聘网采集", **context)
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
    detail_mode = clean_text(options.get("detail_mode") or DEFAULT_SOURCE_OPTIONS["detail_mode"]).lower() or "detail_html"
    search_type = clean_text(options.get("search_type") or DEFAULT_SOURCE_OPTIONS["search_type"]) or "2"
    try:
        request_timeout_seconds = float(options.get("request_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    except (TypeError, ValueError):
        request_timeout_seconds = float(DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    try:
        sleep_seconds = float(options.get("sleep_seconds") or DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    except (TypeError, ValueError):
        sleep_seconds = float(DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    return {
        "detail_mode": detail_mode if detail_mode in {"list_only", "detail_html"} else "detail_html",
        "request_timeout_seconds": max(5.0, min(request_timeout_seconds, 60.0)),
        "sleep_seconds": max(0.0, min(sleep_seconds, 5.0)),
        "search_type": search_type if search_type in {"1", "2", "gw", "dw"} else "2",
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
        raise RuntimeError("未安装 requests，无法执行中国公共招聘网采集")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def simplify_area_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    suffixes = ["特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "自治州", "自治县", "地区", "盟", "省", "市", "县", "区"]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return clean_text(text)


def city_matches(target_city: str, *texts: Any) -> bool:
    normalized_target = simplify_area_name(target_city)
    if not normalized_target or normalized_target == "全国":
        return True
    for value in texts:
        text = clean_text(value)
        simplified = simplify_area_name(value)
        for candidate in {text, simplified}:
            if candidate and (normalized_target in candidate or candidate in normalized_target):
                return True
    return False


def normalize_salary_text(low_salary: Any, high_salary: Any) -> str:
    low = clean_text(low_salary)
    high = clean_text(high_salary)
    if low.isdigit() and high.isdigit():
        low_value = int(low)
        high_value = int(high)
        if low_value > 0 and high_value > low_value:
            return f"{low_value}-{high_value}元/月"
        if low_value > 0:
            return f"{low_value}元以上/月"
        if high_value > 0:
            return f"{high_value}元/月"
    if low.isdigit() and int(low) > 0:
        return f"{int(low)}元以上/月"
    return "面议"


def _extract_findjoblist_json(html_text: str) -> list[dict[str, Any]]:
    match = re.search(r'id="findjoblist"[^>]*value="([^"]*)"', html_text, re.I | re.S)
    if not match:
        return []
    raw_value = html.unescape(match.group(1))
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)]


def parse_job_list_page(html_text: str) -> dict[str, Any]:
    items = _extract_findjoblist_json(html_text)
    total_count_match = re.search(r'name="totalcount"[^>]*value="(\d+)"', html_text, re.I)
    total_pages_match = re.search(r'name="totalpages"[^>]*value="(\d+)"', html_text, re.I)
    page_no_match = re.search(r'name="pageNo"[^>]*value="(\d+)"', html_text, re.I)
    return {
        "items": items,
        "page_no": int(page_no_match.group(1)) if page_no_match else 1,
        "page_size": len(items),
        "total_pages": int(total_pages_match.group(1)) if total_pages_match else 0,
        "total_count": int(total_count_match.group(1)) if total_count_match else 0,
    }


def fetch_job_list_page(
    session: requests.Session,
    *,
    query: str,
    page_no: int,
    search_type: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    params = {
        "pageNo": page_no,
        "orderType": "score",
        "searchtype": search_type,
        "textfield": query,
    }
    response = session.get(LIST_URL, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    return parse_job_list_page(response.text)


def fetch_job_detail_html(session: requests.Session, *, job_id: str, timeout_seconds: float) -> str:
    if not job_id:
        return ""
    response = session.get(DETAIL_URL_TEMPLATE.format(job_id=job_id), timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def extract_labeled_value(text: str, label: str, next_labels: list[str]) -> str:
    start_index = text.find(label)
    if start_index < 0:
        return ""
    start_index += len(label)
    candidates = [text.find(next_label, start_index) for next_label in next_labels if text.find(next_label, start_index) >= 0]
    end_index = min(candidates) if candidates else len(text)
    return clean_text(text[start_index:end_index])


def parse_detail_html(html_text: str) -> dict[str, Any]:
    if not html_text:
        return {}
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析中国公共招聘网详情页")
    soup = BeautifulSoup(html_text, "html.parser")
    body_text = clean_text(soup.get_text("\n", strip=True))
    headings = [clean_text(node.get_text(" ", strip=True)) for node in soup.select("h1, h2, h3, .jobName, .zwname") if clean_text(node.get_text(" ", strip=True))]
    title = headings[0] if headings else ""
    company_name = extract_labeled_value(body_text, "招聘单位：", ["学历要求：", "提供住宿：", "发布机构："])
    degree_text = extract_labeled_value(body_text, "学历要求：", ["提供住宿：", "发布机构：", "工作性质："])
    accommodation = extract_labeled_value(body_text, "提供住宿：", ["发布机构：", "工作性质："])
    publisher = extract_labeled_value(body_text, "发布机构：", ["工作性质：", "工作地点："])
    job_type = extract_labeled_value(body_text, "工作性质：", ["工作地点：", "岗位描述"])
    address_text = extract_labeled_value(body_text, "工作地点：", ["岗位描述", "单位简介", "联系方式"])
    description_text = extract_labeled_value(body_text, "岗位描述", ["单位简介", "联系方式"])
    company_intro = extract_labeled_value(body_text, "单位简介", ["联系方式"])
    contact_person = extract_labeled_value(body_text, "联 系 人 ：", ["联 系 电 话：", "邮 箱："])
    contact_phone = extract_labeled_value(body_text, "联 系 电 话：", ["邮 箱："])
    email = extract_labeled_value(body_text, "邮 箱：", [])
    company_link_match = re.search(r"/cjobs/jobinfolist/cb21/showdw\?id=\d+", html_text)
    company_detail_url = WEB_BASE_URL + company_link_match.group(0) if company_link_match else ""
    return {
        "title": title,
        "company_name": company_name,
        "degree_text": degree_text,
        "job_type": job_type,
        "address_text": address_text,
        "description_text": description_text,
        "company_intro": company_intro,
        "publisher": publisher,
        "accommodation": accommodation,
        "contact_person": contact_person,
        "contact_phone": contact_phone,
        "email": email,
        "company_detail_url": company_detail_url,
    }


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None, *, target_city: str = "") -> dict[str, Any]:
    detail = detail_item or {}
    job_id = clean_text(item.get("acb200"))
    detail_url = DETAIL_URL_TEMPLATE.format(job_id=job_id) if job_id else LIST_URL
    city_name = clean_text(item.get("aab302") or item.get("area_") or "")
    if not city_name and target_city and target_city != "全国":
        city_name = clean_text(target_city)
    address_text = clean_text(detail.get("address_text") or item.get("acb202"))
    company_name = clean_text(detail.get("company_name"))
    description_lines = [clean_text(detail.get("description_text"))]
    if clean_text(detail.get("company_intro")) and clean_text(detail.get("company_intro")) != "暂无介绍":
        description_lines.append(f"单位简介：{clean_text(detail.get('company_intro'))}")
    if clean_text(detail.get("publisher")):
        description_lines.append(f"发布机构：{clean_text(detail.get('publisher'))}")
    if clean_text(detail.get("accommodation")):
        description_lines.append(f"提供住宿：{clean_text(detail.get('accommodation'))}")
    if clean_text(detail.get("contact_person")):
        description_lines.append(f"联系人：{clean_text(detail.get('contact_person'))}")
    if clean_text(detail.get("contact_phone")):
        description_lines.append(f"联系电话：{clean_text(detail.get('contact_phone'))}")
    if clean_text(detail.get("email")):
        description_lines.append(f"邮箱：{clean_text(detail.get('email'))}")
    description_text = clean_text("\n".join([line for line in description_lines if clean_text(line)]))
    return {
        "source_job_id": job_id,
        "title": clean_text(detail.get("title") or item.get("aca112")),
        "company_name": company_name,
        "city_name": city_name,
        "district_name": address_text if address_text and address_text != city_name else clean_text(item.get("area_") or city_name),
        "salary_text": normalize_salary_text(item.get("acb241"), item.get("acb242")),
        "degree_text": clean_text(detail.get("degree_text")),
        "experience_text": "",
        "brand_scale": clean_text(item.get("acb240")),
        "brand_stage": "",
        "job_type": clean_text(detail.get("job_type")),
        "source_url": detail_url,
        "official_apply_url": clean_text(item.get("ace760") or detail_url),
        "description_text": description_text,
        "address_text": address_text,
        "publisher": clean_text(detail.get("publisher") or item.get("org_")),
        "contact_person": clean_text(detail.get("contact_person") or item.get("aae004")),
        "contact_phone": clean_text(detail.get("contact_phone") or item.get("aae005")),
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "jobmohrss") -> dict[str, int]:
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
    max_pages: int,
    detail_mode: str,
    search_type: str,
    timeout_seconds: float,
    sleep_seconds: float,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    logical_pages: list[list[dict[str, Any]]] = []
    matched_jobs: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    total_pages = 0
    total_count = 0
    upstream_page_size = 0

    for page_no in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        payload = fetch_job_list_page(
            session,
            query=query,
            page_no=page_no,
            search_type=search_type,
            timeout_seconds=timeout_seconds,
        )
        items = list(payload.get("items") or [])
        total_pages = int(payload.get("total_pages") or total_pages)
        total_count = int(payload.get("total_count") or total_count)
        upstream_page_size = int(payload.get("page_size") or upstream_page_size)
        if not items:
            break

        page_jobs: list[dict[str, Any]] = []
        for raw_item in items:
            job_id = clean_text(raw_item.get("acb200"))
            if not job_id or job_id in seen_job_ids:
                continue
            detail_item: dict[str, Any] = {}
            if detail_mode == "detail_html":
                html_text = fetch_job_detail_html(session, job_id=job_id, timeout_seconds=timeout_seconds)
                detail_item = parse_detail_html(html_text)
            job = normalize_job_item(raw_item, detail_item, target_city=city_name)
            if not clean_text(job.get("company_name")):
                continue
            if city_name != "全国" and not city_matches(city_name, job.get("city_name"), job.get("district_name"), job.get("address_text")):
                continue
            seen_job_ids.add(job_id)
            page_jobs.append(job)
            matched_jobs.append(job)
        emit_progress(
            progress_callback,
            f"中国公共招聘网 {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条",
            query=query,
            city_name=city_name,
            page=page_no,
            source_code="jobmohrss",
        )
        if page_jobs:
            logical_pages.append(page_jobs)
        if sleep_seconds > 0:
            safe_sleep(sleep_seconds, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        if total_pages > 0 and page_no >= total_pages:
            break

    return {
        "pages": logical_pages,
        "matched_jobs": matched_jobs,
        "api_pages": min(max_pages, total_pages if total_pages > 0 else max_pages),
        "total_count": total_count,
        "total_pages": total_pages,
        "upstream_page_size": upstream_page_size,
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
    del output_dir, runtime_mode, page_size
    configure_stdio()
    ensure_db()
    if requests is None:
        raise RuntimeError("未安装 requests，无法执行中国公共招聘网采集")

    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 10))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    fallback_to_national_locations: list[str] = []
    empty_result_locations: list[str] = []
    request_trace: list[dict[str, Any]] = []

    session = build_session()
    emit_progress(progress_callback, "中国公共招聘网采集启动，模式 requests_html", source_code="jobmohrss")
    try:
        for query in normalized_queries:
            for city_name in normalized_cities:
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                trace_item: dict[str, Any] = {
                    "query": query,
                    "location_name": city_name,
                    "status": "resolved" if city_name == "全国" else "fallback_national",
                    "target_pages": target_pages,
                    "api_pages_used": 0,
                    "upstream_total_count": 0,
                    "upstream_total_pages": 0,
                    "upstream_page_size": 0,
                    "logical_pages": 0,
                    "fetched_count": 0,
                    "new_count": 0,
                    "updated_count": 0,
                }
                if city_name != "全国" and city_name not in fallback_to_national_locations:
                    fallback_to_national_locations.append(city_name)

                emit_progress(
                    progress_callback,
                    f"中国公共招聘网开始抓取 {query} - {city_name}（关键词检索 + 地区文本过滤）",
                    query=query,
                    city_name=city_name,
                    page=1,
                    source_code="jobmohrss",
                )
                collect_result = collect_filtered_jobs(
                    session,
                    query=query,
                    city_name=city_name,
                    max_pages=target_pages,
                    detail_mode=str(options["detail_mode"]),
                    search_type=str(options["search_type"]),
                    timeout_seconds=float(options["request_timeout_seconds"]),
                    sleep_seconds=float(options["sleep_seconds"]),
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                logical_pages = [page_jobs for page_jobs in (collect_result.get("pages") or []) if page_jobs]
                trace_item["api_pages_used"] = int(collect_result.get("api_pages") or 0)
                trace_item["upstream_total_count"] = int(collect_result.get("total_count") or 0)
                trace_item["upstream_total_pages"] = int(collect_result.get("total_pages") or 0)
                trace_item["upstream_page_size"] = int(collect_result.get("upstream_page_size") or 0)
                trace_item["logical_pages"] = len(logical_pages)

                if not logical_pages:
                    trace_item["status"] = "empty"
                    request_trace.append(trace_item)
                    if city_name not in empty_result_locations:
                        empty_result_locations.append(city_name)
                    emit_progress(
                        progress_callback,
                        f"中国公共招聘网 {query} - {city_name} 未解析到职位",
                        query=query,
                        city_name=city_name,
                        source_code="jobmohrss",
                    )
                    continue

                location_fetched = 0
                location_new = 0
                location_updated = 0
                for logical_page_no, page_jobs in enumerate(logical_pages, start=1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=logical_page_no)
                    stats = save_to_db(page_jobs, source_code="jobmohrss")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    location_fetched += len(page_jobs)
                    location_new += stats["new"]
                    location_updated += stats["updated"]
                    emit_progress(
                        progress_callback,
                        f"中国公共招聘网 {query} - {city_name} 第 {logical_page_no} 页完成：抓取 {len(page_jobs)} 条，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=logical_page_no,
                        source_code="jobmohrss",
                    )

                trace_item["fetched_count"] = location_fetched
                trace_item["new_count"] = location_new
                trace_item["updated_count"] = location_updated
                request_trace.append(trace_item)
    finally:
        session.close()

    emit_progress(progress_callback, f"中国公共招聘网采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条", source_code="jobmohrss")
    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated": total_updated,
        "queries": len(normalized_queries),
        "cities": len(normalized_cities),
        "runtime_mode": "requests_only",
        "detail_mode": options["detail_mode"],
        "search_type": options["search_type"],
        "resolved_city_codes": {},
        "unresolved_locations": [],
        "request_trace": request_trace,
        "request_summary": {
            "total_targets": len(request_trace),
            "resolved_targets": sum(1 for item in request_trace if item.get("status") == "resolved"),
            "fallback_targets": len(fallback_to_national_locations),
            "empty_targets": len(empty_result_locations),
        },
        "fallback_to_national_locations": fallback_to_national_locations,
        "empty_result_locations": empty_result_locations,
    }


if __name__ == "__main__":
    result = run_incremental_update()
    print(json.dumps(result, ensure_ascii=False, indent=2))