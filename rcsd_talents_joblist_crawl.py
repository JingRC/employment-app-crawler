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

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
WEB_BASE_URL = "https://web.rcsd.cn"
LIST_URL = f"{WEB_BASE_URL}/rcsd20/demand/talents/"
LIST_PAGE_URL_TEMPLATE = WEB_BASE_URL + "/rcsd20/demand/talents/index_{page_no}.html"
DEFAULT_QUERIES = ["招聘", "引才", "项目经理", "技术支持"]
DEFAULT_CITIES = ["山东", "济南", "青岛"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 15.0,
    "sleep_seconds": 0.0,
}
REQUEST_HEADERS = {
    "Referer": LIST_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}
SHANDONG_CITIES = [
    "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽"
]
ORG_SUFFIXES = [
    "有限公司", "集团有限公司", "集团", "研究所", "科学院", "大学", "学院", "学校", "医院", "党校", "实验室", "中心", "促进会", "事务所", "银行", "证券", "局", "委员会"
]


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
        emit_progress(progress_callback, "收到取消信号，准备停止人才山东引才公告采集", **context)
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
    return values or list(DEFAULT_CITIES)


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(DEFAULT_SOURCE_OPTIONS)
    options.update(source_options or {})
    detail_mode = clean_text(options.get("detail_mode") or DEFAULT_SOURCE_OPTIONS["detail_mode"]).lower() or "detail_html"
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
        raise RuntimeError("未安装 requests，无法执行人才山东引才公告采集")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def fetch_text(session: requests.Session, url: str, timeout_seconds: float) -> str:
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    encoding = (response.encoding or "").strip().lower()
    if not encoding or encoding == "iso-8859-1":
        content_head = response.content[:2048].decode("ascii", errors="ignore").lower()
        if "charset=utf-8" in content_head or "charset=\"utf-8\"" in content_head:
            response.encoding = "utf-8"
        else:
            response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def normalize_city_name(value: Any) -> str:
    text = clean_text(value)
    if text in {"山东", "山东省", "全省", "全国"}:
        return "山东"
    for city in SHANDONG_CITIES:
        if city in text:
            return city
    return ""


def city_matches(target_city: str, *texts: Any) -> bool:
    normalized_target = normalize_city_name(target_city)
    if not normalized_target or normalized_target in {"山东", "全国"}:
        return True
    return any(normalized_target in clean_text(value) for value in texts if clean_text(value))


def derive_company_name(title: str, source_name: str = "") -> str:
    cleaned_title = clean_text(title)
    cleaned_title = re.sub(r"^[0-9]{4}年", "", cleaned_title)
    for suffix in sorted(ORG_SUFFIXES, key=len, reverse=True):
        match = re.search(rf"([\u4e00-\u9fa5A-Za-z0-9（）()·-]{{2,80}}?{re.escape(suffix)})", cleaned_title)
        if match:
            return clean_text(match.group(1))
    source_clean = clean_text(source_name)
    if source_clean:
        return source_clean
    return cleaned_title[:80]


def derive_city_name(title: str, source_name: str, content: str, target_city: str = "") -> str:
    for value in (title, source_name, content, target_city):
        normalized = normalize_city_name(value)
        if normalized and normalized not in {"山东", "全国"}:
            return normalized
    normalized_target = normalize_city_name(target_city)
    return normalized_target if normalized_target else "山东"


def parse_list_page(html_text: str, page_no: int) -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析人才山东列表页")
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[dict[str, Any]] = []
    for row in soup.select(".list .item"):
        link = row.select_one(".title a")
        date_node = row.select_one(".date")
        if link is None:
            continue
        href = clean_text(link.get("href"))
        if not href:
            continue
        full_url = href if href.startswith("http") else f"{LIST_URL}{href[2:]}" if href.startswith("./") else f"{WEB_BASE_URL}{href}"
        items.append(
            {
                "title": clean_text(link.get_text(" ", strip=True)),
                "detail_url": full_url,
                "published_at": clean_text(date_node.get_text(" ", strip=True) if date_node else ""),
            }
        )
    page_count_match = re.search(r"var\s+pageCount\s*=\s*(\d+)", html_text)
    total_pages = int(page_count_match.group(1)) if page_count_match else 0
    return {
        "items": items,
        "page_no": page_no,
        "page_size": len(items),
        "total_pages": total_pages,
        "total_count": total_pages * len(items) if total_pages and items else len(items),
    }


def fetch_list_page(session: requests.Session, page_no: int, timeout_seconds: float) -> dict[str, Any]:
    url = LIST_URL if page_no <= 1 else LIST_PAGE_URL_TEMPLATE.format(page_no=page_no)
    html_text = fetch_text(session, url, timeout_seconds)
    return parse_list_page(html_text, page_no)


def parse_detail_html(html_text: str, detail_url: str = "") -> dict[str, Any]:
    if not html_text:
        return {}
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析人才山东详情页")
    soup = BeautifulSoup(html_text, "html.parser")
    title = clean_text(soup.select_one(".article .title").get_text(" ", strip=True) if soup.select_one(".article .title") else "")
    info_spans = [clean_text(node.get_text(" ", strip=True)) for node in soup.select(".article .info span") if clean_text(node.get_text(" ", strip=True))]
    source_name = ""
    published_at = ""
    for text in info_spans:
        if "信息来源" in text or "来源" in text:
            source_name = clean_text(text.split("：", 1)[-1])
        if "发布时间" in text:
            published_at = clean_text(text.split("：", 1)[-1])
    content_node = soup.select_one(".article .content")
    content_text = clean_text(content_node.get_text("\n", strip=True) if content_node else "")
    company_name = derive_company_name(title, source_name)
    city_name = derive_city_name(title, source_name, content_text)
    return {
        "title": title,
        "source_name": source_name,
        "published_at": published_at,
        "content_text": content_text,
        "company_name": company_name,
        "city_name": city_name,
        "detail_url": detail_url,
    }


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None, *, target_city: str = "") -> dict[str, Any]:
    detail = detail_item or {}
    title = clean_text(detail.get("title") or item.get("title"))
    detail_url = clean_text(detail.get("detail_url") or item.get("detail_url"))
    source_job_id = detail_url.replace(WEB_BASE_URL, "")
    content_text = clean_text(detail.get("content_text"))
    source_name = clean_text(detail.get("source_name"))
    city_name = derive_city_name(title, source_name, content_text, target_city)
    company_name = clean_text(detail.get("company_name") or derive_company_name(title, source_name))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "company_name": company_name,
        "city_name": city_name,
        "district_name": "",
        "salary_text": "",
        "degree_text": "",
        "experience_text": "",
        "brand_scale": "",
        "brand_stage": "引才公告",
        "job_type": "公告",
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": content_text,
        "publisher": source_name,
        "published_at": clean_text(detail.get("published_at") or item.get("published_at")),
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "rcsd_talents") -> dict[str, int]:
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
        content_text = "|".join([title, clean_text(item.get("description_text")), clean_text(item.get("publisher"))])
        content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()[:32]
        existing = conn.execute(
            "SELECT id, content_hash, company_name, city_name, district_name, source_url, official_apply_url, description_text FROM jobs WHERE unique_hash = ?",
            (unique_hash,),
        ).fetchone()
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
                    ("新职位发现", f"{company_name} 发布了 {title}（{city_name or '山东'}）", cursor.lastrowid),
                )
        elif (
            existing["content_hash"] != content_hash
            or clean_text(existing["company_name"]) != company_name
            or clean_text(existing["city_name"]) != city_name
            or clean_text(existing["district_name"]) != clean_text(item.get("district_name"))
            or clean_text(existing["source_url"]) != clean_text(item.get("source_url"))
            or clean_text(existing["official_apply_url"]) != clean_text(item.get("official_apply_url"))
            or clean_text(existing["description_text"]) != clean_text(item.get("description_text"))
        ):
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
        payload = fetch_list_page(session, page_no=page_no, timeout_seconds=timeout_seconds)
        items = list(payload.get("items") or [])
        total_pages = int(payload.get("total_pages") or total_pages)
        total_count = int(payload.get("total_count") or total_count)
        upstream_page_size = int(payload.get("page_size") or upstream_page_size)
        if not items:
            break

        page_jobs: list[dict[str, Any]] = []
        for raw_item in items:
            detail_item: dict[str, Any] = {}
            title_text = clean_text(raw_item.get("title"))
            body_text = title_text
            if detail_mode == "detail_html":
                html_text = fetch_text(session, clean_text(raw_item.get("detail_url")), timeout_seconds)
                detail_item = parse_detail_html(html_text, clean_text(raw_item.get("detail_url")))
                body_text = " ".join([title_text, clean_text(detail_item.get("content_text")), clean_text(detail_item.get("source_name"))])
            if query and query not in body_text:
                continue
            job = normalize_job_item(raw_item, detail_item, target_city=city_name)
            if not clean_text(job.get("company_name")) or not clean_text(job.get("source_job_id")):
                continue
            if city_name != "山东" and city_name != "全国" and not city_matches(city_name, job.get("city_name"), title_text, body_text):
                continue
            if job["source_job_id"] in seen_job_ids:
                continue
            seen_job_ids.add(job["source_job_id"])
            page_jobs.append(job)
            matched_jobs.append(job)

        emit_progress(
            progress_callback,
            f"人才山东引才公告 {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条",
            query=query,
            city_name=city_name,
            page=page_no,
            source_code="rcsd_talents",
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
        raise RuntimeError("未安装 requests，无法执行人才山东引才公告采集")

    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 18))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_trace: list[dict[str, Any]] = []

    session = build_session()
    emit_progress(progress_callback, "人才山东引才公告采集启动，模式 requests_html", source_code="rcsd_talents")
    try:
        for query in normalized_queries:
            for city_name in normalized_cities:
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                trace_item: dict[str, Any] = {
                    "query": query,
                    "location_name": city_name,
                    "status": "resolved",
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
                collect_result = collect_filtered_jobs(
                    session,
                    query=query,
                    city_name=city_name,
                    max_pages=target_pages,
                    detail_mode=options["detail_mode"],
                    timeout_seconds=options["request_timeout_seconds"],
                    sleep_seconds=options["sleep_seconds"],
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                jobs = list(collect_result.get("matched_jobs") or [])
                trace_item["api_pages_used"] = int(collect_result.get("api_pages") or 0)
                trace_item["upstream_total_count"] = int(collect_result.get("total_count") or 0)
                trace_item["upstream_total_pages"] = int(collect_result.get("total_pages") or 0)
                trace_item["upstream_page_size"] = int(collect_result.get("upstream_page_size") or 0)
                trace_item["logical_pages"] = len(collect_result.get("pages") or [])
                trace_item["fetched_count"] = len(jobs)
                if not jobs:
                    trace_item["status"] = "empty"
                    request_trace.append(trace_item)
                    continue
                stats = save_to_db(jobs, source_code="rcsd_talents")
                total_fetched += len(jobs)
                total_new += stats["new"]
                total_updated += stats["updated"]
                trace_item["new_count"] = stats["new"]
                trace_item["updated_count"] = stats["updated"]
                request_trace.append(trace_item)
    finally:
        session.close()

    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated_in_db": total_updated,
        "queries": normalized_queries,
        "cities": normalized_cities,
        "detail_mode": options["detail_mode"],
        "request_summary": {
            "total_targets": len(normalized_queries) * len(normalized_cities),
            "resolved_targets": len([item for item in request_trace if item.get("status") == "resolved"]),
            "empty_targets": len([item for item in request_trace if item.get("status") == "empty"]),
        },
        "request_trace": request_trace,
    }


if __name__ == "__main__":
    print(run_incremental_update())