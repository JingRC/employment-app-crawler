"""英才网联系列统一爬虫 — requests_html 策略。

通过 YINGCAI_SITE_CONFIG 统一配置医药英才网、建筑英才网、化工英才网
及其下属细分子站，消除 4 个重复爬虫文件的代码冗余。
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urljoin

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

DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "detail_html",
    "request_timeout_seconds": 25.0,
    "sleep_seconds": 0.0,
}

YINGCAI_SITE_CONFIG: dict[str, dict[str, Any]] = {
    "healthr": {
        "base_url": "https://www.healthr.com",
        "category_id": "14",
        "function_code": None,
        "title_regex_suffix": "医药英才网",
        "site_label": "healthr",
        "default_queries": ["医生", "销售", "药剂师", "QC"],
        "default_cities": ["全国", "青岛", "济南"],
        "supports_keyword_search": True,
    },
    "healthr_doctor": {
        "base_url": "https://www.healthr.com",
        "category_id": "14",
        "function_code": "fn141100",
        "title_regex_suffix": "医药英才网",
        "site_label": "healthr_doctor",
        "default_queries": ["医生", "护士", "医师", "内科"],
        "default_cities": ["全国", "青岛", "济南"],
        "supports_keyword_search": False,
    },
    "buildhr": {
        "base_url": "https://www.buildhr.com",
        "category_id": "11",
        "function_code": None,
        "title_regex_suffix": "建筑英才网",
        "site_label": "buildhr",
        "default_queries": ["建筑师", "项目经理", "造价工程师", "施工员"],
        "default_cities": ["全国", "青岛", "济南"],
        "supports_keyword_search": True,
    },
    "chenhr": {
        "base_url": "https://www.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "chenhr",
        "default_queries": ["研发工程师", "工艺工程师", "销售经理", "生产经理"],
        "default_cities": ["全国", "青岛", "济南"],
        "supports_keyword_search": True,
    },
    "jxhg_chenhr": {
        "base_url": "https://jxhg.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "jxhg_chenhr",
        "default_queries": ["工程师", "技术员", "操作工", "研发"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "mhg_chenhr": {
        "base_url": "https://mhg.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "mhg_chenhr",
        "default_queries": ["工程师", "技术员", "操作工"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "sysh_chenhr": {
        "base_url": "https://sysh.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "sysh_chenhr",
        "default_queries": ["工程师", "技术员", "安全工程师"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "newenergy_chenhr": {
        "base_url": "https://xny.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "newenergy_chenhr",
        "default_queries": ["工程师", "技术员", "研发", "项目经理"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "sales_chenhr": {
        "base_url": "https://sales.chenhr.com",
        "category_id": "29",
        "function_code": None,
        "title_regex_suffix": "化工英才网",
        "site_label": "sales_chenhr",
        "default_queries": ["销售经理", "销售工程师", "客户经理"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "doctor_healthr": {
        "base_url": "https://doctor.healthr.com",
        "category_id": "14",
        "function_code": None,
        "title_regex_suffix": "医药英才网",
        "site_label": "doctor_healthr",
        "default_queries": ["医生", "医师", "主任医师", "主治医师"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "pha_healthr": {
        "base_url": "https://pha.healthr.com",
        "category_id": "14",
        "function_code": None,
        "title_regex_suffix": "医药英才网",
        "site_label": "pha_healthr",
        "default_queries": ["药师", "营业员", "店长", "药剂师"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "env_buildhr": {
        "base_url": "https://env.buildhr.com",
        "category_id": "11",
        "function_code": None,
        "title_regex_suffix": "建筑英才网",
        "site_label": "env_buildhr",
        "default_queries": ["环评工程师", "环保工程师", "环境检测", "环境工程"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
    "construct_buildhr": {
        "base_url": "https://construct.buildhr.com",
        "category_id": "11",
        "function_code": None,
        "title_regex_suffix": "建筑英才网",
        "site_label": "construct_buildhr",
        "default_queries": ["施工员", "项目经理", "安全员", "技术员"],
        "default_cities": ["全国"],
        "supports_keyword_search": True,
    },
}

CITY_CODE_CACHE: dict[str, dict[str, str]] = {}


def _get_site_config(source_code: str) -> dict[str, Any]:
    config = YINGCAI_SITE_CONFIG.get(source_code)
    if config is None:
        raise RuntimeError(f"未知的英才网联来源: {source_code}")
    return config


def _make_list_url(config: dict[str, Any]) -> str:
    return f"{config['base_url']}/so/"


def _make_national_page_url(config: dict[str, Any]) -> str:
    cid = config["category_id"]
    fc = config.get("function_code")
    base = config["base_url"]
    if fc:
        return f"{base}/so/{cid}-{fc}-sm1-p{{page_no}}.html"
    return f"{base}/so/{cid}-sm3-p{{page_no}}.html"


def _make_city_page_url(config: dict[str, Any]) -> str:
    cid = config["category_id"]
    fc = config.get("function_code")
    base = config["base_url"]
    if fc:
        return f"{base}/so/{cid}-{{city_code}}-{fc}-sm1-p{{page_no}}.html"
    return f"{base}/so/{cid}-{{city_code}}-sm1-p{{page_no}}.html"


def _make_keyword_page_url(config: dict[str, Any]) -> str:
    return f"{config['base_url']}/so/kw{{encoded_query}}-p{{page_no}}.html"


def _make_page_regex(config: dict[str, Any]) -> str:
    cid = config["category_id"]
    fc = config.get("function_code")
    if fc:
        return rf"/so/{cid}-(?:\d+-)?{fc}-sm\d+-p(\d+)\.html"
    return rf"/so/(?:{cid}-)?(?:\d+-)?sm\d+-p(\d+)\.html"


def _make_title_regex(config: dict[str, Any]) -> str:
    suffix = re.escape(config["title_regex_suffix"])
    return rf"(.+?)招聘(.+?)-{suffix}"


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
        emit_progress(progress_callback, "收到取消信号，准备停止采集", **context)
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
    text = " ".join(str(value or "").replace("\xa0", " ").split()).strip()
    return re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)


def normalize_queries(config: dict[str, Any], queries: list[str] | None) -> list[str]:
    defaults = list(config.get("default_queries") or [])
    values = [clean_text(item) for item in (queries or defaults) if clean_text(item)]
    return values or list(defaults)


def normalize_cities(config: dict[str, Any], cities: list[str] | None) -> list[str]:
    defaults = list(config.get("default_cities") or [])
    values: list[str] = []
    for item in cities or defaults:
        value = clean_text(item)
        if value and value not in values:
            values.append(value)
    return values or list(defaults)


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


def build_session(list_url: str) -> requests.Session:
    if requests is None:
        raise RuntimeError("未安装 requests，无法执行 英才网联 采集")
    session = requests.Session()
    session.headers.update(
        {
            "Referer": list_url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        }
    )
    return session


def fetch_text(session: requests.Session, url: str, timeout_seconds: float) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
            declared_encoding = clean_text(response.encoding)
            apparent_encoding = clean_text(getattr(response, "apparent_encoding", ""))
            if declared_encoding and declared_encoding.lower() not in {"iso-8859-1", "latin-1", "ascii"}:
                response.encoding = declared_encoding
            elif apparent_encoding:
                response.encoding = apparent_encoding
            else:
                response.encoding = "utf-8"
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is None:
        raise RuntimeError(f"请求失败：{url}")
    raise last_error


def fetch_city_code_map(session: requests.Session, config: dict[str, Any], timeout_seconds: float) -> dict[str, str]:
    global CITY_CODE_CACHE
    base_url = config["base_url"]
    if base_url in CITY_CODE_CACHE and CITY_CODE_CACHE[base_url]:
        return dict(CITY_CODE_CACHE[base_url])
    list_url = _make_list_url(config)
    html_text = fetch_text(session, list_url, timeout_seconds)
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析城市映射")
    soup = BeautifulSoup(html_text, "html.parser")
    mapping: dict[str, str] = {"全国": ""}
    for link in soup.select("a[href*='/so/']"):
        href = clean_text(link.get("href"))
        text = clean_text(link.get_text(" ", strip=True))
        match = re.search(r"/so/(\d+)(?:\.html|/)?(?:$|[?#])", href)
        if match and text and len(text) <= 8:
            mapping[text] = match.group(1)
    CITY_CODE_CACHE[base_url] = dict(mapping)
    return dict(mapping)


def resolve_city_code(city_name: str, city_code_map: dict[str, str]) -> tuple[str, bool]:
    normalized = clean_text(city_name)
    if not normalized or normalized == "全国":
        return "", False
    if normalized in city_code_map:
        return clean_text(city_code_map[normalized]), False
    if normalized.endswith("市") and normalized[:-1] in city_code_map:
        return clean_text(city_code_map[normalized[:-1]]), False
    if normalized.isdigit():
        return normalized, False
    return "", True


def build_list_url(config: dict[str, Any], city_code: str, page_no: int) -> str:
    normalized_page = max(1, int(page_no))
    if city_code:
        return _make_city_page_url(config).format(city_code=city_code, page_no=normalized_page)
    return _make_national_page_url(config).format(page_no=normalized_page)


def encode_keyword_query(query: str) -> str:
    normalized = clean_text(query)
    if not normalized:
        return ""
    return quote(normalized.encode("gbk"))


def build_query_list_url(config: dict[str, Any], query: str, city_code: str, page_no: int) -> str:
    if not config.get("supports_keyword_search", True):
        return build_list_url(config, city_code=city_code, page_no=page_no)
    normalized_page = max(1, int(page_no))
    if not city_code:
        encoded_query = encode_keyword_query(query)
        if encoded_query:
            return _make_keyword_page_url(config).format(encoded_query=encoded_query, page_no=normalized_page)
    return build_list_url(config, city_code=city_code, page_no=normalized_page)


def normalize_city_name(value: Any) -> str:
    text = clean_text(value)
    match = re.search(r"([一-鿿]{2,8}市)", text)
    if match:
        return clean_text(match.group(1))
    return text


def normalize_district_name(value: Any) -> str:
    text = clean_text(value)
    match = re.search(r"([一-鿿]{2,8}(?:区|县))", text)
    if match:
        return clean_text(match.group(1))
    return ""


def city_matches(target_city: str, *texts: Any) -> bool:
    normalized = clean_text(target_city)
    if not normalized or normalized == "全国":
        return True
    candidates = [clean_text(text) for text in texts if clean_text(text)]
    if not candidates:
        return False
    plain = normalized[:-1] if normalized.endswith("市") else normalized
    return any(normalized in text or plain in text for text in candidates)


def parse_list_page(html_text: str, config: dict[str, Any], page_no: int) -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析列表页")
    base_url = config["base_url"]
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[dict[str, Any]] = []
    for node in soup.select(".result_list_one"):
        title_link = node.select_one(".result_list_one_job_name a[href*='/job/']")
        company_link = node.select_one(".result_list_one_company a[href*='/company/']")
        if title_link is None or company_link is None:
            continue
        title = clean_text(title_link.get_text(" ", strip=True))
        detail_url = urljoin(base_url, clean_text(title_link.get("href")))
        company_name = clean_text(company_link.get_text(" ", strip=True))
        salary_text = clean_text(node.select_one(".result_list_one_salary").get_text(" ", strip=True) if node.select_one(".result_list_one_salary") else "")
        area_text = clean_text(node.select_one(".result_list_one_area").get_text(" ", strip=True) if node.select_one(".result_list_one_area") else "")
        company_meta = clean_text(node.select_one(".result_list_one_shuxin").get_text(" ", strip=True) if node.select_one(".result_list_one_shuxin") else "")
        published_at = clean_text(node.select_one(".result_list_one_time").get_text(" ", strip=True) if node.select_one(".result_list_one_time") else "")
        area_parts = [clean_text(part) for part in area_text.split("·") if clean_text(part)]
        location_text = area_parts[0] if area_parts else ""
        degree_text = area_parts[1] if len(area_parts) > 1 else ""
        headcount_text = area_parts[2] if len(area_parts) > 2 else ""
        meta_parts = [clean_text(part) for part in company_meta.split("·") if clean_text(part)]
        brand_stage = meta_parts[0] if meta_parts else ""
        brand_scale = meta_parts[1] if len(meta_parts) > 1 else ""
        items.append(
            {
                "title": title,
                "detail_url": detail_url,
                "company_name": company_name,
                "salary_text": salary_text,
                "location_text": location_text,
                "degree_text": degree_text,
                "headcount_text": headcount_text,
                "brand_stage": brand_stage,
                "brand_scale": brand_scale,
                "published_at": published_at,
                "summary_text": " ".join(filter(None, [title, company_name, location_text, degree_text, company_meta])),
                "city_name": normalize_city_name(location_text),
                "district_name": normalize_district_name(location_text),
            }
        )
    page_regex = _make_page_regex(config)
    page_numbers = [int(value) for value in re.findall(page_regex, html_text)]
    total_pages = max(page_numbers) if page_numbers else page_no
    return {
        "items": items,
        "page_no": page_no,
        "page_size": len(items),
        "total_pages": total_pages,
        "total_count": total_pages * len(items) if items and total_pages else len(items),
    }


def fetch_list_page(session: requests.Session, config: dict[str, Any], query: str, city_code: str, page_no: int, timeout_seconds: float) -> dict[str, Any]:
    url = build_query_list_url(config, query=query, city_code=city_code, page_no=page_no)
    html_text = fetch_text(session, url, timeout_seconds)
    return parse_list_page(html_text, config, page_no)


def _extract_block(lines: list[str], start_label: str, end_labels: list[str]) -> str:
    if start_label not in lines:
        return ""
    start_index = lines.index(start_label) + 1
    end_index = len(lines)
    for label in end_labels:
        if label in lines[start_index:]:
            end_index = min(end_index, start_index + lines[start_index:].index(label))
    return clean_text("\n".join(lines[start_index:end_index]))


def parse_detail_html(html_text: str, config: dict[str, Any], detail_url: str = "") -> dict[str, Any]:
    if BeautifulSoup is None:
        raise RuntimeError("未安装 beautifulsoup4，无法解析详情页")
    title_regex = _make_title_regex(config)
    soup = BeautifulSoup(html_text, "html.parser")
    title_tag = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    title_match = re.search(title_regex, title_tag)
    company_name = clean_text(title_match.group(1)) if title_match else ""
    title = clean_text(title_match.group(2)) if title_match else ""
    texts = [clean_text(text) for text in soup.get_text("\n", strip=True).splitlines() if clean_text(text)]

    def find_after(label: str) -> str:
        if label not in texts:
            return ""
        index = texts.index(label)
        if index + 1 >= len(texts):
            return ""
        return clean_text(texts[index + 1])

    salary_text = ""
    for line in texts:
        if re.search(r"\d+\s*[~～-]\s*\d+\s*元/月", line):
            salary_text = clean_text(re.search(r"\d+\s*[~～-]\s*\d+\s*元/月", line).group(0))
            break
    if not salary_text:
        salary_match = re.search(r"(面议|\d+\s*[~～-]\s*\d+\s*元/月)", title_tag)
        salary_text = clean_text(salary_match.group(1)) if salary_match else ""

    requirement_text = _extract_block(texts, "岗位职责", ["公司介绍", "英才网联安全提示", "该公司技术型人才招聘职位"])
    company_intro = _extract_block(texts, "公司介绍", ["收起", "展开", "英才网联安全提示", "公司基本信息"])
    company_basic_index = texts.index("公司基本信息") if "公司基本信息" in texts else -1
    brand_stage = ""
    brand_scale = ""
    industry_text = ""
    if company_basic_index != -1:
        tail = texts[company_basic_index + 1 :]
        if not company_name and tail:
            company_name = clean_text(tail[0])
        if len(tail) > 1:
            brand_stage = clean_text(tail[1])
        if len(tail) > 2:
            brand_scale = clean_text(tail[2])
        if len(tail) > 3:
            industry_text = clean_text(tail[3])

    location_text = find_after("工作地点：")
    hr_name = ""
    if "HR信息" in texts:
        hr_index = texts.index("HR信息")
        if hr_index + 1 < len(texts):
            hr_name = clean_text(texts[hr_index + 1])

    return {
        "title": title,
        "company_name": company_name,
        "salary_text": salary_text,
        "degree_text": find_after("学历要求："),
        "experience_text": find_after("工作经验："),
        "job_type": find_after("职位性质："),
        "location_text": location_text,
        "description_text": requirement_text,
        "company_intro": company_intro,
        "brand_stage": brand_stage,
        "brand_scale": brand_scale,
        "industry_text": industry_text,
        "city_name": normalize_city_name(location_text),
        "district_name": normalize_district_name(location_text),
        "headcount_text": find_after("招聘人数："),
        "publisher": hr_name,
        "published_at": find_after("更新日期："),
        "detail_url": detail_url,
    }


def normalize_job_item(item: dict[str, Any], detail_item: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = detail_item or {}
    detail_url = clean_text(detail.get("detail_url") or item.get("detail_url"))
    source_job_id = clean_text(re.sub(r"^https?://[^/]+", "", detail_url))
    title = clean_text(detail.get("title") or item.get("title"))
    company_name = clean_text(detail.get("company_name") or item.get("company_name"))
    description_parts = [clean_text(detail.get("description_text")), clean_text(detail.get("company_intro"))]
    return {
        "source_job_id": source_job_id,
        "title": title,
        "company_name": company_name,
        "city_name": clean_text(detail.get("city_name") or item.get("city_name")),
        "district_name": clean_text(detail.get("district_name") or item.get("district_name")),
        "salary_text": clean_text(detail.get("salary_text") or item.get("salary_text")),
        "degree_text": clean_text(detail.get("degree_text") or item.get("degree_text")),
        "experience_text": clean_text(detail.get("experience_text")),
        "brand_scale": clean_text(detail.get("brand_scale") or item.get("brand_scale")),
        "brand_stage": clean_text(detail.get("brand_stage") or item.get("brand_stage")),
        "job_type": clean_text(detail.get("job_type")),
        "source_url": detail_url,
        "official_apply_url": detail_url,
        "description_text": "\n".join([part for part in description_parts if part]),
        "publisher": clean_text(detail.get("publisher")),
        "published_at": clean_text(detail.get("published_at") or item.get("published_at")),
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str) -> dict[str, int]:
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
                    ("新职位发现", f"{company_name} 发布了 {title}（{city_name or '全国'}）", cursor.lastrowid),
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
    config: dict[str, Any],
    *,
    query: str,
    city_name: str,
    city_code: str,
    max_pages: int,
    detail_mode: str,
    timeout_seconds: float,
    sleep_seconds: float,
    source_code: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    site_label = config["site_label"]
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
            payload = fetch_list_page(session, config, query=query, city_code=city_code, page_no=page_no, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            emit_progress(progress_callback, f"{site_label} 列表页获取失败，结束当前组合：第 {page_no} 页", query=query, city_name=city_name, page=page_no, source_code=source_code, error=str(exc))
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
            haystack = " ".join([clean_text(raw_item.get("title")), clean_text(raw_item.get("summary_text")), clean_text(raw_item.get("company_name")), clean_text(raw_item.get("location_text"))])
            if detail_mode == "detail_html":
                try:
                    detail_html = fetch_text(session, clean_text(raw_item.get("detail_url")), timeout_seconds)
                    detail_item = parse_detail_html(detail_html, config, clean_text(raw_item.get("detail_url")))
                    haystack = " ".join([haystack, clean_text(detail_item.get("description_text")), clean_text(detail_item.get("company_intro")), clean_text(detail_item.get("location_text"))])
                except Exception as exc:  # noqa: BLE001
                    emit_progress(progress_callback, f"{site_label} 详情页获取失败，回退列表字段继续处理：{clean_text(raw_item.get('detail_url'))}", query=query, city_name=city_name, page=page_no, source_code=source_code, error=str(exc))
            if query and query not in haystack:
                continue
            if city_name and not city_matches(city_name, raw_item.get("location_text"), detail_item.get("location_text"), detail_item.get("company_intro")):
                continue
            job = normalize_job_item(raw_item, detail_item)
            if not job["source_job_id"] or job["source_job_id"] in seen_job_ids:
                continue
            seen_job_ids.add(job["source_job_id"])
            page_jobs.append(job)
            matched_jobs.append(job)
        emit_progress(progress_callback, f"{site_label} {query} - {city_name} 第 {page_no} 页完成：原始 {len(items)} 条，保留 {len(page_jobs)} 条，累计 {len(matched_jobs)} 条", query=query, city_name=city_name, page=page_no, source_code=source_code)
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
    source_code: str | None = None,
) -> dict[str, Any]:
    del page_size, output_dir, runtime_mode
    configure_stdio()
    ensure_db()
    resolved_source = source_code or "healthr"
    config = _get_site_config(resolved_source)
    options = normalize_source_options(source_options)
    normalized_queries = normalize_queries(config, queries)
    normalized_cities = normalize_cities(config, cities)
    target_pages = max(1, min(int(max_pages or 1), 20))
    total_fetched = 0
    total_new = 0
    total_updated = 0
    resolved_city_codes: dict[str, str] = {}
    fallback_to_national_locations: list[str] = []
    empty_result_locations: list[str] = []
    request_trace: list[dict[str, Any]] = []
    site_label = config["site_label"]
    list_url = _make_list_url(config)
    session = build_session(list_url)
    try:
        city_code_map = fetch_city_code_map(session, config, options["request_timeout_seconds"])
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_code, is_fallback = resolve_city_code(city_name, city_code_map)
                if city_code:
                    resolved_city_codes[city_name] = city_code
                elif is_fallback:
                    fallback_to_national_locations.append(city_name)
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
                    config,
                    query=query,
                    city_name=city_name,
                    city_code=city_code,
                    max_pages=target_pages,
                    detail_mode=options["detail_mode"],
                    timeout_seconds=options["request_timeout_seconds"],
                    sleep_seconds=options["sleep_seconds"],
                    source_code=resolved_source,
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
                if is_fallback:
                    trace_item["status"] = "fallback_national"
                if not jobs:
                    trace_item["status"] = "empty"
                    if city_name not in empty_result_locations:
                        empty_result_locations.append(city_name)
                    request_trace.append(trace_item)
                    continue
                stats = save_to_db(jobs, source_code=resolved_source)
                total_fetched += len(jobs)
                total_new += stats["new"]
                total_updated += stats["updated"]
                trace_item["new_count"] = stats["new"]
                trace_item["updated_count"] = stats["updated"]
                request_trace.append(trace_item)
    finally:
        session.close()
    emit_progress(progress_callback, f"{site_label} 采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条", source_code=resolved_source)
    return {
        "source_code": resolved_source,
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "updated": total_updated,
        "resolved_city_codes": resolved_city_codes,
        "fallback_to_national_locations": fallback_to_national_locations,
        "empty_result_locations": empty_result_locations,
        "request_trace": request_trace,
        "request_summary": {
            "total_targets": len(normalized_queries) * len(normalized_cities),
            "resolved_targets": sum(1 for item in request_trace if item.get("status") in {"resolved", "fallback_national"} and item.get("fetched_count")),
            "fallback_targets": len(fallback_to_national_locations),
            "empty_targets": sum(1 for item in request_trace if item.get("status") == "empty"),
        },
    }


if __name__ == "__main__":
    result = run_incremental_update()
    print(result)
