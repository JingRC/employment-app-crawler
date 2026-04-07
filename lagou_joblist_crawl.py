from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
DEBUG_DIR = DB_DIR / "debug_snapshots" / "lagou"
BASE_URL = "https://www.lagou.com/wn/jobs"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州"]
DEFAULT_WAIT_SECONDS = 6.0
DEFAULT_SOURCE_OPTIONS = {
    "verification_wait_seconds": 90,
    "capture_debug_snapshot": True,
    "stop_on_all_seen_page": True,
}
MAX_RETRIES = 2
BRANCH_LABELS = {
    "next_data": "首屏注水",
    "packet": "接口响应",
    "dom": "结果页DOM",
    "pagination_end": "分页尾页",
    "none": "未命中",
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
        emit_progress(progress_callback, "收到取消信号，准备停止拉勾采集", **context)
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


def parse_bool_option(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(DEFAULT_SOURCE_OPTIONS)
    options.update(source_options or {})
    wait_seconds = int(options.get("verification_wait_seconds") or DEFAULT_SOURCE_OPTIONS["verification_wait_seconds"])
    wait_seconds = max(15, min(wait_seconds, 300))
    capture_debug_snapshot = parse_bool_option(options.get("capture_debug_snapshot"), True)
    stop_on_all_seen_page = parse_bool_option(options.get("stop_on_all_seen_page"), True)
    return {
        "verification_wait_seconds": wait_seconds,
        "capture_debug_snapshot": capture_debug_snapshot,
        "stop_on_all_seen_page": stop_on_all_seen_page,
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


def build_browser_options() -> ChromiumOptions:
    if ChromiumOptions is None:
        raise RuntimeError("未安装 DrissionPage，无法执行拉勾浏览器采集")
    options = ChromiumOptions()
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument("--disable-gpu")
    options.set_argument("--window-size=1440,960")
    return options


def build_search_url(query: str, city_name: str) -> str:
    params = {"kd": query}
    if city_name and city_name != "全国":
        params["city"] = city_name
    return f"{BASE_URL}?{urlencode(params)}"


def page_text(page: Any) -> str:
    try:
        return clean_text(page.run_js("return document.body.innerText.slice(0, 2000)"))
    except Exception:
        return ""


def is_verification_page(page: Any) -> bool:
    title = clean_text(getattr(page, "title", ""))
    body_text = page_text(page)
    return "滑动验证页面" in title or "访问验证" in body_text or "请按住滑块" in body_text


def has_result_dom(page: Any) -> bool:
    try:
        count = int(
            page.run_js(
                """
                return document.querySelectorAll(
                    '[class*="job-card"], [class*="job-list"], a[href*="/jobs/"]'
                ).length;
                """
            )
            or 0
        )
    except Exception:
        count = 0
    return count > 0 and not is_verification_page(page)


def wait_for_access(
    page: Any,
    *,
    verification_wait_seconds: int,
    query: str,
    city_name: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> bool:
    if not is_verification_page(page):
        return False
    emit_progress(
        progress_callback,
        f"拉勾 {query} - {city_name} 触发滑动验证，请在浏览器窗口手动完成，最长等待 {verification_wait_seconds} 秒",
        query=query,
        city_name=city_name,
        source_code="lagou",
    )
    deadline = time.time() + verification_wait_seconds
    while time.time() < deadline:
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name)
        if not is_verification_page(page):
            safe_sleep(2, should_stop_callback, progress_callback, query=query, city_name=city_name)
            if has_result_dom(page):
                return True
        time.sleep(1)
    raise RuntimeError("拉勾仍停留在滑动验证页，请人工通过后重试")


def split_city_district(raw_text: str) -> tuple[str, str]:
    value = clean_text(raw_text)
    if not value:
        return "", ""
    for separator in ["-", "·", "/", "|"]:
        if separator in value:
            city_name, district_name = value.split(separator, 1)
            return clean_text(city_name), clean_text(district_name)
    return value, ""


def traverse_job_lists(node: Any) -> list[list[dict[str, Any]]]:
    matches: list[list[dict[str, Any]]] = []
    if isinstance(node, list) and node and all(isinstance(item, dict) for item in node):
        score = 0
        for item in node[:5]:
            if any(key in item for key in ["positionId", "positionName", "salary", "companyFullName", "companyShortName", "city"]):
                score += 1
        if score >= max(1, min(2, len(node))):
            matches.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            matches.extend(traverse_job_lists(value))
    return matches


def normalize_packet_job(item: dict[str, Any]) -> dict[str, Any]:
    city_name, district_name = split_city_district(item.get("city") or item.get("district") or item.get("positionAddress"))
    company_name = clean_text(item.get("companyFullName") or item.get("companyShortName") or item.get("companyName"))
    source_job_id = clean_text(item.get("positionId") or item.get("jobId") or item.get("id"))
    source_url = clean_text(item.get("positionDetailUrl") or item.get("positionUrl") or item.get("link"))
    if source_url.startswith("//"):
        source_url = f"https:{source_url}"
    if source_job_id and not source_url:
        source_url = f"https://www.lagou.com/jobs/{source_job_id}.html"
    description_parts = [
        clean_text(item.get("positionAdvantage") or item.get("positionLabel")),
        clean_text(item.get("businessZones")),
        clean_text(item.get("companyLabelList")),
    ]
    return {
        "source_job_id": source_job_id,
        "title": clean_text(item.get("positionName") or item.get("title") or item.get("jobName")),
        "company_name": company_name,
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(item.get("salary")),
        "degree_text": clean_text(item.get("education") or item.get("degree")),
        "experience_text": clean_text(item.get("workYear") or item.get("experience")),
        "brand_scale": clean_text(item.get("companySize") or item.get("financeStage")),
        "brand_stage": clean_text(item.get("financeStage")),
        "job_type": clean_text(item.get("jobNature") or item.get("firstType") or item.get("secondType")),
        "source_url": source_url,
        "official_apply_url": source_url,
        "description_text": "\n\n".join(part for part in description_parts if part),
        "source_code": "lagou",
        "status": "active",
    }


def extract_jobs_from_packets(packets: list[Any]) -> list[dict[str, Any]]:
    for packet in reversed(packets):
        body = getattr(getattr(packet, "response", None), "body", None)
        if isinstance(body, str):
            stripped = body.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    body = json.loads(stripped)
                except Exception:
                    continue
            else:
                continue
        if not isinstance(body, (dict, list)):
            continue
        for job_list in traverse_job_lists(body):
            jobs = [normalize_packet_job(item) for item in job_list]
            jobs = [job for job in jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
            if jobs:
                return jobs
    return []


def extract_jobs_from_next_data(page: Any) -> list[dict[str, Any]]:
        try:
                payload = page.run_js(
                        """
                        const node = document.getElementById('__NEXT_DATA__');
                        if (!node) {
                            return null;
                        }
                        try {
                            const parsed = JSON.parse(node.textContent || '{}');
                            return parsed?.props?.pageProps?.initData || null;
                        } catch (error) {
                            return { parseError: String(error) };
                        }
                        """
                )
        except Exception:
                return []
        if not isinstance(payload, (dict, list)):
                return []
        for job_list in traverse_job_lists(payload):
                jobs = [normalize_packet_job(item) for item in job_list]
                jobs = [job for job in jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
                if jobs:
                        return jobs
        return []


def extract_dom_job_cards(page: Any) -> list[dict[str, Any]]:
    payload = page.run_js(
        """
        const cardSelectors = [
                    '.item__10RTO',
                    '.list__YibNq .item__10RTO',
          '.job-card-wrapper',
          '.job-list-item',
          '[class*="job-card"]',
          '[class*="job-list-item"]'
        ];
        const cards = [];
        for (const selector of cardSelectors) {
          const found = Array.from(document.querySelectorAll(selector));
          if (found.length) {
            cards.push(...found);
            break;
          }
        }
        const uniq = Array.from(new Set(cards));
        return uniq.map((card) => {
                    const textLines = (card.innerText || '')
                        .split('\\n')
            .map((item) => item.trim())
            .filter(Boolean);
                    const link = card.querySelector('a[href*="/jobs/"]') || card.querySelector('.p-top__1F7CL a') || card.querySelector('.position__21iOS a') || card.querySelector('a');
                    const titleNode = card.querySelector('.p-top__1F7CL') || card.querySelector('.position__21iOS') || card.querySelector('[class*="title"], [class*="name"], h3, h4');
          const salaryNode = card.querySelector('[class*="salary"], [class*="money"]');
          const companyNode = card.querySelector('[class*="company"]');
          const tagNodes = Array.from(card.querySelectorAll('span, li')).map((el) => (el.innerText || '').trim()).filter(Boolean).slice(0, 12);
                      const fallbackSalary = textLines.find((line) => /k|K|薪|元\\/?天|万/.test(line)) || '';
          return {
            title: (titleNode ? titleNode.innerText : '') || (link ? link.innerText : '') || textLines[0] || '',
                        source_url: link ? (link.href || link.getAttribute('href') || '') : '',
                        salary: salaryNode ? (salaryNode.innerText || '') : fallbackSalary,
                        company_name: companyNode ? (companyNode.innerText || '') : (textLines[2] || textLines[1] || ''),
            location: textLines.find((line) => /北京|上海|广州|深圳|杭州|成都|武汉|南京|苏州|天津|重庆|青岛|济南|西安|大连|厦门|长沙|宁波|无锡|郑州|沈阳|合肥|福州|东莞|佛山/.test(line)) || '',
            experience: textLines.find((line) => /年|应届|实习|经验不限/.test(line)) || '',
            degree: textLines.find((line) => /学历不限|本科|大专|硕士|博士|中专|高中/.test(line)) || '',
            tags: tagNodes,
            description_text: textLines.join('\\n'),
          };
        }).filter((item) => item.title && item.company_name);
        """
    )
    return payload if isinstance(payload, list) else []


def build_debug_snapshot(page: Any, packets: list[Any], *, query: str, city_name: str, page_no: int, stage: str) -> dict[str, Any]:
    try:
        selector_counts = page.run_js(
            """
            return {
              jobCardWrapper: document.querySelectorAll('.job-card-wrapper').length,
              jobListItem: document.querySelectorAll('.job-list-item').length,
              genericJobCard: document.querySelectorAll('[class*="job-card"]').length,
              genericJobList: document.querySelectorAll('[class*="job-list"]').length,
              jobLinks: document.querySelectorAll('a[href*="/jobs/"]').length,
              scriptTags: document.querySelectorAll('script').length
            };
            """
        )
    except Exception:
        selector_counts = {}

    request_hits: list[dict[str, Any]] = []
    for packet in packets[-80:]:
        request = getattr(packet, "request", None)
        response = getattr(packet, "response", None)
        request_url = str(getattr(request, "url", ""))
        if not request_url:
            continue
        lower = request_url.lower()
        if not any(keyword in lower for keyword in ["lagou", "jobs", "search", "query", "position", "list"]):
            continue
        body = getattr(response, "body", None)
        request_hits.append(
            {
                "url": request_url,
                "method": clean_text(getattr(request, "method", "")),
                "post_data": getattr(request, "postData", None),
                "response_type": type(body).__name__,
                "response_keys": list(body.keys())[:20] if isinstance(body, dict) else None,
            }
        )

    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "query": query,
        "city_name": city_name,
        "page_no": page_no,
        "current_url": clean_text(getattr(page, "url", "")),
        "title": clean_text(getattr(page, "title", "")),
        "is_verification_page": is_verification_page(page),
        "body_text_excerpt": page_text(page),
        "html_excerpt": clean_text((getattr(page, "html", "") or "")[:4000]),
        "selector_counts": selector_counts,
        "request_hits": request_hits,
    }


def save_debug_snapshot(snapshot: dict[str, Any], *, query: str, city_name: str, page_no: int, stage: str) -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_-]+", "_", query)[:40] or "query"
    safe_city = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_-]+", "_", city_name)[:40] or "city"
    safe_stage = re.sub(r"[^0-9A-Za-z_-]+", "_", stage)[:30] or "stage"
    file_path = DEBUG_DIR / f"{timestamp}_{safe_query}_{safe_city}_p{page_no}_{safe_stage}.json"
    file_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


def capture_debug_snapshot_if_needed(
    page: Any,
    packets: list[Any],
    *,
    query: str,
    city_name: str,
    page_no: int,
    stage: str,
    capture_debug_snapshot: bool,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> str:
    if not capture_debug_snapshot:
        return ""
    snapshot = build_debug_snapshot(page, packets, query=query, city_name=city_name, page_no=page_no, stage=stage)
    path = save_debug_snapshot(snapshot, query=query, city_name=city_name, page_no=page_no, stage=stage)
    emit_progress(
        progress_callback,
        f"拉勾 {query} - {city_name} 第 {page_no} 页已保存诊断快照：{path}",
        query=query,
        city_name=city_name,
        page=page_no,
        debug_snapshot_path=str(path),
    )
    return str(path)


def normalize_dom_job(item: dict[str, Any]) -> dict[str, Any]:
    city_name, district_name = split_city_district(item.get("location"))
    title = clean_text(item.get("title"))
    if not district_name:
        district_match = re.search(r"\[([^\]]+)\]", title)
        if district_match:
            district_name = clean_text(district_match.group(1))
    source_url = clean_text(item.get("source_url"))
    source_job_id = ""
    match = re.search(r"/jobs/(\d+)\.html", source_url)
    if match:
        source_job_id = match.group(1)
    tags = [clean_text(tag) for tag in (item.get("tags") or []) if clean_text(tag)]
    return {
        "source_job_id": source_job_id,
        "title": title,
        "company_name": clean_text(item.get("company_name")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(item.get("salary")),
        "degree_text": clean_text(item.get("degree")),
        "experience_text": clean_text(item.get("experience")),
        "brand_scale": "",
        "brand_stage": "",
        "job_type": " / ".join(tags[:8]),
        "source_url": source_url,
        "official_apply_url": source_url,
        "description_text": clean_text(item.get("description_text")),
        "source_code": "lagou",
        "status": "active",
    }


def city_matches(expected_city: str, actual_city: str) -> bool:
    expected = clean_text(expected_city)
    actual = clean_text(actual_city)
    if not expected or expected == "全国":
        return True
    return actual == expected or actual.startswith(expected)


def extract_page_signature_token(item: dict[str, Any]) -> str:
    return (
        clean_text(item.get("source_job_id"))
        or clean_text(item.get("source_url"))
        or clean_text(item.get("title"))
        or clean_text(item.get("company_name"))
    )


def detect_payload_branch(payload: dict[str, Any]) -> str:
    if payload.get("pagination_end"):
        return "pagination_end"
    if payload.get("from_next_data"):
        return "next_data"
    if payload.get("from_packet"):
        return "packet"
    if payload.get("from_dom"):
        return "dom"
    return "none"


def get_branch_label(branch: str) -> str:
    normalized = clean_text(branch).lower() or "none"
    return BRANCH_LABELS.get(normalized, normalized)


def capture_current_page_jobs(
    page: Any,
    *,
    query: str,
    city_name: str,
    verification_wait_seconds: int,
    capture_debug_snapshot: bool,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    url = build_search_url(query, city_name)
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
        page.listen.start()
        page.get(url)
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
        had_verification = wait_for_access(
            page,
            verification_wait_seconds=verification_wait_seconds,
            query=query,
            city_name=city_name,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
        )
        if had_verification:
            page.listen.start()
            page.refresh()
            safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
        packets = list(page.listen.steps(count=60, timeout=4))
        packet_jobs = extract_jobs_from_packets(packets)
        if packet_jobs:
            return {"items": packet_jobs, "from_packet": True, "current_page": 1}
        next_data_jobs = extract_jobs_from_next_data(page)
        if next_data_jobs:
            return {"items": next_data_jobs, "from_next_data": True, "current_page": 1}
        dom_jobs = [normalize_dom_job(item) for item in extract_dom_job_cards(page)]
        dom_jobs = [job for job in dom_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
        if dom_jobs:
            return {"items": dom_jobs, "from_dom": True, "current_page": 1}
        debug_snapshot_path = capture_debug_snapshot_if_needed(
            page,
            packets,
            query=query,
            city_name=city_name,
            page_no=1,
            stage=f"first_page_attempt_{attempt}",
            capture_debug_snapshot=capture_debug_snapshot,
            progress_callback=progress_callback,
        )
        if attempt < MAX_RETRIES:
            emit_progress(progress_callback, f"拉勾 {query} - {city_name} 第 1 页未解析到职位，准备重试", query=query, city_name=city_name, page=1)
    return {"items": [], "current_page": 1, "debug_snapshot_path": debug_snapshot_path if 'debug_snapshot_path' in locals() else ""}


def load_page_via_click(
    page: Any,
    *,
    target_page_no: int,
    query: str,
    city_name: str,
    verification_wait_seconds: int,
    capture_debug_snapshot: bool,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=target_page_no)
    clicked = False
    try:
        clicked = bool(
            page.run_js(
                f"""
                const targetText = String({json.dumps(str(target_page_no), ensure_ascii=False)});
                const candidates = Array.from(document.querySelectorAll('li, a, span, button'));
                const node = candidates.find((item) => (item.innerText || '').trim() === targetText);
                if (!node) return false;
                node.click();
                return true;
                """
            )
        )
    except Exception:
        clicked = False
    if not clicked:
        emit_progress(
            progress_callback,
            f"拉勾 {query} - {city_name} 第 {target_page_no} 页未找到分页按钮，按结果尾页结束",
            query=query,
            city_name=city_name,
            page=target_page_no,
            branch="pagination_end",
            branch_label=f"来源分支: {get_branch_label('pagination_end')}",
        )
        return {"items": [], "current_page": target_page_no - 1, "pagination_end": True}
    page.listen.start()
    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=target_page_no)
    if is_verification_page(page):
        wait_for_access(
            page,
            verification_wait_seconds=verification_wait_seconds,
            query=query,
            city_name=city_name,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
        )
        page.listen.start()
        page.refresh()
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=target_page_no)
    packets = list(page.listen.steps(count=60, timeout=4))
    packet_jobs = extract_jobs_from_packets(packets)
    if packet_jobs:
        return {"items": packet_jobs, "from_packet": True, "current_page": target_page_no}
    next_data_jobs = extract_jobs_from_next_data(page)
    if next_data_jobs:
        return {"items": next_data_jobs, "from_next_data": True, "current_page": target_page_no}
    dom_jobs = [normalize_dom_job(item) for item in extract_dom_job_cards(page)]
    dom_jobs = [job for job in dom_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
    if dom_jobs:
        return {"items": dom_jobs, "from_dom": True, "current_page": target_page_no}
    debug_snapshot_path = capture_debug_snapshot_if_needed(
        page,
        packets,
        query=query,
        city_name=city_name,
        page_no=target_page_no,
        stage="pagination_no_jobs",
        capture_debug_snapshot=capture_debug_snapshot,
        progress_callback=progress_callback,
    )
    return {"items": [], "current_page": target_page_no - 1, "debug_snapshot_path": debug_snapshot_path}


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "lagou") -> dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}
    for item in jobs:
        job_id = clean_text(item.get("source_job_id"))
        title = clean_text(item.get("title"))
        company_name = clean_text(item.get("company_name"))
        city_name = clean_text(item.get("city_name"))
        if not title or not company_name:
            continue
        unique_raw = f"{source_code}|{job_id or title}|{company_name}|{city_name}"
        unique_hash = hashlib.sha256(unique_raw.encode("utf-8")).hexdigest()[:32]
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
    max_pages: int = 1,
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
        raise RuntimeError("未安装 DrissionPage，无法执行拉勾浏览器采集")

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    normalized_source_options = normalize_source_options(source_options)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 40))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    seen_page_signatures: set[tuple[str, str, str]] = set()
    seen_job_ids: set[str] = set()
    debug_snapshot_paths: list[str] = []
    lagou_trace: list[dict[str, Any]] = []
    overall_branch_counts = {branch: 0 for branch in BRANCH_LABELS}

    page = ChromiumPage(build_browser_options())
    try:
        emit_progress(progress_callback, "拉勾采集启动，模式 browser_manual_intercept")
        emit_progress(progress_callback, "拉勾若触发滑动验证，将等待手工通过后继续抓取", source_code="lagou")
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_fetched = 0
                city_new = 0
                city_updated = 0
                pages_completed = 0
                stop_reason = "target_pages_reached"
                city_branch_counts = {branch: 0 for branch in BRANCH_LABELS}
                last_branch = "none"
                last_debug_snapshot_path = ""
                emit_progress(progress_callback, f"拉勾开始抓取 {query} - {city_name} 第 1 页", query=query, city_name=city_name, page=1)
                current_payload = capture_current_page_jobs(
                    page,
                    query=query,
                    city_name=city_name,
                    verification_wait_seconds=int(normalized_source_options["verification_wait_seconds"]),
                    capture_debug_snapshot=bool(normalized_source_options["capture_debug_snapshot"]),
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                for page_no in range(1, target_pages + 1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                    if page_no > 1:
                        emit_progress(progress_callback, f"拉勾开始抓取 {query} - {city_name} 第 {page_no} 页", query=query, city_name=city_name, page=page_no)
                        current_payload = load_page_via_click(
                            page,
                            target_page_no=page_no,
                            query=query,
                            city_name=city_name,
                            verification_wait_seconds=int(normalized_source_options["verification_wait_seconds"]),
                            capture_debug_snapshot=bool(normalized_source_options["capture_debug_snapshot"]),
                            should_stop_callback=should_stop_callback,
                            progress_callback=progress_callback,
                        )
                    page_jobs = list(current_payload.get("items") or [])[:target_page_size]
                    payload_branch = detect_payload_branch(current_payload)
                    last_branch = payload_branch
                    city_branch_counts.setdefault(payload_branch, 0)
                    city_branch_counts[payload_branch] += 1
                    overall_branch_counts.setdefault(payload_branch, 0)
                    overall_branch_counts[payload_branch] += 1
                    debug_snapshot_path = clean_text(current_payload.get("debug_snapshot_path"))
                    if debug_snapshot_path:
                        last_debug_snapshot_path = debug_snapshot_path
                    if debug_snapshot_path and debug_snapshot_path not in debug_snapshot_paths:
                        debug_snapshot_paths.append(debug_snapshot_path)
                    if current_payload.get("from_dom") and city_name and city_name != "全国":
                        for job in page_jobs:
                            if not clean_text(job.get("city_name")):
                                job["city_name"] = city_name
                    page_jobs = [job for job in page_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
                    page_jobs = [job for job in page_jobs if city_matches(city_name, str(job.get("city_name") or ""))]
                    if not page_jobs:
                        if payload_branch == "pagination_end":
                            stop_reason = "pagination_end"
                            break
                        stop_reason = "empty_normalized"
                        emit_progress(
                            progress_callback,
                            f"拉勾 {query} - {city_name} 第 {page_no} 页没有可入库职位",
                            query=query,
                            city_name=city_name,
                            page=page_no,
                            branch=payload_branch,
                            branch_label=f"来源分支: {get_branch_label(payload_branch)}",
                            debug_snapshot_path=debug_snapshot_path,
                        )
                        break

                    page_signature = (query, city_name, "|".join(extract_page_signature_token(item) for item in page_jobs[:5]))
                    if page_signature in seen_page_signatures:
                        stop_reason = "duplicate_page"
                        emit_progress(progress_callback, f"拉勾 {query} - {city_name} 第 {page_no} 页出现重复分页签名，提前结束", query=query, city_name=city_name, page=page_no)
                        break
                    seen_page_signatures.add(page_signature)

                    all_seen_before_page = all(clean_text(job.get("source_job_id")) in seen_job_ids for job in page_jobs if clean_text(job.get("source_job_id")))
                    stats = save_to_db(page_jobs, source_code="lagou")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    city_fetched += len(page_jobs)
                    city_new += stats["new"]
                    city_updated += stats["updated"]
                    pages_completed = page_no
                    seen_job_ids.update(clean_text(job.get("source_job_id")) for job in page_jobs if clean_text(job.get("source_job_id")))
                    emit_progress(
                        progress_callback,
                        f"拉勾 {query} - {city_name} 第 {page_no} 页完成：抓取 {len(page_jobs)} 条，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                        branch=payload_branch,
                        branch_label=f"来源分支: {get_branch_label(payload_branch)}",
                        debug_snapshot_path=debug_snapshot_path,
                    )
                    if all_seen_before_page and bool(normalized_source_options["stop_on_all_seen_page"]):
                        stop_reason = "all_seen"
                        emit_progress(progress_callback, f"拉勾 {query} - {city_name} 第 {page_no} 页全部为已处理职位，提前结束", query=query, city_name=city_name, page=page_no)
                        break

                lagou_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "fetched_count": city_fetched,
                        "new_count": city_new,
                        "updated_count": city_updated,
                        "last_branch": last_branch,
                        "last_branch_label": get_branch_label(last_branch),
                        "branch_counts": {key: int(value) for key, value in city_branch_counts.items() if value},
                        "debug_snapshot_path": last_debug_snapshot_path,
                    }
                )

        emit_progress(progress_callback, f"拉勾采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条")
        return {
            "total_fetched": total_fetched,
            "new_to_db": total_new,
            "updated": total_updated,
            "queries": len(normalized_queries),
            "cities": len(normalized_cities),
            "runtime_mode": "browser",
            "detail_mode": "manual_verification_next_data_or_dom",
            "debug_snapshot_paths": debug_snapshot_paths,
            "lagou_summary": {
                "trace_count": len(lagou_trace),
                "branch_counts": {key: int(value) for key, value in overall_branch_counts.items() if value},
                "debug_snapshot_count": len(debug_snapshot_paths),
                "detail_mode": "manual_verification_next_data_or_dom",
            },
            "lagou_trace": lagou_trace,
        }
    finally:
        try:
            page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    print(json.dumps(run_incremental_update(), ensure_ascii=False))