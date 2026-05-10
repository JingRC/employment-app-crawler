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
BASE_URL = "https://www.gaoxiaojob.com"
LIST_API_URL = f"{BASE_URL}/home/change-latest-job"

DEFAULT_COLUMNS = ["1", "2", "3", "4", "5", "6", "9"]
COLUMN_NAMES: dict[str, str] = {
    "1": "高校招聘",
    "2": "中小学校",
    "3": "科技人才",
    "4": "政府与事业单位",
    "5": "医学人才",
    "6": "企业招聘",
    "9": "高端人才",
}
DEFAULT_CITIES = ["0"]
DEFAULT_QUERIES = list(DEFAULT_COLUMNS)
DEFAULT_MAX_PAGES = 3
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "list_only",
    "request_timeout_seconds": 25.0,
    "page_size": 12,
}
REQUEST_HEADERS = {
    "Referer": BASE_URL,
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
        emit_progress(progress_callback, "收到取消信号，准备停止高才网采集", **context)
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


def make_job_hash(title: str, organization: str, city: str, source_job_id: str) -> str:
    raw = f"{title}|{organization}|{city}|{source_job_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fetch_job_list(
    session: requests.Session,
    column_id: str,
    city_id: str,
    page: int,
    page_size: int,
    timeout: float,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    del city_id, page_size
    # Column pages return all jobs on a single page (no pagination)
    if page > 1:
        return [], 0
    column_url = f"{BASE_URL}/column/{column_id}.html"
    for attempt in range(3):
        ensure_not_cancelled(should_stop_callback, progress_callback, column=column_id, page=page)
        try:
            response = session.get(column_url, timeout=timeout, headers=REQUEST_HEADERS)
            if response.status_code == 200:
                response.encoding = "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                items = parse_list_html(soup)
                return items, len(items)
            if attempt < 2:
                time.sleep(2.0)
        except Exception as exc:
            if attempt < 2:
                time.sleep(2.0)
            else:
                raise exc
    return [], 0


def parse_list_html(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for li in soup.find_all("li"):
        a = li.find("a", href=re.compile(r"/job/detail/"))
        if not a:
            continue
        href = str(a.get("href", "")).strip()
        detail_match = re.search(r"/job/detail/(\d+)\.html", href)
        if not detail_match:
            continue
        source_job_id = detail_match.group(1)
        source_url = BASE_URL + href if href.startswith("/") else href

        title = (a.get("title") or "").strip()
        if not title:
            h6 = a.select_one("h6")
            title = clean_text(h6.get_text()) if h6 else ""

        school_el = a.select_one(".school")
        company_name = clean_text(school_el.get_text()) if school_el else ""

        city_el = a.select_one(".city")
        city_name = clean_text(city_el.get_text()) if city_el else ""

        money_el = a.select_one(".money")
        salary_text = clean_text(money_el.get_text()) if money_el else ""

        degree_text = ""
        experience_text = ""
        req_el = a.select_one(".requirement")
        if req_el:
            req_spans = req_el.select("span")
            degree_text = clean_text(req_spans[0].get_text()) if len(req_spans) > 0 else ""
            experience_text = clean_text(req_spans[2].get_text()) if len(req_spans) > 2 else ""

        status = "inactive" if "已下线" in str(a.get("class", [])) or "offline" in str(a.get("class", [])) else "active"

        items.append({
            "source_job_id": source_job_id,
            "title": title,
            "company_name": company_name,
            "city_name": city_name,
            "salary_text": salary_text,
            "degree_text": degree_text,
            "experience_text": experience_text,
            "source_url": source_url,
            "status": status,
        })
    return items


def upsert_job(conn: sqlite3.Connection, item: dict[str, Any], source_code: str) -> dict[str, Any]:
    unique_hash = make_job_hash(item["title"], item["company_name"], item["city_name"], item["source_job_id"])
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    cursor = conn.execute("SELECT id, status, unique_hash FROM jobs WHERE unique_hash = ?", (unique_hash,))
    existing = cursor.fetchone()

    if existing:
        job_id = int(existing[0])
        old_status = str(existing[1] or "active")
        new_status = item.get("status", "active")
        if old_status != new_status and new_status == "active":
            conn.execute("UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?", (new_status, now, job_id))
            conn.execute(
                "INSERT INTO job_change_events (job_id, change_type, old_value, new_value, changed_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, "status_change", old_status, new_status, now),
            )
        else:
            conn.execute("UPDATE jobs SET last_seen_at = ? WHERE id = ?", (now, job_id))
        return {"action": "updated", "job_id": job_id, "status": new_status}

    cursor = conn.execute(
        """INSERT INTO jobs (source_job_id, source_code, title, company_name, city_name,
        salary_text, degree_text, experience_text, source_url, unique_hash,
        first_seen_at, last_seen_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item["source_job_id"], source_code, item["title"], item["company_name"],
            item["city_name"], item.get("salary_text", ""), item.get("degree_text", ""),
            item.get("experience_text", ""), item["source_url"], unique_hash,
            now, now, item.get("status", "active"),
        ),
    )
    job_id = int(cursor.lastrowid or 0)
    return {"action": "new", "job_id": job_id, "status": item.get("status", "active")}


def run_incremental_update(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    source_options: dict[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    page_size: int | None = None,
    source_code: str = "gaoxiaojob",
) -> dict[str, Any]:
    configure_stdio()
    options = dict(DEFAULT_SOURCE_OPTIONS)
    if source_options:
        options.update(source_options)

    active_queries = list(queries) if queries else list(DEFAULT_QUERIES)
    active_cities = list(cities) if cities else list(DEFAULT_CITIES)
    active_max_pages = int(max_pages) if max_pages else DEFAULT_MAX_PAGES
    active_page_size = int(page_size or int(options.get("page_size", 12)))
    timeout = float(options.get("request_timeout_seconds", 25.0))

    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    try:
        session.get(BASE_URL, timeout=timeout)
    except Exception:
        pass

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_trace: list[dict[str, Any]] = []
    request_summary = {"total_targets": 0, "resolved_targets": 0, "fallback_targets": 0, "empty_targets": 0}
    empty_locations: list[str] = []

    emit_progress(progress_callback, f"开始高才网采集 columns={active_queries} cities={active_cities}")

    for column_id in active_queries:
        for city_id in active_cities:
            column_name = COLUMN_NAMES.get(column_id, f"column_{column_id}")
            request_summary["total_targets"] += 1
            page_fetched = 0
            column_empty = True

            for page in range(1, active_max_pages + 1):
                ensure_not_cancelled(should_stop_callback, progress_callback, column=column_id, page=page)
                try:
                    items, total_count = fetch_job_list(
                        session, column_id, city_id, page, active_page_size, timeout,
                        should_stop_callback, progress_callback,
                    )
                except CrawlCancelledError:
                    raise
                except Exception as exc:
                    emit_progress(progress_callback, f"高才网获取失败 column={column_id} page={page}: {exc}")
                    request_trace.append({
                        "column": column_id,
                        "page": page,
                        "error": str(exc),
                    })
                    break

                if not items:
                    if page == 1:
                        empty_locations.append(f"{column_name}(city={city_id})")
                    break

                column_empty = False
                for item in items:
                    total_fetched += 1
                    page_fetched += 1
                    try:
                        result = upsert_job(conn, item, source_code)
                        if result["action"] == "new":
                            total_new += 1
                        elif result["action"] == "updated":
                            total_updated += 1
                    except Exception:
                        pass

                request_trace.append({
                    "column": column_id,
                    "column_name": column_name,
                    "city_id": city_id,
                    "page": page,
                    "fetched": len(items),
                    "total_count": total_count,
                })

                if len(items) < active_page_size:
                    break

                safe_sleep(1.0, should_stop_callback, progress_callback)

            if column_empty:
                request_summary["empty_targets"] += 1
            else:
                request_summary["resolved_targets"] += 1

    conn.commit()
    conn.close()
    session.close()

    result: dict[str, Any] = {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated_in_db": total_updated,
        "request_trace": request_trace,
        "request_summary": request_summary,
    }
    if empty_locations:
        result["empty_result_locations"] = empty_locations
    emit_progress(progress_callback, f"高才网完成: fetched={total_fetched} new={total_new} updated={total_updated}")
    return result
