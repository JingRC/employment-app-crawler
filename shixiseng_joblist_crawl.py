from __future__ import annotations

import json
import hashlib
import math
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None

import requests


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
BASE_URL = "https://www.shixiseng.com"
SEARCH_API_URL = f"{BASE_URL}/app/interns/search/v2"
DETAIL_API_URL = f"{BASE_URL}/proxy-prefix/new-intern-api-host/api/interns/v3.0/interns/info/wxz"
COMPANY_API_URL = f"{BASE_URL}/proxy-prefix/new-intern-api-host/api/interns/v3.0/company/info/wxz"
PCXZ_API_BASE = f"{BASE_URL}/proxy-prefix/new-intern-api-host/api/interns/v3.0/pcxz"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州"]
DEFAULT_WAIT_SECONDS = 4.0
DETAIL_WAIT_SECONDS = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_DETAIL_WORKERS = 4
DEFAULT_DETAIL_RATE_PER_SECOND = 1.5
DEFAULT_TRACK = "all"

CITY_ALIASES = {
    "全国站": "全国",
    "全国": "全国",
    "北京市": "北京",
    "上海市": "上海",
    "广州市": "广州",
    "深圳市": "深圳",
    "杭州市": "杭州",
    "成都市": "成都",
    "武汉市": "武汉",
    "南京市": "南京",
    "苏州市": "苏州",
    "济南市": "济南",
    "青岛市": "青岛",
}

STATE_OWNED_KEYWORDS = (
    "央企",
    "国企",
    "国有",
    "国资",
    "事业单位",
    "国家电网",
    "南方电网",
    "国家能源集团",
    "三峡集团",
    "中广核",
    "中石油",
    "中石化",
    "中海油",
    "中国移动",
    "中国联通",
    "中国电信",
    "中国建筑",
    "中国中铁",
    "中国铁建",
    "中国交建",
    "中国中车",
    "中国电子",
    "中国电科",
    "航天科技",
    "航天科工",
    "中航工业",
    "中船集团",
    "华润",
    "招商局",
    "中粮",
    "中远海运",
    "中国能建",
    "中国电建",
    "交投",
    "城投",
    "地铁集团",
)

STATE_OWNED_GROUP_RULES = (
    (("电网", "电力", "能源", "三峡", "中广核", "国家能源", "中国能建", "中国电建"), "电力能源央国企"),
    (("移动", "联通", "电信", "运营商"), "通信运营商"),
    (("中铁", "铁建", "交建", "中车", "建筑", "地铁", "交投", "城投"), "基建交通央国企"),
    (("航天", "中航", "中船", "电科", "中国电子", "军工"), "军工电子央国企"),
    (("中石油", "中石化", "中海油"), "石油化工央国企"),
)

MANUAL_FAMOUS_COMPANY_LINKS = (
    {
        "company_name": "阿里巴巴",
        "aliases": ("阿里巴巴", "阿里巴巴集团"),
        "official_site_url": "https://www.alibabagroup.com/",
        "career_site_url": "https://www.alibabagroup.com/careers",
    },
    {
        "company_name": "TCL实业",
        "aliases": ("TCL实业", "TCL"),
        "official_site_url": "https://www.tcl.com/cn/zh",
        "career_site_url": "https://campus.tcl.com/",
    },
    {
        "company_name": "安克创新",
        "aliases": ("安克创新", "Anker"),
        "official_site_url": "https://www.anker.com.cn/",
        "career_site_url": "https://career.anker.com.cn",
    },
    {
        "company_name": "真格基金",
        "aliases": ("真格基金",),
        "official_site_url": "https://www.zhenfund.com/",
        "career_site_url": "https://www.zhenfund.com/Contact",
    },
    {
        "company_name": "深南电路",
        "aliases": ("深南电路",),
        "official_site_url": "https://www.scc.com.cn/",
        "career_site_url": "https://scc.zhiye.com/campus/jobs",
    },
    {
        "company_name": "心田花开",
        "aliases": ("心田花开", "心田花开网校"),
        "official_site_url": "https://www.xthk.cn/",
        "career_site_url": "",
    },
    {
        "company_name": "深圳市正浩创新科技股份有限公司",
        "aliases": ("深圳市正浩创新科技股份有限公司", "正浩创新", "EcoFlow"),
        "official_site_url": "https://www.ecoflow.com/cn",
        "career_site_url": "https://jobs.ecoflow.com/index",
    },
    {
        "company_name": "科锐国际",
        "aliases": ("科锐国际", "Career International"),
        "official_site_url": "https://www.careerintlinc.com/",
        "career_site_url": "https://ats.careerintlinc.com/home",
    },
    {
        "company_name": "自如",
        "aliases": ("自如",),
        "official_site_url": "https://www.ziroom.com/",
        "career_site_url": "https://job.ziroom.com/home",
    },
    {
        "company_name": "江波龙",
        "aliases": ("江波龙", "Longsys"),
        "official_site_url": "https://www.longsys.com/",
        "career_site_url": "",
    },
)


class CrawlCancelledError(Exception):
    pass


class DetailRateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self._min_interval = 0.0 if rate_per_second <= 0 else 1.0 / rate_per_second
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(
        self,
        *,
        should_stop_callback: Callable[[], bool] | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        **context: Any,
    ) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_allowed - now)
            base = max(now, self._next_allowed)
            self._next_allowed = base + self._min_interval
        if wait_seconds > 0:
            safe_sleep(wait_seconds, should_stop_callback, progress_callback, **context)


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
        emit_progress(progress_callback, "收到取消信号，准备停止实习僧采集", **context)
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS featured_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_code TEXT NOT NULL DEFAULT 'featured_famous',
            company_type TEXT NOT NULL DEFAULT 'famous_enterprise',
            group_name TEXT DEFAULT '',
            source_code TEXT NOT NULL DEFAULT 'shixiseng',
            company_uuid TEXT NOT NULL,
            company_name TEXT NOT NULL,
            city_text TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            scale_text TEXT DEFAULT '',
            module_name TEXT DEFAULT '',
            description_text TEXT DEFAULT '',
            official_site_url TEXT DEFAULT '',
            career_site_url TEXT DEFAULT '',
            extra_json TEXT DEFAULT '',
            unique_hash TEXT UNIQUE,
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    existing_columns = {
        str(row[1]).lower()
        for row in conn.execute("PRAGMA table_info(featured_companies)").fetchall()
    }
    if "board_code" not in existing_columns:
        conn.execute("ALTER TABLE featured_companies ADD COLUMN board_code TEXT NOT NULL DEFAULT 'featured_famous'")
    if "company_type" not in existing_columns:
        conn.execute("ALTER TABLE featured_companies ADD COLUMN company_type TEXT NOT NULL DEFAULT 'famous_enterprise'")
    if "group_name" not in existing_columns:
        conn.execute("ALTER TABLE featured_companies ADD COLUMN group_name TEXT DEFAULT ''")
    if "official_site_url" not in existing_columns:
        conn.execute("ALTER TABLE featured_companies ADD COLUMN official_site_url TEXT DEFAULT ''")
    if "career_site_url" not in existing_columns:
        conn.execute("ALTER TABLE featured_companies ADD COLUMN career_site_url TEXT DEFAULT ''")
    conn.execute(
        """
        UPDATE featured_companies
        SET board_code='featured_famous'
        WHERE COALESCE(board_code, '')=''
        """
    )
    conn.execute(
        """
        UPDATE featured_companies
        SET company_type='famous_enterprise'
        WHERE COALESCE(company_type, '')=''
        """
    )
    conn.execute(
        """
        UPDATE featured_companies
        SET group_name=COALESCE(NULLIF(module_name, ''), '校招名企')
        WHERE COALESCE(group_name, '')=''
        """
    )
    conn.commit()
    conn.close()


def normalize_featured_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def resolve_featured_company_links(company_name: str) -> dict[str, str]:
    normalized_company_name = normalize_featured_text(company_name)
    if not normalized_company_name:
        return {
            "official_site_url": "",
            "career_site_url": "",
        }

    for item in MANUAL_FAMOUS_COMPANY_LINKS:
        aliases = tuple(normalize_featured_text(alias) for alias in item.get("aliases") or (item["company_name"],))
        if any(
            alias and (normalized_company_name == alias or normalized_company_name in alias or alias in normalized_company_name)
            for alias in aliases
        ):
            return {
                "official_site_url": str(item.get("official_site_url") or ""),
                "career_site_url": str(item.get("career_site_url") or ""),
            }

    return {
        "official_site_url": "",
        "career_site_url": "",
    }


def build_browser_options() -> ChromiumOptions:
    if ChromiumOptions is None:
        raise RuntimeError("未安装 DrissionPage，无法执行实习僧浏览器采集")

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
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(source_options or {})
    track = str(options.get("track") or DEFAULT_TRACK).strip().lower() or DEFAULT_TRACK
    if track not in {"all", "intern", "campus"}:
        track = DEFAULT_TRACK
    detail_workers = int(options.get("detail_workers") or DEFAULT_DETAIL_WORKERS)
    detail_rate = float(options.get("detail_rate_per_second") or DEFAULT_DETAIL_RATE_PER_SECOND)
    include_campus_home_modules = parse_bool_option(options.get("include_campus_home_modules"), True)
    campus_hotintern_city = str(options.get("campus_hotintern_city") or "推荐").strip() or "推荐"
    campus_hotcompany_industry = str(options.get("campus_hotcompany_industry") or "推荐").strip() or "推荐"
    return {
        "track": track,
        "detail_workers": max(1, min(detail_workers, 8)),
        "detail_rate_per_second": max(0.1, min(detail_rate, 10.0)),
        "include_campus_home_modules": include_campus_home_modules,
        "campus_hotintern_city": campus_hotintern_city,
        "campus_hotcompany_industry": campus_hotcompany_industry,
    }


def infer_featured_company_metadata(item: dict[str, Any], module_name: str) -> dict[str, str]:
    company_name = str(item.get("company_name") or item.get("name") or "").strip()
    industry = str(item.get("industry") or "").strip()
    description = str(item.get("description") or "").strip()
    combined_text = " ".join(part for part in [company_name, industry, description, str(module_name or "").strip()] if part)

    if any(keyword in combined_text for keyword in STATE_OWNED_KEYWORDS):
        company_type = "state_owned_enterprise"
        if any(keyword in combined_text for keyword in ("央企", "国家电网", "南方电网", "国家能源集团", "三峡集团", "中广核", "中石油", "中石化", "中海油", "中国移动", "中国联通", "中国电信", "中国建筑", "中国中铁", "中国铁建", "中国交建", "中国中车", "中国电子", "中国电科", "航天科技", "航天科工", "中航工业", "中船集团", "华润", "招商局", "中粮", "中远海运", "中国能建", "中国电建")):
            company_type = "central_soe"
        elif any(keyword in combined_text for keyword in ("地方国企", "城投", "交投", "地铁集团", "文旅集团", "国资委")):
            company_type = "local_soe"
        group_name = "央国企目录"
        for keywords, candidate_group_name in STATE_OWNED_GROUP_RULES:
            if any(keyword in combined_text for keyword in keywords):
                group_name = candidate_group_name
                break
        return {
            "board_code": "featured_soe",
            "company_type": company_type,
            "group_name": group_name,
        }

    return {
        "board_code": "featured_famous",
        "company_type": "famous_enterprise",
        "group_name": str(module_name or "").strip() or "校招名企",
    }


def build_search_url(query: str, city_name: str, page: int) -> str:
    params = {
        "keyword": query,
        "page": str(page),
    }
    if city_name and city_name != "全国":
        params["city"] = city_name
    return f"{BASE_URL}/interns?{urlencode(params)}"


def build_search_api_params(query: str, city_name: str, page: int, track: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "page": page,
        "keyword": query,
    }
    if city_name and city_name != "全国":
        params["city"] = city_name
    if track == "campus":
        params["intern_type"] = "xz"
    return params


def build_detail_url(job_uuid: str) -> str:
    return f"{BASE_URL}/intern/{job_uuid}?pcm=pc_SearchList"


def extract_nuxt_data(page: Any) -> dict[str, Any]:
    payload = page.run_js("return window.__NUXT__")
    return payload if isinstance(payload, dict) else {}


def build_cookie_header(page: Any) -> str:
    cookies = page.cookies(all_domains=True, all_info=False)
    if isinstance(cookies, dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items())
    return str(cookies or "")


def build_requests_session(cookie_header: str, referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
            "Cookie": cookie_header,
        }
    )
    return session


def build_api_session(referer: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": referer,
        }
    )
    return session


def build_pcxz_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://resume.shixiseng.com/xiaozhao",
        }
    )
    return session


def extract_nuxt_script(html: str) -> str:
    match = re.search(r"__NUXT__=(.*?)(?:</script>|;\(function)", html, re.S)
    return match.group(1) if match else ""


def extract_js_string(script: str, field_name: str) -> str:
    match = re.search(rf"\.{re.escape(field_name)}=(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')", script)
    if not match:
        return ""
    literal = match.group(1)
    if literal.startswith("'"):
        literal = '"' + literal[1:-1].replace('\\"', '"').replace('"', '\\"') + '"'
    try:
        return json.loads(literal)
    except json.JSONDecodeError:
        return literal.strip("\"'")


def extract_js_number(script: str, field_name: str) -> int | None:
    match = re.search(rf"\.{re.escape(field_name)}=(-?\d+)", script)
    if not match:
        return None
    return int(match.group(1))


def extract_js_array(script: str, field_name: str) -> list[str]:
    match = re.search(rf"\.{re.escape(field_name)}=\[(.*?)\]", script, re.S)
    if not match:
        return []
    return [
        json.loads(item)
        for item in re.findall(r'\"(?:\\.|[^\"])*\"', match.group(1))
    ]


def load_search_api_page_with_retry(
    query: str,
    city_name: str,
    page_no: int,
    track: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    params = build_search_api_params(query, city_name, page_no, track)
    referer = build_search_url(query, city_name, page_no)
    last_total = 0
    last_page_number = 1
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        session = build_api_session(referer)
        response = session.get(SEARCH_API_URL, params=params, timeout=25)
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if int(payload.get("code") or 100) == 100:
                msg = payload.get("msg") or {}
                items = msg.get("data") or []
                total = int(msg.get("total") or 0)
                page_number = int(msg.get("pageNumber") or 1)
                normalized_items = [item for item in items if isinstance(item, dict) and item.get("uuid")]
                if normalized_items:
                    return normalized_items, total, page_number
                last_total = total
                last_page_number = page_number
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"实习僧搜索接口 {query} - {city_name} 第 {page_no} 页失败，准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
    return [], last_total, last_page_number


def load_detail_api_with_retry(
    job_uuid: str,
    *,
    query: str,
    city_name: str,
    page_no: int,
    rate_limiter: DetailRateLimiter,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    referer = build_search_url(query, city_name, page_no)
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        rate_limiter.wait(should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        session = build_api_session(referer)
        response = session.get(DETAIL_API_URL, params={"uuid": job_uuid}, timeout=25)
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if int(payload.get("code") or 100) == 100:
                detail_item = payload.get("msg") or {}
                if isinstance(detail_item, dict) and (detail_item.get("iname") or detail_item.get("job")):
                    detail_item.setdefault("uuid", job_uuid)
                    return detail_item
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"实习僧职位 {job_uuid} 详情接口失败，准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
                job_uuid=job_uuid,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
    return {}


def load_pcxz_endpoint(path: str, params: dict[str, Any] | None = None) -> Any:
    session = build_pcxz_session()
    response = session.get(f"{PCXZ_API_BASE}/{path}", params=params or {}, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("code") or 0) != 100:
        raise RuntimeError(f"校招专区接口返回异常: {path}")
    return payload.get("msg")


def save_featured_companies(companies: list[dict[str, Any]], module_name: str) -> dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}
    for item in companies:
        company_uuid = str(item.get("company_uuid") or item.get("uuid") or "").strip()
        company_name = str(item.get("company_name") or item.get("name") or "").strip()
        if not company_uuid or not company_name:
            continue
        city_text = " / ".join(str(part).strip() for part in (item.get("city") or []) if str(part).strip()) if isinstance(item.get("city"), list) else str(item.get("city") or "").strip()
        metadata = infer_featured_company_metadata(item, module_name)
        links = resolve_featured_company_links(company_name) if metadata["board_code"] == "featured_famous" else {"official_site_url": "", "career_site_url": ""}
        unique_hash = hashlib.sha256(f"shixiseng|featured_company|{module_name}|{company_uuid}".encode("utf-8")).hexdigest()[:32]
        extra_json = json.dumps(item, ensure_ascii=False)
        existing = conn.execute(
            "SELECT id, extra_json, board_code, company_type, group_name, official_site_url, career_site_url FROM featured_companies WHERE unique_hash = ?",
            (unique_hash,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO featured_companies (
                    board_code, company_type, group_name, source_code, company_uuid, company_name,
                    city_text, industry, scale_text, module_name, description_text, official_site_url,
                    career_site_url, extra_json, unique_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata["board_code"],
                    metadata["company_type"],
                    metadata["group_name"],
                    "shixiseng",
                    company_uuid,
                    company_name,
                    city_text,
                    str(item.get("industry") or "").strip(),
                    str(item.get("scale") or "").strip(),
                    module_name,
                    str(item.get("description") or "").strip(),
                    links["official_site_url"],
                    links["career_site_url"],
                    extra_json,
                    unique_hash,
                ),
            )
            stats["new"] += 1
        elif (
            str(existing["extra_json"] or "") != extra_json
            or str(existing["board_code"] or "") != metadata["board_code"]
            or str(existing["company_type"] or "") != metadata["company_type"]
            or str(existing["group_name"] or "") != metadata["group_name"]
            or (links["official_site_url"] and str(existing["official_site_url"] or "") != links["official_site_url"])
            or (links["career_site_url"] and str(existing["career_site_url"] or "") != links["career_site_url"])
        ):
            next_official_site_url = links["official_site_url"] or str(existing["official_site_url"] or "")
            next_career_site_url = links["career_site_url"] or str(existing["career_site_url"] or "")
            conn.execute(
                """
                UPDATE featured_companies
                SET board_code=?, company_type=?, group_name=?, company_name=?, city_text=?, industry=?, scale_text=?, module_name=?,
                    description_text=?, official_site_url=?, career_site_url=?, extra_json=?, last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    metadata["board_code"],
                    metadata["company_type"],
                    metadata["group_name"],
                    company_name,
                    city_text,
                    str(item.get("industry") or "").strip(),
                    str(item.get("scale") or "").strip(),
                    module_name,
                    str(item.get("description") or "").strip(),
                    next_official_site_url,
                    next_career_site_url,
                    extra_json,
                    existing["id"],
                ),
            )
            stats["updated"] += 1
        else:
            conn.execute("UPDATE featured_companies SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
            stats["unchanged"] += 1
    conn.commit()
    conn.close()
    return stats


def collect_campus_home_modules(
    *,
    detail_workers: int,
    detail_rate_per_second: float,
    source_options: dict[str, Any],
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    ensure_not_cancelled(should_stop_callback, progress_callback, query="校招首页", city_name="专区")
    hotintern_city = str(source_options.get("campus_hotintern_city") or "推荐")
    hotcompany_industry = str(source_options.get("campus_hotcompany_industry") or "推荐")
    emit_progress(progress_callback, f"开始抓取校招首页模块：热门推荐 city={hotintern_city}，名企 industry={hotcompany_industry}", query="校招首页", city_name="专区")

    hotintern_items = load_pcxz_endpoint("hotintern", {"city": hotintern_city}) or []
    internlist_groups = load_pcxz_endpoint("internlist") or {}
    hotcompany_items = load_pcxz_endpoint("hotcompany", {"industry": hotcompany_industry}) or []

    module_jobs: list[dict[str, Any]] = []
    seen_module_job_ids: set[str] = set()
    for item in list(hotintern_items) + list(internlist_groups.get("high_salary") or []) + list(internlist_groups.get("hot_intern") or []) + list(internlist_groups.get("latest_intern") or []):
        job_uuid = str(item.get("uuid") or "").strip()
        if job_uuid and job_uuid not in seen_module_job_ids:
            seen_module_job_ids.add(job_uuid)
            module_jobs.append(item)

    page_jobs = fetch_page_jobs_via_api(
        module_jobs,
        query="校招首页",
        city_name="专区",
        page_no=1,
        detail_workers=detail_workers,
        detail_rate_per_second=detail_rate_per_second,
        track="campus",
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    ) if module_jobs else []

    job_stats = save_to_db(page_jobs, source_code="shixiseng") if page_jobs else {"new": 0, "updated": 0, "unchanged": 0}
    company_stats = save_featured_companies(list(hotcompany_items), module_name="xiaozhao_hotcompany") if hotcompany_items else {"new": 0, "updated": 0, "unchanged": 0}

    emit_progress(
        progress_callback,
        f"校招首页模块抓取完成：职位 {len(page_jobs)} 条，名企 {len(hotcompany_items)} 家，新增职位 {job_stats['new']}，新增名企 {company_stats['new']}",
        query="校招首页",
        city_name="专区",
    )
    return {
        "job_items": len(page_jobs),
        "company_items": len(hotcompany_items),
        "job_new": job_stats["new"],
        "job_updated": job_stats["updated"],
        "company_new": company_stats["new"],
        "company_updated": company_stats["updated"],
    }


def extract_list_items(page: Any) -> tuple[list[dict[str, Any]], int]:
    data = extract_nuxt_data(page)
    sections = data.get("data") or []
    if not sections or not isinstance(sections[0], dict):
        return [], 0
    interns = sections[0].get("interns") or {}
    items = interns.get("data") or []
    total = int(interns.get("total") or 0)
    normalized_items = [item for item in items if isinstance(item, dict) and item.get("uuid")]
    return normalized_items, total


def extract_detail_payload(page: Any) -> dict[str, Any]:
    data = extract_nuxt_data(page)
    sections = data.get("data") or []
    if not sections or not isinstance(sections[0], dict):
        return {}
    msg = sections[0].get("msg") or {}
    return msg if isinstance(msg, dict) else {}


def build_salary_text(min_salary: Any, max_salary: Any, chance: str) -> str:
    chance_text = str(chance or "").strip()
    min_text = str(min_salary or "").strip()
    max_text = str(max_salary or "").strip()
    if min_text and max_text:
        if min_text == max_text:
            return f"{min_text}元/天"
        return f"{min_text}-{max_text}元/天"
    if chance_text:
        return chance_text
    return ""


def build_stage_text(detail_item: dict[str, Any]) -> str:
    values = []
    stock_status = str(detail_item.get("stock_status") or "").strip()
    company_status = str(detail_item.get("company_status") or "").strip()
    xiaozhao_type = detail_item.get("xiaozhao_type")
    if stock_status and stock_status not in {"normal", "未知"}:
        values.append(stock_status)
    if company_status and company_status not in {"normal", "未知"}:
        values.append(company_status)
    if str(xiaozhao_type) not in {"", "0", "None"}:
        values.append(f"校招类型{xiaozhao_type}")
    return " / ".join(values)


def build_experience_text(day: Any, month: Any, chance: str) -> str:
    parts: list[str] = []
    if str(day or "").strip():
        parts.append(f"{day}天/周")
    if str(month or "").strip():
        parts.append(f"{month}个月")
    if str(chance or "").strip() and chance != "面议":
        parts.append(str(chance).strip())
    return " · ".join(parts)


def build_district_text(address: str) -> str:
    text = str(address or "").strip()
    if not text:
        return ""
    parts = [item.strip() for item in text.split("/") if item.strip()]
    if len(parts) >= 3:
        return parts[2]
    if len(parts) >= 2:
        return parts[-1]
    return text[:60]


def build_description(detail_item: dict[str, Any], company_tags: list[str]) -> str:
    description_parts: list[str] = []
    info = str(detail_item.get("info") or "").strip()
    if info:
        description_parts.append(info)
    requirement = str(detail_item.get("job_requirements") or "").strip()
    if requirement:
        description_parts.append("岗位要求：\n" + requirement)
    other_info = str(detail_item.get("job_other_info") or "").strip()
    if other_info:
        description_parts.append("补充信息：\n" + other_info)
    if company_tags:
        description_parts.append("公司亮点：" + "、".join(company_tags))

    meta_parts: list[str] = []
    refresh = str(detail_item.get("refresh") or "").strip()
    company_city = str(detail_item.get("company_city") or "").strip()
    address = str(detail_item.get("address") or "").strip()
    if refresh:
        meta_parts.append(f"刷新时间：{refresh}")
    if company_city:
        meta_parts.append(f"公司城市：{company_city}")
    if address:
        meta_parts.append(f"工作地址：{address}")
    if meta_parts:
        description_parts.append("\n".join(meta_parts))

    return "\n\n".join(item for item in description_parts if item).strip()


def build_job_type(detail_item: dict[str, Any], job_tags: list[str]) -> str:
    values: list[str] = []
    for item in [detail_item.get("job"), *job_tags, *(detail_item.get("skills") or [])]:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return " / ".join(values)


def retry_delay(attempt: int) -> float:
    return RETRY_BACKOFF_SECONDS * attempt


def is_campus_like_job(detail_item: dict[str, Any], normalized_job: dict[str, Any]) -> bool:
    xiaozhao_type = detail_item.get("xiaozhao_type")
    if str(xiaozhao_type) not in {"", "0", "None"}:
        return True
    joined_text = " ".join(
        [
            str(normalized_job.get("title") or ""),
            str(normalized_job.get("job_type") or ""),
            str(normalized_job.get("description_text") or ""),
            str(detail_item.get("chance") or ""),
        ]
    )
    return bool(re.search(r"校招|应届|毕业生|秋招|春招|管培生|202\d届", joined_text, re.I))


def should_keep_job(track: str, detail_item: dict[str, Any], normalized_job: dict[str, Any]) -> bool:
    if track == "all":
        return True
    is_campus = is_campus_like_job(detail_item, normalized_job)
    if track == "campus":
        return is_campus
    if track == "intern":
        return not is_campus
    return True


def load_search_items_with_retry(
    page: Any,
    query: str,
    city_name: str,
    page_no: int,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> tuple[list[dict[str, Any]], int]:
    last_total = 0
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        page.get(build_search_url(query, city_name, page_no))
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
        list_items, total_items = extract_list_items(page)
        if list_items:
            return list_items, total_items
        last_total = total_items
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"实习僧 {query} - {city_name} 第 {page_no} 页解析失败，准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
    return [], last_total


def load_detail_with_retry(
    page: Any,
    job_uuid: str,
    query: str,
    city_name: str,
    page_no: int,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    detail_url = build_detail_url(job_uuid)
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        page.get(detail_url)
        safe_sleep(DETAIL_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        detail_item = extract_detail_payload(page)
        if detail_item.get("iname") or detail_item.get("job"):
            detail_item.setdefault("uuid", job_uuid)
            return detail_item
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"实习僧职位 {job_uuid} 详情解析失败，准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
                job_uuid=job_uuid,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
    return {}


def load_detail_html_with_retry(
    job_uuid: str,
    *,
    cookie_header: str,
    query: str,
    city_name: str,
    page_no: int,
    rate_limiter: DetailRateLimiter,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> str:
    detail_url = build_detail_url(job_uuid)
    referer = build_search_url(query, city_name, page_no)
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        rate_limiter.wait(should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
        session = build_requests_session(cookie_header, referer)
        response = session.get(detail_url, timeout=25)
        if response.status_code == 200 and "__NUXT__=" in response.text:
            return response.text
        if attempt < MAX_RETRIES:
            emit_progress(
                progress_callback,
                f"实习僧职位 {job_uuid} requests 详情失败（{response.status_code}），准备第 {attempt + 1} 次重试",
                query=query,
                city_name=city_name,
                page=page_no,
                job_uuid=job_uuid,
            )
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no, job_uuid=job_uuid)
    return ""


def parse_detail_html(html: str, job_uuid: str) -> dict[str, Any]:
    script = extract_nuxt_script(html)
    if not script:
        return {}
    detail_item = {
        "uuid": job_uuid,
        "iname": extract_js_string(script, "iname"),
        "job": extract_js_string(script, "job"),
        "city": extract_js_string(script, "city"),
        "cname": extract_js_string(script, "cname"),
        "company_city": extract_js_string(script, "company_city"),
        "company_status": extract_js_string(script, "company_status"),
        "stock_status": extract_js_string(script, "stock_status"),
        "degree": extract_js_string(script, "degree"),
        "salary_desc": extract_js_string(script, "salary_desc"),
        "chance": extract_js_string(script, "chance"),
        "scale": extract_js_string(script, "scale"),
        "address": extract_js_string(script, "address"),
        "info": extract_js_string(script, "info"),
        "job_requirements": extract_js_string(script, "job_requirements"),
        "job_other_info": extract_js_string(script, "job_other_info"),
        "apply_link": extract_js_string(script, "apply_link"),
        "refresh": extract_js_string(script, "refresh"),
        "source": extract_js_string(script, "source"),
        "xiaozhao_type": extract_js_number(script, "xiaozhao_type") or 0,
        "day": extract_js_number(script, "day") or "",
        "month": extract_js_number(script, "month") or "",
        "minsal": extract_js_string(script, "minsal") or (extract_js_number(script, "minsal") or ""),
        "maxsal": extract_js_string(script, "maxsal") or (extract_js_number(script, "maxsal") or ""),
        "attraction": extract_js_array(script, "attraction"),
        "skills": extract_js_array(script, "skills"),
    }
    return detail_item


def fetch_detail_job_via_requests(
    list_item: dict[str, Any],
    *,
    cookie_header: str,
    query: str,
    city_name: str,
    page_no: int,
    rate_limiter: DetailRateLimiter,
    track: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any] | None:
    job_uuid = str(list_item.get("uuid") or "").strip()
    if not job_uuid:
        return None
    html = load_detail_html_with_retry(
        job_uuid,
        cookie_header=cookie_header,
        query=query,
        city_name=city_name,
        page_no=page_no,
        rate_limiter=rate_limiter,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    if not html:
        return None
    detail_item = parse_detail_html(html, job_uuid)
    if not detail_item:
        return None
    job = normalize_job_item(list_item, detail_item)
    if not job.get("title") or not job.get("company_name"):
        return None
    if not should_keep_job(track, detail_item, job):
        return None
    return job


def fetch_detail_job_via_api(
    list_item: dict[str, Any],
    *,
    query: str,
    city_name: str,
    page_no: int,
    rate_limiter: DetailRateLimiter,
    track: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any] | None:
    job_uuid = str(list_item.get("uuid") or "").strip()
    if not job_uuid:
        return None
    detail_item = load_detail_api_with_retry(
        job_uuid,
        query=query,
        city_name=city_name,
        page_no=page_no,
        rate_limiter=rate_limiter,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    if not detail_item:
        return None
    job = normalize_job_item(list_item, detail_item)
    if not job.get("title") or not job.get("company_name"):
        return None
    if not should_keep_job(track, detail_item, job):
        return None
    return job


def fetch_page_jobs_via_requests(
    list_items: list[dict[str, Any]],
    *,
    cookie_header: str,
    query: str,
    city_name: str,
    page_no: int,
    detail_workers: int,
    detail_rate_per_second: float,
    track: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    rate_limiter = DetailRateLimiter(detail_rate_per_second)
    with ThreadPoolExecutor(max_workers=detail_workers, thread_name_prefix="sxs-detail") as executor:
        futures = [
            executor.submit(
                fetch_detail_job_via_requests,
                list_item,
                cookie_header=cookie_header,
                query=query,
                city_name=city_name,
                page_no=page_no,
                rate_limiter=rate_limiter,
                track=track,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            for list_item in list_items
        ]
        for future in as_completed(futures):
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
            job = future.result()
            if job is not None:
                jobs.append(job)
    return jobs


def fetch_page_jobs_via_api(
    list_items: list[dict[str, Any]],
    *,
    query: str,
    city_name: str,
    page_no: int,
    detail_workers: int,
    detail_rate_per_second: float,
    track: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    rate_limiter = DetailRateLimiter(detail_rate_per_second)
    with ThreadPoolExecutor(max_workers=detail_workers, thread_name_prefix="sxs-api-detail") as executor:
        futures = [
            executor.submit(
                fetch_detail_job_via_api,
                list_item,
                query=query,
                city_name=city_name,
                page_no=page_no,
                rate_limiter=rate_limiter,
                track=track,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            for list_item in list_items
        ]
        for future in as_completed(futures):
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
            job = future.result()
            if job is not None:
                jobs.append(job)
    return jobs


def normalize_job_item(list_item: dict[str, Any], detail_item: dict[str, Any]) -> dict[str, Any]:
    job_uuid = str(detail_item.get("uuid") or list_item.get("uuid") or "").strip()
    title = str(detail_item.get("iname") or detail_item.get("job") or "").replace(" ", "").strip()
    company_name = str(detail_item.get("cname") or list_item.get("cname") or "").replace(" ", "").strip()
    city_name = str(detail_item.get("city") or list_item.get("city") or "").replace(" ", "").strip()
    job_tags = [str(item).strip() for item in (detail_item.get("attraction") or list_item.get("i_tags") or []) if str(item).strip()]
    company_tags = [str(item).strip() for item in (list_item.get("c_tags") or []) if str(item).strip()]

    return {
        "source_job_id": job_uuid,
        "title": title,
        "company_name": company_name,
        "city_name": city_name,
        "district_name": build_district_text(str(detail_item.get("address") or "")),
        "salary_text": str(detail_item.get("salary_desc") or "").strip() or build_salary_text(detail_item.get("minsal"), detail_item.get("maxsal"), str(detail_item.get("chance") or "")),
        "degree_text": str(detail_item.get("degree") or list_item.get("degree") or "").strip(),
        "experience_text": build_experience_text(detail_item.get("day"), detail_item.get("month"), str(detail_item.get("chance") or "")),
        "brand_scale": str(detail_item.get("scale") or "").strip(),
        "brand_stage": build_stage_text(detail_item),
        "job_type": build_job_type(detail_item, job_tags),
        "source_url": build_detail_url(job_uuid),
        "official_apply_url": str(detail_item.get("apply_link") or "").strip() or build_detail_url(job_uuid),
        "description_text": build_description(detail_item, company_tags),
        "source_code": "shixiseng",
        "status": "active",
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "shixiseng") -> dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for item in jobs:
        job_id = str(item.get("source_job_id") or "").strip()
        title = str(item.get("title") or "").strip()
        company_name = str(item.get("company_name") or "").strip()
        city_name = str(item.get("city_name") or "").strip()
        if not job_id or not title or not company_name:
            continue

        unique_hash = hashlib.sha256(f"{source_code}|{job_id}".encode("utf-8")).hexdigest()[:32]
        content_text = "|".join(
            [
                title,
                str(item.get("salary_text") or ""),
                str(item.get("degree_text") or ""),
                str(item.get("experience_text") or ""),
                str(item.get("description_text") or ""),
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
                    str(item.get("district_name") or ""),
                    str(item.get("salary_text") or ""),
                    str(item.get("degree_text") or ""),
                    str(item.get("experience_text") or ""),
                    str(item.get("brand_scale") or ""),
                    str(item.get("brand_stage") or ""),
                    str(item.get("job_type") or ""),
                    str(item.get("source_url") or ""),
                    str(item.get("official_apply_url") or ""),
                    str(item.get("description_text") or ""),
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
                    experience_text=?, job_type=?, source_url=?, official_apply_url=?, description_text=?,
                    content_hash=?, last_seen_at=CURRENT_TIMESTAMP, status='active'
                WHERE id=?
                """,
                (
                    title,
                    company_name,
                    city_name,
                    str(item.get("district_name") or ""),
                    str(item.get("salary_text") or ""),
                    str(item.get("degree_text") or ""),
                    str(item.get("experience_text") or ""),
                    str(item.get("job_type") or ""),
                    str(item.get("source_url") or ""),
                    str(item.get("official_apply_url") or ""),
                    str(item.get("description_text") or ""),
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
    del output_dir
    configure_stdio()
    ensure_db()

    if ChromiumPage is None:
        raise RuntimeError("未安装 DrissionPage，无法执行实习僧浏览器采集")

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    normalized_source_options = normalize_source_options(source_options)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 30))
    detail_workers = int(normalized_source_options["detail_workers"])
    detail_rate_per_second = float(normalized_source_options["detail_rate_per_second"])
    track = str(normalized_source_options["track"])
    include_campus_home_modules = bool(normalized_source_options["include_campus_home_modules"])
    runtime_mode_normalized = runtime_mode.strip().lower()
    detail_mode = "api" if runtime_mode_normalized in {"api", "requests_only", "hybrid_requests", "hybrid", "requests_html"} else "browser"

    total_fetched = 0
    total_new = 0
    total_updated = 0
    campus_home_result: dict[str, Any] = {}
    shixiseng_trace: list[dict[str, Any]] = []
    page = None
    seen_page_signatures: set[tuple[str, str, str]] = set()
    seen_job_ids: set[str] = set()

    try:
        emit_progress(progress_callback, f"实习僧采集启动，详情模式 {detail_mode}，并发 {detail_workers}，限速 {detail_rate_per_second:.2f} req/s，筛选 {track}")
        if detail_mode == "browser":
            options = build_browser_options()
            page = ChromiumPage(options)
        if detail_mode == "api" and track == "campus" and include_campus_home_modules:
            campus_home_result = collect_campus_home_modules(
                detail_workers=detail_workers,
                detail_rate_per_second=detail_rate_per_second,
                source_options=normalized_source_options,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            total_fetched += int(campus_home_result.get("job_items") or 0)
            total_new += int(campus_home_result.get("job_new") or 0)
            total_updated += int(campus_home_result.get("job_updated") or 0)
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_fetched = 0
                city_new = 0
                city_updated = 0
                pages_completed = 0
                last_total_items = 0
                last_estimated_total_pages = 0
                stop_reason = "target_pages_reached"
                for page_no in range(1, target_pages + 1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                    emit_progress(progress_callback, f"实习僧开始抓取 {query} - {city_name} 第 {page_no} 页", query=query, city_name=city_name, page=page_no)
                    if detail_mode == "api":
                        list_items, total_items, estimated_total_pages = load_search_api_page_with_retry(query, city_name, page_no, track, should_stop_callback, progress_callback)
                    else:
                        list_items, total_items = load_search_items_with_retry(page, query, city_name, page_no, should_stop_callback, progress_callback)
                        site_page_size = max(1, len(list_items))
                        estimated_total_pages = max(1, math.ceil((total_items or site_page_size) / site_page_size))
                    last_total_items = int(total_items or 0)
                    last_estimated_total_pages = int(estimated_total_pages or 0)
                    if not list_items:
                        stop_reason = "empty"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 第 {page_no} 页未解析到职位", query=query, city_name=city_name, page=page_no)
                        break

                    page_signature = (query, city_name, "|".join(str(item.get("uuid") or "") for item in list_items[:5]))
                    if page_signature in seen_page_signatures:
                        stop_reason = "duplicate_page"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 第 {page_no} 页出现重复分页签名，提前结束", query=query, city_name=city_name, page=page_no)
                        break
                    seen_page_signatures.add(page_signature)
                    all_seen_before_page = all(str(item.get("uuid") or "") in seen_job_ids for item in list_items)

                    if detail_mode == "api":
                        page_jobs = fetch_page_jobs_via_api(
                            list_items[:target_page_size],
                            query=query,
                            city_name=city_name,
                            page_no=page_no,
                            detail_workers=detail_workers,
                            detail_rate_per_second=detail_rate_per_second,
                            track=track,
                            should_stop_callback=should_stop_callback,
                            progress_callback=progress_callback,
                        )
                    elif detail_mode == "requests":
                        cookie_header = build_cookie_header(page)
                        page_jobs = fetch_page_jobs_via_requests(
                            list_items[:target_page_size],
                            cookie_header=cookie_header,
                            query=query,
                            city_name=city_name,
                            page_no=page_no,
                            detail_workers=detail_workers,
                            detail_rate_per_second=detail_rate_per_second,
                            track=track,
                            should_stop_callback=should_stop_callback,
                            progress_callback=progress_callback,
                        )
                    else:
                        page_jobs = []
                        for list_item in list_items[:target_page_size]:
                            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                            job_uuid = str(list_item.get("uuid") or "").strip()
                            if not job_uuid:
                                continue
                            detail_item = load_detail_with_retry(page, job_uuid, query, city_name, page_no, should_stop_callback, progress_callback)
                            if not detail_item:
                                continue
                            job = normalize_job_item(list_item, detail_item)
                            if not job.get("title") or not job.get("company_name"):
                                continue
                            if should_keep_job(track, detail_item, job):
                                page_jobs.append(job)

                    if not page_jobs:
                        stop_reason = "empty_normalized"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 第 {page_no} 页没有命中筛选后的职位", query=query, city_name=city_name, page=page_no)
                        break

                    stats = save_to_db(page_jobs, source_code="shixiseng")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    city_fetched += len(page_jobs)
                    city_new += stats["new"]
                    city_updated += stats["updated"]
                    pages_completed = page_no
                    seen_job_ids.update(str(item.get("source_job_id") or "") for item in page_jobs if str(item.get("source_job_id") or ""))
                    emit_progress(
                        progress_callback,
                        f"实习僧 {query} - {city_name} 第 {page_no} 页完成：抓取 {len(page_jobs)} / 总数 {total_items}，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                    )
                    if page_no >= estimated_total_pages:
                        stop_reason = "end_page"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 已到最后一页，共估算 {estimated_total_pages} 页", query=query, city_name=city_name, page=page_no)
                        break
                    if city_fetched >= total_items > 0:
                        stop_reason = "covered_total"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 已覆盖该检索结果总数 {total_items}", query=query, city_name=city_name, page=page_no)
                        break
                    if all_seen_before_page:
                        stop_reason = "all_seen"
                        emit_progress(progress_callback, f"实习僧 {query} - {city_name} 第 {page_no} 页全部为已处理职位，提前结束", query=query, city_name=city_name, page=page_no)
                        break

                shixiseng_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "total_items": last_total_items,
                        "estimated_total_pages": last_estimated_total_pages,
                        "fetched_count": city_fetched,
                        "new_count": city_new,
                        "updated_count": city_updated,
                        "detail_mode": detail_mode,
                        "track": track,
                    }
                )

        emit_progress(progress_callback, f"实习僧采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条")
        return {
            "total_fetched": total_fetched,
            "new_to_db": total_new,
            "updated": total_updated,
            "queries": len(normalized_queries),
            "cities": len(normalized_cities),
            "runtime_mode": runtime_mode,
            "detail_mode": detail_mode,
            "track": track,
            "campus_home": campus_home_result,
            "shixiseng_summary": {
                "trace_count": len(shixiseng_trace),
                "campus_home_jobs": int(campus_home_result.get("job_items") or 0),
                "campus_home_companies": int(campus_home_result.get("company_items") or 0),
                "detail_mode": detail_mode,
                "track": track,
            },
            "shixiseng_trace": shixiseng_trace,
        }
    finally:
        try:
            if page is not None:
                page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    result = run_incremental_update()
    print(result)