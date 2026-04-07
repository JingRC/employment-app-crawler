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
BASE_URL = "http://laoshan.qdhr.com"
LIST_URL = f"{BASE_URL}/jobs/jobs_list.html"
LIST_PAGE_URL = BASE_URL + "/jobs/jobs_list/page/{page_no}.html"
DEFAULT_QUERIES = ["Java", "前端", "测试", "运维"]
DEFAULT_CITIES = ["青岛", "崂山区", "市北区"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 30.0,
    "sleep_seconds": 0.0,
}
REQUEST_HEADERS = {
    "Referer": LIST_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}
QINGDAO_DISTRICTS = ["市南区", "市北区", "黄岛区", "崂山区", "李沧区", "城阳区", "胶州市", "即墨区", "平度市", "莱西市", "西海岸新区"]


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
        emit_progress(progress_callback, "收到取消信号，准备停止 qdhr 采集", **context)
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
        value = clean_text(item)
        if value and value not in values:
            values.append(value)
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
        raise RuntimeError("未安装 requests，无法执行 qdhr 采集")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def fetch_text(session: requests.Session, url: str, timeout_seconds: float) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding or "utf-8"
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is None:
        raise RuntimeError(f"请求失败：{url}")
    raise last_error


def normalize_city_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if "青岛" in text:
        return "青岛"
    for district in QINGDAO_DISTRICTS:
        if district in text:
            return district
    return ""


def normalize_district_name(value: Any) -> str:
    text = clean_text(value)
    for district in QINGDAO_DISTRICTS:
        if district in text:
            return district
    return ""


def city_matches(target_city: str, *texts: Any) -> bool:
    target = clean_text(target_city)
    if not target or target in {"青岛", "山东"}:
        return any("青岛" in clean_text(text) for text in texts if clean_text(text)) or target in {"青岛", "山东"}
    return any(target in clean_text(text) for text in texts if clean_text(text))


def parse_list_page(html_text: str, page_no: int) -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析 qdhr 列表页")
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[dict[str, Any]] = []
    for node in soup.select(".J_jobsList"):
        job_link = node.select_one(".td-j-name a[href*='/jobs/']")
        company_link = node.select_one(".td3 a[href*='/company/']")
        detail_text = clean_text(node.select_one(".detail .txt").get_text(" ", strip=True) if node.select_one(".detail .txt") else "")
        salary_text = clean_text(node.select_one(".td4").get_text(" ", strip=True) if node.select_one(".td4") else "")
        publish_text = clean_text(node.select_one(".td5").get_text(" ", strip=True) if node.select_one(".td5") else "")
        if job_link is None:
            continue
        href = clean_text(job_link.get("href"))
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        labels = [clean_text(label.get_text(" ", strip=True)) for label in node.select(".dlabs .dl") if clean_text(label.get_text(" ", strip=True))]
        items.append(
            {
                "title": clean_text(job_link.get_text(" ", strip=True)).split("|", 1)[-1].strip(),
                "list_title": clean_text(job_link.get_text(" ", strip=True)),
                "detail_url": full_url,
                "company_name": clean_text(company_link.get_text(" ", strip=True) if company_link else ""),
                "salary_text": salary_text,
                "published_at": publish_text,
                "summary_text": detail_text,
                "tags": labels,
            }
        )
    page_numbers = [int(value) for value in re.findall(r"/jobs/jobs_list/page/(\d+)\.html", html_text)]
    total_pages = max(page_numbers) if page_numbers else page_no
    return {
        "items": items,
        "page_no": page_no,
        "page_size": len(items),
        "total_pages": total_pages,
        "total_count": total_pages * len(items) if items and total_pages else len(items),
    }


def fetch_list_page(session: requests.Session, page_no: int, timeout_seconds: float) -> dict[str, Any]:
    url = LIST_URL if page_no <= 1 else LIST_PAGE_URL.format(page_no=page_no)
    html_text = fetch_text(session, url, timeout_seconds)
    return parse_list_page(html_text, page_no)


def parse_detail_html(html_text: str, detail_url: str = "") -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析 qdhr 详情页")
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text("\n", strip=True)
    title = clean_text(soup.title.get_text(" ", strip=True).split("-", 1)[0] if soup.title else "")
    company_name = ""
    title_text = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    title_parts = [clean_text(part) for part in title_text.split("-") if clean_text(part)]
    if len(title_parts) >= 2:
        company_name = title_parts[1].replace("招聘", "").strip()

    def capture(label: str, next_label: str | None = None) -> str:
        pattern = re.escape(label) + r"\s*(.*?)"
        if next_label:
            pattern += re.escape(next_label)
        match = re.search(pattern, text, flags=re.S)
        if not match:
            return ""
        value = clean_text(match.group(1))
        return value

    salary_text = ""
    salary_match = re.search(r"([0-9一二三四五六七八九十百千万kK点\.\-~]+/月|面议)", text)
    if salary_match:
        salary_text = clean_text(salary_match.group(1))
    degree_text = capture("学历要求", "工作经验")
    experience_text = capture("工作经验", "年龄要求")
    job_type = capture("工作性质", "招聘人数")
    location_text = capture("工作地点", "联系方式")
    description_text = capture("职位描述", "申请职位") or capture("职位描述", "收藏")
    brand_stage = capture("性质", "行业")
    industry_text = capture("行业", "规模")
    brand_scale = capture("规模", "地区")
    company_area = capture("地区", "扫描二维码即可在手机端精彩呈现") or capture("地区", "给我留言")
    district_name = normalize_district_name(location_text or company_area)
    city_name = "青岛" if "青岛" in f"{location_text} {company_area}" else (district_name or "青岛")
    return {
        "title": title,
        "company_name": company_name,
        "salary_text": salary_text,
        "degree_text": degree_text,
        "experience_text": experience_text,
        "job_type": job_type,
        "location_text": location_text,
        "description_text": description_text,
        "brand_stage": brand_stage,
        "industry_text": industry_text,
        "brand_scale": brand_scale,
        "city_name": city_name,
        "district_name": district_name,
        "company_area": company_area,
        "detail_url": detail_url,
    }


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = detail_item or {}
    title = clean_text(detail.get("title") or item.get("title"))
    detail_url = clean_text(detail.get("detail_url") or item.get("detail_url"))
    source_job_id = detail_url.replace(BASE_URL, "")
    company_name = clean_text(detail.get("company_name") or item.get("company_name"))
    district_name = clean_text(detail.get("district_name") or normalize_district_name(item.get("list_title")))
    city_name = clean_text(detail.get("city_name") or "青岛")
    description_text = clean_text(detail.get("description_text") or item.get("summary_text"))
    return {
        "source_job_id": source_job_id,
        "title": title,
        "company_name": company_name,
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(detail.get("salary_text") or item.get("salary_text")),
        "degree_text": clean_text(detail.get("degree_text")),
        "experience_text": clean_text(detail.get("experience_text")),
        "brand_scale": clean_text(detail.get("brand_scale")),
        "brand_stage": clean_text(detail.get("brand_stage")),
        "job_type": clean_text(detail.get("job_type")),
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": description_text,
        "publisher": clean_text(detail.get("industry_text")),
        "published_at": clean_text(item.get("published_at")),
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "qdhr") -> dict[str, int]:
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
        content_text = "|".join([title, clean_text(item.get("description_text")), clean_text(item.get("salary_text"))])
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
                    ("新职位发现", f"{company_name} 发布了 {title}（{city_name or '青岛'}）", cursor.lastrowid),
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
    stop_reason = "completed"

    for page_no in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        try:
            payload = fetch_list_page(session, page_no=page_no, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            emit_progress(
                progress_callback,
                f"qdhr 列表页获取失败，结束当前组合：第 {page_no} 页",
                query=query,
                city_name=city_name,
                page=page_no,
                source_code="qdhr",
                error=str(exc),
            )
            stop_reason = f"list_page_error:{exc.__class__.__name__}"
            break
        items = list(payload.get("items") or [])
        total_pages = int(payload.get("total_pages") or total_pages)
        total_count = int(payload.get("total_count") or total_count)
        upstream_page_size = int(payload.get("page_size") or upstream_page_size)
        if not items:
            stop_reason = "empty_page"
            break
        page_jobs: list[dict[str, Any]] = []
        for raw_item in items:
            detail_item: dict[str, Any] = {}
            haystack = " ".join([clean_text(raw_item.get("title")), clean_text(raw_item.get("summary_text")), clean_text(raw_item.get("company_name"))])
            if detail_mode == "detail_html":
                try:
                    detail_html = fetch_text(session, clean_text(raw_item.get("detail_url")), timeout_seconds)
                    detail_item = parse_detail_html(detail_html, clean_text(raw_item.get("detail_url")))
                    haystack = " ".join([haystack, clean_text(detail_item.get("description_text")), clean_text(detail_item.get("company_name"))])
                except Exception as exc:  # noqa: BLE001
                    emit_progress(
                        progress_callback,
                        f"qdhr 详情页获取失败，回退列表字段继续处理：{clean_text(raw_item.get('detail_url'))}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                        source_code="qdhr",
                        error=str(exc),
                    )
            if query and query not in haystack:
                continue
            if city_name and not city_matches(city_name, raw_item.get("list_title"), raw_item.get("summary_text"), detail_item.get("location_text"), detail_item.get("company_area")):
                continue
            job = normalize_job_item(raw_item, detail_item)
            if not job["source_job_id"] or job["source_job_id"] in seen_job_ids:
                continue
            seen_job_ids.add(job["source_job_id"])
            page_jobs.append(job)
            matched_jobs.append(job)
        emit_progress(
            progress_callback,
            f"qdhr {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条",
            query=query,
            city_name=city_name,
            page=page_no,
            source_code="qdhr",
        )
        if page_jobs:
            logical_pages.append(page_jobs)
        if sleep_seconds > 0:
            safe_sleep(sleep_seconds, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        if total_pages > 0 and page_no >= total_pages:
            stop_reason = "reached_total_pages"
            break

    return {
        "pages": logical_pages,
        "matched_jobs": matched_jobs,
        "api_pages": min(max_pages, total_pages if total_pages > 0 else max_pages),
        "total_count": total_count,
        "total_pages": total_pages,
        "upstream_page_size": upstream_page_size,
        "stop_reason": stop_reason,
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
    del output_dir, page_size, runtime_mode
    configure_stdio()
    ensure_db()
    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 20))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_trace: list[dict[str, Any]] = []

    session = build_session()
    try:
        for query in normalized_queries:
            for city_name in normalized_cities:
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
                trace_item["stop_reason"] = clean_text(collect_result.get("stop_reason"))
                if not jobs:
                    trace_item["status"] = "empty"
                    request_trace.append(trace_item)
                    continue
                stats = save_to_db(jobs, source_code="qdhr")
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