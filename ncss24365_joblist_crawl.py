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
WEB_BASE_URL = "https://www.ncss.cn"
LIST_API_URL = f"{WEB_BASE_URL}/student/jobs/jobslist/ajax/"
DETAIL_URL_TEMPLATE = WEB_BASE_URL + "/student/jobs/{job_id}/detail.html"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州", "青岛"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 15.0,
    "sleep_seconds": 0.0,
    "job_type": "",
    "sources_name": "",
    "sources_type": "",
    "allow_empty_query": False,
}
CITY_CODE_MAP = {
    "北京": "110100",
    "上海": "310100",
    "广州": "440100",
    "深圳": "440300",
    "杭州": "330100",
    "成都": "510100",
    "武汉": "420100",
    "南京": "320100",
    "苏州": "320500",
    "青岛": "370200",
    "天津": "120100",
    "重庆": "500100",
    "西安": "610100",
    "长沙": "430100",
    "厦门": "350200",
    "宁波": "330200",
    "郑州": "410100",
    "合肥": "340100",
    "济南": "370100",
    "福州": "350100",
    "南昌": "360100",
    "石家庄": "130100",
    "太原": "140100",
    "呼和浩特": "150100",
    "大连": "210200",
    "沈阳": "210100",
    "长春": "220100",
    "哈尔滨": "230100",
    "无锡": "320200",
    "常州": "320400",
    "东莞": "441900",
    "佛山": "440600",
    "南宁": "450100",
    "海口": "460100",
    "贵阳": "520100",
    "昆明": "530100",
    "拉萨": "540100",
    "兰州": "620100",
    "西宁": "630100",
    "银川": "640100",
    "乌鲁木齐": "650100",
}
REQUEST_HEADERS = {
    "Referer": f"{WEB_BASE_URL}/student/jobs/index.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
INTERN_LIST_REFERER_URL = "https://job.ncss.cn/student/jobs/internindex.html"


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
        emit_progress(progress_callback, "收到取消信号，准备停止 24365 采集", **context)
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


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = clean_text(value).lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_job_type(value: Any) -> str:
    normalized = clean_text(value).lower()
    if normalized in {"", "fulltime", "full_time", "job", "职位", "全职"}:
        return ""
    if normalized in {"03", "intern", "internship", "shixi", "实习"}:
        return "03"
    return clean_text(value)


def normalize_queries(queries: list[str] | None, *, allow_empty: bool = False) -> list[str]:
    if allow_empty:
        if queries is None:
            return [""]
        values = [clean_text(item) for item in queries if clean_text(item)]
        return values or [""]

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
    try:
        request_timeout_seconds = float(options.get("request_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    except (TypeError, ValueError):
        request_timeout_seconds = float(DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    try:
        sleep_seconds = float(options.get("sleep_seconds") or DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    except (TypeError, ValueError):
        sleep_seconds = float(DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    job_type = normalize_job_type(options.get("job_type"))
    sources_name = clean_text(options.get("sources_name"))
    sources_type = clean_text(options.get("sources_type"))
    allow_empty_query = parse_bool(options.get("allow_empty_query"), default=bool(job_type))
    return {
        "detail_mode": detail_mode if detail_mode in {"list_only", "detail_html"} else "detail_html",
        "request_timeout_seconds": max(5.0, min(request_timeout_seconds, 60.0)),
        "sleep_seconds": max(0.0, min(sleep_seconds, 5.0)),
        "job_type": job_type,
        "sources_name": sources_name,
        "sources_type": sources_type,
        "allow_empty_query": allow_empty_query,
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
        raise RuntimeError("未安装 requests，无法执行 24365 采集")
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


def resolve_city_code(city_name: str) -> str | None:
    normalized_city = clean_text(city_name)
    if not normalized_city or normalized_city == "全国":
        return None
    return CITY_CODE_MAP.get(normalized_city)


def normalize_salary_text(low_month_pay: Any, high_month_pay: Any) -> str:
    try:
        low = float(low_month_pay or 0)
    except (TypeError, ValueError):
        low = 0.0
    try:
        high = float(high_month_pay or 0)
    except (TypeError, ValueError):
        high = 0.0
    if low <= 0 and high <= 0:
        return "面议"
    if low > 0 and high > 0:
        low_text = f"{low:.1f}".rstrip("0").rstrip(".")
        high_text = f"{high:.1f}".rstrip("0").rstrip(".")
        return f"{low_text}-{high_text}K"
    value = high if high > 0 else low
    return f"{f'{value:.1f}'.rstrip('0').rstrip('.')}K"


def fetch_job_list_page(
    session: requests.Session,
    *,
    query: str,
    page_no: int,
    page_size: int,
    area_code: str | None,
    timeout_seconds: float,
    job_type: str = "",
    sources_name: str = "",
    sources_type: str = "",
) -> dict[str, Any]:
    params = {
        "offset": page_no,
        "limit": page_size,
        "jobName": query,
        "areaCode": area_code or "",
        "jobType": job_type,
        "sourcesName": sources_name,
        "sourcesType": sources_type,
    }
    response = session.get(LIST_API_URL, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("flag"):
        messages: list[str] = []
        for item in payload.get("global") or []:
            if isinstance(item, dict) and clean_text(item.get("des")):
                messages.append(clean_text(item.get("des")))
        for item in payload.get("errors") or []:
            if isinstance(item, dict) and clean_text(item.get("des")):
                messages.append(clean_text(item.get("des")))
            elif clean_text(item):
                messages.append(clean_text(item))
        message_text = "；".join(messages) if messages else "24365 列表接口返回异常"
        raise RuntimeError(message_text)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    pagination = data.get("pagenation") if isinstance(data.get("pagenation"), dict) else {}
    items = [item for item in (data.get("list") or []) if isinstance(item, dict) and clean_text(item.get("jobId"))]
    return {
        "items": items,
        "page_no": int(pagination.get("offset") or page_no),
        "page_size": int(pagination.get("limit") or page_size),
        "total_pages": int(pagination.get("total") or 0),
        "total_count": int(pagination.get("count") or 0),
    }


def fetch_job_detail_html(session: requests.Session, *, job_id: str, timeout_seconds: float) -> str:
    if not job_id:
        return ""
    response = session.get(DETAIL_URL_TEMPLATE.format(job_id=job_id), timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def _extract_company_detail_map(soup: Any) -> dict[str, str]:
    detail_map: dict[str, str] = {}
    for item in soup.select(".con-right .company ul.details li"):
        label_node = item.select_one(".ico")
        value_node = item.select_one("span.show.fr")
        label = clean_text(label_node.get_text(" ", strip=True) if label_node else "")
        value = clean_text(value_node.get_text(" ", strip=True) if value_node else "")
        if label:
            detail_map[label] = value
    return detail_map


def parse_detail_html(html: str) -> dict[str, Any]:
    if not html:
        return {}
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析 24365 详情页")
    soup = BeautifulSoup(html, "html.parser")
    job_title = clean_text((soup.select_one("#jobName") or soup.select_one(".job-title")).get_text(" ", strip=True) if (soup.select_one("#jobName") or soup.select_one(".job-title")) else "")
    job_type = clean_text((soup.select_one("ul.work li:nth-of-type(2)") or {}).get_text(" ", strip=True) if soup.select_one("ul.work li:nth-of-type(2)") else "").strip("[]")
    salary_text = clean_text((soup.select_one("ul.salary li:nth-of-type(1) span") or {}).get_text(" ", strip=True) if soup.select_one("ul.salary li:nth-of-type(1) span") else "")
    degree_text = clean_text((soup.select_one("ul.salary li:nth-of-type(3) span") or {}).get_text(" ", strip=True) if soup.select_one("ul.salary li:nth-of-type(3) span") else "")
    address_text = clean_text((soup.select_one("ul.address .site-tag") or {}).get_text(" ", strip=True) if soup.select_one("ul.address .site-tag") else "")
    company_name = clean_text((soup.select_one("#realCorpName") or {}).get_text(" ", strip=True) if soup.select_one("#realCorpName") else "")
    major = clean_text((soup.select_one(".major-bl .major") or {}).get_text(" ", strip=True) if soup.select_one(".major-bl .major") else "")
    source_name_ch = clean_text((soup.select_one(".source-rl .source-sp") or {}).get_text(" ", strip=True) if soup.select_one(".source-rl .source-sp") else "")
    source_name = clean_text((soup.select_one("#sourcesName") or {}).get_text(" ", strip=True) if soup.select_one("#sourcesName") else "")
    description_text = clean_text((soup.select_one(".jobdetail-box .mainContent") or {}).get_text("\n", strip=True) if soup.select_one(".jobdetail-box .mainContent") else "")
    detail_map = _extract_company_detail_map(soup)
    return {
        "title": job_title,
        "company_name": company_name,
        "job_type": job_type,
        "salary_text": salary_text,
        "degree_text": degree_text,
        "address_text": address_text,
        "major": major,
        "source_name_ch": source_name_ch,
        "source_name": source_name,
        "description_text": description_text,
        "industry_text": detail_map.get("所属行业", ""),
        "brand_stage": detail_map.get("公司性质", ""),
        "brand_scale": detail_map.get("公司规模", ""),
        "company_address": detail_map.get("所在地址", ""),
    }


def extract_city_name(address_text: str, fallback_area: str = "") -> str:
    value = clean_text(address_text)
    if value:
        match = re.search(r"([\u4e00-\u9fff]{2,}(?:自治州|地区|盟|市))", value)
        if match:
            return simplify_area_name(match.group(1))
    return simplify_area_name(fallback_area)


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None, *, target_city: str = "") -> dict[str, Any]:
    detail = detail_item or {}
    job_id = clean_text(item.get("jobId"))
    detail_url = DETAIL_URL_TEMPLATE.format(job_id=job_id) if job_id else f"{WEB_BASE_URL}/student/jobs/index.html"
    address_text = clean_text(detail.get("address_text") or item.get("areaCodeName"))
    company_address = clean_text(detail.get("company_address"))
    city_name = extract_city_name(address_text, clean_text(item.get("areaCodeName")))
    if not city_name and target_city and target_city != "全国":
        city_name = clean_text(target_city)
    district_name = address_text if address_text and address_text != city_name else company_address
    description_text = clean_text(detail.get("description_text"))
    extra_lines = []
    if clean_text(detail.get("major") or item.get("major")):
        extra_lines.append(f"专业要求：{clean_text(detail.get('major') or item.get('major'))}")
    if clean_text(detail.get("source_name_ch") or item.get("sourcesNameCh")):
        extra_lines.append(f"来源：{clean_text(detail.get('source_name_ch') or item.get('sourcesNameCh'))}")
    if clean_text(detail.get("industry_text")):
        extra_lines.append(f"所属行业：{clean_text(detail.get('industry_text'))}")
    if company_address:
        extra_lines.append(f"单位地址：{company_address}")
    if extra_lines:
        description_text = clean_text("\n".join([description_text, *extra_lines]))
    return {
        "source_job_id": job_id,
        "title": clean_text(detail.get("title") or item.get("jobName")),
        "company_name": clean_text(detail.get("company_name") or item.get("recName")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(detail.get("salary_text")) or normalize_salary_text(item.get("lowMonthPay"), item.get("highMonthPay")),
        "degree_text": clean_text(detail.get("degree_text") or item.get("degreeName")),
        "experience_text": "",
        "brand_scale": clean_text(detail.get("brand_scale") or item.get("recScale")),
        "brand_stage": clean_text(detail.get("brand_stage") or item.get("recProperty")),
        "job_type": clean_text(detail.get("job_type")),
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": description_text,
        "source_name": clean_text(detail.get("source_name") or item.get("sourcesName")),
        "source_name_ch": clean_text(detail.get("source_name_ch") or item.get("sourcesNameCh")),
        "address_text": address_text,
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "ncss24365") -> dict[str, int]:
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
    area_code: str | None,
    max_pages: int,
    page_size: int,
    detail_mode: str,
    timeout_seconds: float,
    sleep_seconds: float,
    job_type: str,
    sources_name: str,
    sources_type: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    logical_pages: list[list[dict[str, Any]]] = []
    matched_jobs: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    total_pages = 0
    total_count = 0
    stop_reason = "completed"

    for page_no in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        try:
            payload = fetch_job_list_page(
                session,
                query=query,
                page_no=page_no,
                page_size=page_size,
                area_code=area_code,
                timeout_seconds=timeout_seconds,
                job_type=job_type,
                sources_name=sources_name,
                sources_type=sources_type,
            )
        except RuntimeError as exc:
            error_text = clean_text(str(exc))
            if page_no > 1 and "请登录后查看" in error_text:
                emit_progress(
                    progress_callback,
                    f"24365 {query or '全部'} - {city_name} 第 {page_no} 页命中登录墙，按可访问尾页结束",
                    query=query or "全部",
                    city_name=city_name,
                    page=page_no,
                    source_code="ncss24365",
                    stop_reason="login_wall",
                )
                stop_reason = "login_wall"
                break
            raise
        items = list(payload.get("items") or [])
        total_pages = int(payload.get("total_pages") or total_pages)
        total_count = int(payload.get("total_count") or total_count)
        if not items:
            stop_reason = "empty_page"
            break

        page_jobs: list[dict[str, Any]] = []
        for raw_item in items:
            job_id = clean_text(raw_item.get("jobId"))
            if not job_id or job_id in seen_job_ids:
                continue
            detail_item: dict[str, Any] = {}
            if detail_mode == "detail_html":
                html = fetch_job_detail_html(session, job_id=job_id, timeout_seconds=timeout_seconds)
                detail_item = parse_detail_html(html)
            job = normalize_job_item(raw_item, detail_item, target_city=city_name)
            if city_name != "全国" and not city_matches(city_name, job.get("city_name"), job.get("district_name"), job.get("address_text")):
                continue
            seen_job_ids.add(job_id)
            page_jobs.append(job)
            matched_jobs.append(job)
        emit_progress(
            progress_callback,
            f"24365 {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条",
            query=query,
            city_name=city_name,
            page=page_no,
            source_code="ncss24365",
        )
        if page_jobs:
            logical_pages.append(page_jobs)
        if sleep_seconds > 0:
            safe_sleep(sleep_seconds, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        if total_pages > 0 and page_no >= total_pages:
            stop_reason = "reached_total_pages"
            break
        if page_no >= max_pages:
            stop_reason = "target_pages_reached"

    return {
        "pages": logical_pages,
        "matched_jobs": matched_jobs,
        "api_pages": min(max_pages, total_pages if total_pages > 0 else max_pages),
        "total_count": total_count,
        "total_pages": total_pages,
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
    del output_dir, runtime_mode
    configure_stdio()
    ensure_db()
    if requests is None:
        raise RuntimeError("未安装 requests，无法执行 24365 采集")

    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(queries, allow_empty=bool(options["allow_empty_query"]))
    normalized_cities = normalize_cities(cities)
    target_pages = max(1, min(int(max_pages or 1), 10))
    target_page_size = max(1, min(int(page_size or 20), 50))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    resolved_city_codes: dict[str, str] = {}
    unresolved_locations: list[str] = []
    fallback_to_national_locations: list[str] = []
    empty_result_locations: list[str] = []
    request_trace: list[dict[str, Any]] = []

    session = build_session()
    if hasattr(session, "headers") and isinstance(session.headers, dict):
        session.headers["Referer"] = INTERN_LIST_REFERER_URL if str(options["job_type"]) == "03" else REQUEST_HEADERS["Referer"]
    job_mode_label = "实习聚合" if str(options["job_type"]) == "03" else "职位信息"
    emit_progress(progress_callback, f"24365 采集启动，模式 requests_api，口径 {job_mode_label}", source_code="ncss24365")
    try:
        for query in normalized_queries:
            for city_name in normalized_cities:
                display_query = query or "全部"
                ensure_not_cancelled(should_stop_callback, progress_callback, query=display_query, city_name=city_name, page=1)
                area_code = resolve_city_code(city_name)
                trace_item: dict[str, Any] = {
                    "query": query,
                    "location_name": city_name,
                    "area_code": area_code or "",
                    "job_type": str(options["job_type"]),
                    "sources_name": str(options["sources_name"]),
                    "sources_type": str(options["sources_type"]),
                    "status": "pending",
                    "target_pages": target_pages,
                    "page_size": target_page_size,
                    "api_pages_used": 0,
                    "upstream_total_count": 0,
                    "upstream_total_pages": 0,
                    "logical_pages": 0,
                    "fetched_count": 0,
                    "new_count": 0,
                    "updated_count": 0,
                }
                if city_name != "全国" and not area_code:
                    if city_name not in unresolved_locations:
                        unresolved_locations.append(city_name)
                    if city_name not in fallback_to_national_locations:
                        fallback_to_national_locations.append(city_name)
                    trace_item["status"] = "fallback_national"
                    emit_progress(
                        progress_callback,
                        f"24365 未内置城市码 {city_name}，回退为全国检索后按详情地址过滤",
                        query=display_query,
                        city_name=city_name,
                        source_code="ncss24365",
                    )
                elif area_code:
                    resolved_city_codes[city_name] = area_code
                    trace_item["status"] = "resolved"

                emit_progress(progress_callback, f"24365 开始抓取 {display_query} - {city_name}", query=display_query, city_name=city_name, page=1, source_code="ncss24365")
                collect_result = collect_filtered_jobs(
                    session,
                    query=query,
                    city_name=city_name,
                    area_code=area_code,
                    max_pages=target_pages,
                    page_size=target_page_size,
                    detail_mode=str(options["detail_mode"]),
                    timeout_seconds=float(options["request_timeout_seconds"]),
                    sleep_seconds=float(options["sleep_seconds"]),
                    job_type=str(options["job_type"]),
                    sources_name=str(options["sources_name"]),
                    sources_type=str(options["sources_type"]),
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                logical_pages = [page_jobs for page_jobs in (collect_result.get("pages") or []) if page_jobs]
                trace_item["api_pages_used"] = int(collect_result.get("api_pages") or 0)
                trace_item["upstream_total_count"] = int(collect_result.get("total_count") or 0)
                trace_item["upstream_total_pages"] = int(collect_result.get("total_pages") or 0)
                trace_item["logical_pages"] = len(logical_pages)
                trace_item["stop_reason"] = clean_text(collect_result.get("stop_reason"))

                if not logical_pages:
                    trace_item["status"] = "empty"
                    request_trace.append(trace_item)
                    if city_name not in empty_result_locations:
                        empty_result_locations.append(city_name)
                    emit_progress(progress_callback, f"24365 {display_query} - {city_name} 未解析到职位", query=display_query, city_name=city_name, source_code="ncss24365")
                    continue

                location_fetched = 0
                location_new = 0
                location_updated = 0
                for logical_page_no, page_jobs in enumerate(logical_pages, start=1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=display_query, city_name=city_name, page=logical_page_no)
                    stats = save_to_db(page_jobs, source_code="ncss24365")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    location_fetched += len(page_jobs)
                    location_new += stats["new"]
                    location_updated += stats["updated"]
                    emit_progress(
                        progress_callback,
                        f"24365 {display_query} - {city_name} 第 {logical_page_no} 页完成：抓取 {len(page_jobs)} 条，新增 {stats['new']}，更新 {stats['updated']}",
                        query=display_query,
                        city_name=city_name,
                        page=logical_page_no,
                        source_code="ncss24365",
                    )

                trace_item["fetched_count"] = location_fetched
                trace_item["new_count"] = location_new
                trace_item["updated_count"] = location_updated
                trace_item["status"] = trace_item["status"] if trace_item["status"] == "fallback_national" else "resolved"
                request_trace.append(trace_item)
    finally:
        session.close()

    emit_progress(progress_callback, f"24365 采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条", source_code="ncss24365")
    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated": total_updated,
        "queries": len(normalized_queries),
        "cities": len(normalized_cities),
        "runtime_mode": "requests_only",
        "detail_mode": options["detail_mode"],
        "job_type": options["job_type"],
        "sources_name": options["sources_name"],
        "sources_type": options["sources_type"],
        "resolved_city_codes": resolved_city_codes,
        "unresolved_locations": unresolved_locations,
        "request_trace": request_trace,
        "request_summary": {
            "total_targets": len(request_trace),
            "resolved_targets": sum(1 for item in request_trace if item.get("status") == "resolved"),
            "fallback_targets": len(fallback_to_national_locations),
            "empty_targets": len(empty_result_locations),
            "login_wall_targets": sum(1 for item in request_trace if item.get("stop_reason") == "login_wall"),
        },
        "fallback_to_national_locations": fallback_to_national_locations,
        "empty_result_locations": empty_result_locations,
    }
