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
WEB_BASE_URL = "https://fw.rc.qingdao.gov.cn"
HOME_URL = f"{WEB_BASE_URL}/zhaopin/"
LIST_PAGE_URL = f"{WEB_BASE_URL}/qdzhrcww/work/f60050102/showGw.action"
QUERY_URL = f"{WEB_BASE_URL}/qdzhrcww/work/f60050102/jzQuery.action"
PAGE_QUERY_URL = f"{WEB_BASE_URL}/qdzhrcww/work/f60050102/findQuery.action"
DETAIL_URL_TEMPLATE = WEB_BASE_URL + "/qdzhrcww/work/f60050102/toDetail.action?gwid={gwid}&sign={sign}"
FW_DETAIL_URL_TEMPLATE = WEB_BASE_URL + "/qdzhrcww/work/f60050102/toFwDetail.action?gwid={gwid}"
BSX_DETAIL_URL_TEMPLATE = WEB_BASE_URL + "/qdzhrcww/work/f60050102/toBsxDetail.action?gwid={gwid}"
DEFAULT_QUERIES = ["Java", "Python", "前端", "测试"]
DEFAULT_CITIES = ["青岛"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 15.0,
    "sleep_seconds": 0.0,
}
REQUEST_HEADERS = {
    "Referer": HOME_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}
AJAX_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": WEB_BASE_URL,
    "Referer": LIST_PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
}
SIGN_LABELS = {
    "1": "国企招聘",
    "2": "招聘e站",
    "3": "公益性招聘",
    "4": "赴外招聘",
    "5": "博士行",
}
QINGDAO_REGION_CODES = {
    "全国": "",
    "青岛": "",
    "青岛市": "",
    "全市": "",
    "市南区": "370202",
    "市北区": "370203",
    "李沧区": "370213",
    "崂山区": "370212",
    "西海岸新区": "370284",
    "黄岛区": "370284",
    "城阳区": "370214",
    "即墨区": "370282",
    "胶州市": "370281",
    "胶州": "370281",
    "平度市": "370283",
    "平度": "370283",
    "莱西市": "370285",
    "莱西": "370285",
    "高新区": "370286",
    "青岛高新区": "370286",
    "青岛蓝谷": "370270",
    "青岛市外": "370298",
}
QINGDAO_DISTRICTS = {name for name, code in QINGDAO_REGION_CODES.items() if code and name != "青岛市外"}


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
        emit_progress(progress_callback, "收到取消信号，准备停止青岛人才招聘e站采集", **context)
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
        raise RuntimeError("未安装 requests，无法执行青岛人才招聘e站采集")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def decode_response_text(response: requests.Response) -> str:
    candidates: list[str] = []
    for value in (response.encoding, getattr(response, "apparent_encoding", None), "utf-8", "gb18030", "gbk"):
        normalized = clean_text(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    best_text = response.text
    best_score = -1
    for encoding in candidates:
        try:
            text = response.content.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        score = sum(1 for marker in ("唯才", "青岛", "招聘", "岗位", "职位", "公司", "工作地点") if marker in text)
        if score > best_score:
            best_text = text
            best_score = score
    return best_text


def normalize_region_name(value: Any) -> str:
    text = clean_text(value)
    aliases = {
        "黄岛区": "西海岸新区",
        "青岛高新区": "高新区",
        "青岛市": "青岛",
    }
    return aliases.get(text, text)


def is_qingdao_region_text(value: Any) -> bool:
    text = normalize_region_name(value)
    return text in {"青岛", "全市"} or text in QINGDAO_DISTRICTS or "青岛" in text


def resolve_region_filter(city_name: str) -> tuple[str, bool, str]:
    normalized = normalize_region_name(city_name)
    if not normalized:
        return "", True, "青岛"
    if normalized in QINGDAO_REGION_CODES:
        return QINGDAO_REGION_CODES[normalized], True, normalized
    return "", False, normalized


def city_matches(target_city: str, *texts: Any) -> bool:
    normalized_target = normalize_region_name(target_city)
    if not normalized_target or normalized_target == "全国":
        return True
    if normalized_target in {"青岛", "全市"}:
        return any(is_qingdao_region_text(item) for item in texts if clean_text(item)) or True
    normalized_texts = [normalize_region_name(item) for item in texts if clean_text(item)]
    return any(
        normalized_target == item or normalized_target in item or item in normalized_target
        for item in normalized_texts
        if item
    )


def derive_city_and_district(location_text: str, target_city: str) -> tuple[str, str]:
    location = normalize_region_name(location_text)
    target = normalize_region_name(target_city)
    if location in QINGDAO_DISTRICTS:
        return "青岛", location
    if location in {"青岛", "全市"}:
        return "青岛", ""
    if "青岛" in location:
        return "青岛", location
    if target in QINGDAO_DISTRICTS:
        return "青岛", target
    if target in {"青岛", "全市"}:
        return "青岛", location if location in QINGDAO_DISTRICTS else ""
    if location:
        return location, ""
    return (target if target != "全国" else ""), ""


def build_detail_url(gwid: str, sign: str) -> str:
    normalized_sign = clean_text(sign) or "2"
    if normalized_sign == "4":
        return FW_DETAIL_URL_TEMPLATE.format(gwid=gwid)
    if normalized_sign == "5":
        return BSX_DETAIL_URL_TEMPLATE.format(gwid=gwid)
    return DETAIL_URL_TEMPLATE.format(gwid=gwid, sign=normalized_sign)


def fetch_json_page(
    session: requests.Session,
    *,
    query: str,
    page_no: int,
    region_code: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = QUERY_URL if page_no <= 1 else PAGE_QUERY_URL
    payload = {
        "startpage": str(max(1, page_no)),
        "qh": region_code,
        "nx": "",
        "xl": "",
        "gw": query,
        "xz": "",
        "gz": "",
        "lb": "",
        "gzz270": "",
        "cge090": "",
    }
    response = session.post(url, data=payload, headers=AJAX_HEADERS, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    items: list[dict[str, Any]] = []
    total_count = 0
    total_pages = 0
    if isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        items = [item for item in (data.get("data") or []) if isinstance(item, dict)]
        total_count = int(data.get("total") or 0)
    if items:
        page_hint = int(items[0].get("ys") or 0)
        if page_hint > 0:
            total_pages = page_hint
    if total_pages <= 0 and total_count > 0 and items:
        total_pages = (total_count + len(items) - 1) // len(items)
    return {
        "items": items,
        "page_no": page_no,
        "page_size": len(items),
        "total_pages": total_pages,
        "total_count": total_count,
        "endpoint": url,
    }


def fetch_job_detail_html(session: requests.Session, *, gwid: str, sign: str, timeout_seconds: float) -> str:
    if not gwid:
        return ""
    response = session.get(build_detail_url(gwid, sign), timeout=timeout_seconds)
    response.raise_for_status()
    return decode_response_text(response)


def warmup_listing(session: requests.Session, *, timeout_seconds: float) -> None:
    response = session.get(HOME_URL, timeout=timeout_seconds)
    response.raise_for_status()


def parse_detail_html(html_text: str) -> dict[str, Any]:
    if not html_text:
        return {}
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析青岛人才招聘e站详情页")
    soup = BeautifulSoup(html_text, "html.parser")

    title = clean_text(soup.select_one(".left-title .name").get_text(" ", strip=True) if soup.select_one(".left-title .name") else "")
    salary_text = clean_text(soup.select_one(".left-title .money").get_text(" ", strip=True) if soup.select_one(".left-title .money") else "")
    company_name = clean_text(soup.select_one(".bottom-item .company").get_text(" ", strip=True) if soup.select_one(".bottom-item .company") else "")
    top_meta_items = [clean_text(node.get_text(" ", strip=True)) for node in soup.select(".left-btn li") if clean_text(node.get_text(" ", strip=True))]

    section_map: dict[str, str] = {}
    plain_lines: list[str] = []
    for item in soup.select(".main-left-box .main-left-item"):
        title_node = item.select_one(".title")
        if title_node is None:
            plain_lines.extend(clean_text(node.get_text(" ", strip=True)) for node in item.select(".content2") if clean_text(node.get_text(" ", strip=True)))
            continue
        section_title = clean_text(title_node.get_text(" ", strip=True)).replace(" ", "")
        content_nodes = item.select(".content, .content2")
        content_text = clean_text("\n".join(node.get_text(" ", strip=True) for node in content_nodes if clean_text(node.get_text(" ", strip=True))))
        if section_title:
            section_map[section_title] = content_text

    label_values = [clean_text(node.get_text(" ", strip=True)) for node in soup.select(".main-right-box .lable .lable-text") if clean_text(node.get_text(" ", strip=True))]
    company_type = label_values[0] if len(label_values) > 0 else ""
    location_text = label_values[1] if len(label_values) > 1 else ""
    contact_phone = next((item for item in label_values if re.search(r"\d{7,}", item)), "")
    email = next((item for item in label_values if "@" in item), "")
    company_intro = ""
    for item in reversed(label_values):
        if item not in {company_type, location_text, contact_phone, email} and len(item) >= 12:
            company_intro = item
            break

    requirement_text = section_map.get("任职要求") or section_map.get("专业要求")
    description_text = section_map.get("岗位描述")
    other_text = section_map.get("其他要求")
    remark_text = section_map.get("备注")
    salary_detail_text = section_map.get("薪资待遇")
    address_text = location_text
    headcount = top_meta_items[-1] if top_meta_items and re.search(r"\d", top_meta_items[-1]) else ""

    return {
        "title": title,
        "salary_text": salary_text or salary_detail_text,
        "company_name": company_name,
        "degree_text": top_meta_items[-2] if len(top_meta_items) >= 2 else "",
        "experience_text": top_meta_items[0] if top_meta_items else "",
        "headcount": headcount,
        "company_type": company_type,
        "location_text": location_text,
        "address_text": address_text,
        "requirement_text": requirement_text,
        "description_text": description_text,
        "other_text": other_text,
        "remark_text": remark_text,
        "company_intro": company_intro,
        "contact_phone": contact_phone,
        "email": email,
        "extra_lines": plain_lines,
    }


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None, *, target_city: str = "") -> dict[str, Any]:
    detail = detail_item or {}
    gwid = clean_text(item.get("gwid"))
    sign = clean_text(item.get("sign") or "2")
    detail_url = build_detail_url(gwid, sign) if gwid else LIST_PAGE_URL
    location_text = clean_text(detail.get("location_text") or target_city)
    city_name, district_name = derive_city_and_district(location_text, target_city)
    description_lines = []
    for label, value in (
        ("任职要求", detail.get("requirement_text")),
        ("岗位描述", detail.get("description_text")),
        ("其他要求", detail.get("other_text")),
        ("备注", detail.get("remark_text")),
    ):
        cleaned = clean_text(value)
        if cleaned:
            description_lines.append(f"{label}：{cleaned}")
    if detail.get("extra_lines"):
        description_lines.extend(clean_text(line) for line in detail.get("extra_lines") if clean_text(line))
    if clean_text(detail.get("company_intro")):
        description_lines.append(f"公司简介：{clean_text(detail.get('company_intro'))}")
    if clean_text(detail.get("contact_phone")):
        description_lines.append(f"联系电话：{clean_text(detail.get('contact_phone'))}")
    if clean_text(detail.get("email")):
        description_lines.append(f"邮箱：{clean_text(detail.get('email'))}")
    sign_label = SIGN_LABELS.get(sign, "招聘e站")
    description_text = clean_text("\n".join(description_lines))
    return {
        "source_job_id": f"{sign}-{gwid}",
        "title": clean_text(detail.get("title") or item.get("gwname")),
        "company_name": clean_text(detail.get("company_name") or item.get("gab003")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(detail.get("salary_text") or item.get("xz")),
        "degree_text": clean_text(detail.get("degree_text") or item.get("xl")),
        "experience_text": clean_text(detail.get("experience_text") or item.get("gzjy")),
        "brand_scale": clean_text(detail.get("headcount") or item.get("rs")),
        "brand_stage": sign_label,
        "job_type": "",
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": description_text,
        "address_text": clean_text(detail.get("address_text") or location_text),
        "publisher": sign_label,
        "contact_phone": clean_text(detail.get("contact_phone")),
        "email": clean_text(detail.get("email")),
        "sign": sign,
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "qingdao_rc") -> dict[str, int]:
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
                    ("新职位发现", f"{company_name} 发布了 {title}（{city_name or '青岛'}）", cursor.lastrowid),
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
    region_code, supported, resolved_region = resolve_region_filter(city_name)
    if not supported:
        return {
            "pages": [],
            "matched_jobs": [],
            "api_pages": 0,
            "total_count": 0,
            "total_pages": 0,
            "upstream_page_size": 0,
            "supported": False,
            "resolved_region": resolved_region,
        }

    for page_no in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        payload = fetch_json_page(
            session,
            query=query,
            page_no=page_no,
            region_code=region_code,
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
            gwid = clean_text(raw_item.get("gwid"))
            sign = clean_text(raw_item.get("sign") or "2")
            if not gwid or gwid in seen_job_ids:
                continue
            detail_item: dict[str, Any] = {}
            if detail_mode == "detail_html":
                try:
                    html_text = fetch_job_detail_html(session, gwid=gwid, sign=sign, timeout_seconds=timeout_seconds)
                    detail_item = parse_detail_html(html_text)
                except Exception as exc:
                    emit_progress(
                        progress_callback,
                        f"青岛人才招聘e站详情补抓失败，回退列表字段：{exc}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                        source_code="qingdao_rc",
                        gwid=gwid,
                        sign=sign,
                    )
            job = normalize_job_item(raw_item, detail_item, target_city=resolved_region)
            if not clean_text(job.get("company_name")):
                continue
            if city_name != "全国" and not city_matches(city_name, job.get("city_name"), job.get("district_name"), job.get("address_text")):
                continue
            seen_job_ids.add(gwid)
            page_jobs.append(job)
            matched_jobs.append(job)

        emit_progress(
            progress_callback,
            f"青岛人才招聘e站 {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条",
            query=query,
            city_name=city_name,
            page=page_no,
            source_code="qingdao_rc",
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
        "supported": True,
        "resolved_region": resolved_region,
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
        raise RuntimeError("未安装 requests，无法执行青岛人才招聘e站采集")

    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 20))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    unsupported_locations: list[str] = []
    empty_result_locations: list[str] = []
    resolved_region_codes: dict[str, str] = {}
    request_trace: list[dict[str, Any]] = []

    session = build_session()
    emit_progress(progress_callback, "青岛人才招聘e站采集启动，模式 requests_api", source_code="qingdao_rc")
    try:
        warmup_listing(session, timeout_seconds=options["request_timeout_seconds"])
        for query in normalized_queries:
            for city_name in normalized_cities:
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                region_code, supported, resolved_region = resolve_region_filter(city_name)
                trace_item: dict[str, Any] = {
                    "query": query,
                    "location_name": city_name,
                    "resolved_region": resolved_region,
                    "region_code": region_code,
                    "status": "resolved" if supported else "unsupported_city",
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
                if not supported:
                    if city_name not in unsupported_locations:
                        unsupported_locations.append(city_name)
                    request_trace.append(trace_item)
                    emit_progress(
                        progress_callback,
                        f"青岛人才招聘e站暂不支持城市筛选 {city_name}，当前仅支持青岛及区县维度",
                        query=query,
                        city_name=city_name,
                        source_code="qingdao_rc",
                    )
                    continue

                resolved_region_codes[city_name] = region_code
                emit_progress(
                    progress_callback,
                    f"青岛人才招聘e站开始抓取 {query} - {city_name}",
                    query=query,
                    city_name=city_name,
                    page=1,
                    source_code="qingdao_rc",
                )
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
                    if city_name not in empty_result_locations:
                        empty_result_locations.append(city_name)
                    trace_item["status"] = "empty"
                    request_trace.append(trace_item)
                    emit_progress(
                        progress_callback,
                        f"青岛人才招聘e站 {query} - {city_name} 未命中职位",
                        query=query,
                        city_name=city_name,
                        source_code="qingdao_rc",
                    )
                    continue

                stats = save_to_db(jobs, source_code="qingdao_rc")
                total_fetched += len(jobs)
                total_new += stats["new"]
                total_updated += stats["updated"]
                trace_item["new_count"] = stats["new"]
                trace_item["updated_count"] = stats["updated"]
                request_trace.append(trace_item)
                emit_progress(
                    progress_callback,
                    f"青岛人才招聘e站 {query} - {city_name} 完成：抓取 {len(jobs)} 条，新增 {stats['new']} 条，更新 {stats['updated']} 条",
                    query=query,
                    city_name=city_name,
                    source_code="qingdao_rc",
                )
    finally:
        session.close()

    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated_in_db": total_updated,
        "queries": normalized_queries,
        "cities": normalized_cities,
        "detail_mode": options["detail_mode"],
        "resolved_region_codes": resolved_region_codes,
        "unsupported_locations": unsupported_locations,
        "empty_result_locations": empty_result_locations,
        "request_summary": {
            "total_targets": len(normalized_queries) * len(normalized_cities),
            "resolved_targets": len(request_trace) - len([item for item in request_trace if item.get('status') == 'unsupported_city']),
            "unsupported_targets": len([item for item in request_trace if item.get("status") == "unsupported_city"]),
            "empty_targets": len([item for item in request_trace if item.get("status") == "empty"]),
        },
        "request_trace": request_trace,
    }


if __name__ == "__main__":
    result = run_incremental_update()
    print(result)