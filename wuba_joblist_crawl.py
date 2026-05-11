"""58同城招聘爬虫 — 移动端 m.58.com 策略。

m.58.com 移动版无需 JS 反爬验证，直接返回 SSR 职位列表 HTML。
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

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
BASE_URL = "https://m.58.com"
DEFAULT_QUERIES = ["普工", "司机", "快递", "服务员", "销售"]
DEFAULT_CITIES = ["北京", "上海", "广州", "深圳", "青岛", "济南"]
DEFAULT_SOURCE_OPTIONS = {
    "detail_mode": "list_only",
    "request_timeout_seconds": 25.0,
    "sleep_seconds": 1.5,
}
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

CITY_SUBDOMAIN_MAP: dict[str, str] = {
    "北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz",
    "杭州": "hz", "成都": "cd", "武汉": "wh", "南京": "nj",
    "西安": "xa", "重庆": "cq", "天津": "tj", "苏州": "su",
    "郑州": "zz", "长沙": "cs", "东莞": "dg", "青岛": "qd",
    "济南": "jn", "合肥": "hf", "福州": "fz", "厦门": "xm",
    "大连": "dl", "沈阳": "sy", "宁波": "nb", "昆明": "km",
    "石家庄": "sjz", "哈尔滨": "heb", "长春": "cc", "无锡": "wx",
    "佛山": "fs",
    # Tier 2/3 cities
    "珠海": "zh", "惠州": "huizhou", "中山": "zs", "嘉兴": "jx",
    "温州": "wz", "绍兴": "sx", "台州": "tz", "泉州": "qz",
    "徐州": "xz", "常州": "cz", "扬州": "yz", "烟台": "yt",
    "潍坊": "wf", "淄博": "zb", "洛阳": "luoyang", "襄阳": "xy",
    "柳州": "liuzhou", "桂林": "gl", "绵阳": "my", "宜宾": "yb",
    "遵义": "zunyi", "兰州": "lz", "银川": "yc", "西宁": "xn",
    "包头": "bt", "三亚": "sanya", "海口": "haikou", "拉萨": "lasa",
    "乌鲁木齐": "wlmq", "唐山": "ts", "邯郸": "hd", "保定": "bd",
    "大同": "datong", "运城": "yuncheng", "鄂尔多斯": "erds",
    "鞍山": "anshan", "吉林": "jil", "齐齐哈尔": "qqhe",
    "连云港": "lyg", "淮安": "huaian", "湖州": "huzhou",
    "芜湖": "wuhu", "九江": "jiujiang", "赣州": "ganzhou",
    "开封": "kaifeng", "新乡": "xinxiang", "黄石": "huangshi",
    "十堰": "shiyan", "衡阳": "hengyang", "常德": "changde",
    "汕头": "shantou", "湛江": "zhanjiang", "肇庆": "zhaoqing",
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
        emit_progress(progress_callback, "收到取消信号，准备停止 58同城 采集", **context)
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
    detail_mode = clean_text(options.get("detail_mode") or DEFAULT_SOURCE_OPTIONS["detail_mode"]).lower() or "list_only"
    try:
        request_timeout_seconds = float(options.get("request_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    except (TypeError, ValueError):
        request_timeout_seconds = float(DEFAULT_SOURCE_OPTIONS["request_timeout_seconds"])
    try:
        sleep_seconds = float(options.get("sleep_seconds") or DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    except (TypeError, ValueError):
        sleep_seconds = float(DEFAULT_SOURCE_OPTIONS["sleep_seconds"])
    return {
        "detail_mode": detail_mode if detail_mode in {"list_only", "detail_html"} else "list_only",
        "request_timeout_seconds": max(5.0, min(request_timeout_seconds, 60.0)),
        "sleep_seconds": max(0.2, min(sleep_seconds, 10.0)),
    }


def resolve_city_subdomain(city_name: str) -> str:
    for name, sub in CITY_SUBDOMAIN_MAP.items():
        if name in city_name or city_name in name:
            return sub
    return ""


def build_list_url(city_sub: str, keyword: str, page: int = 1) -> str:
    if page <= 1:
        return f"{BASE_URL}/{city_sub}/job/?key={quote(keyword)}"
    return f"{BASE_URL}/{city_sub}/job/pn{page}/?key={quote(keyword)}"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def parse_job_list_html(html: str, city_name: str, keyword: str) -> list[dict[str, Any]]:
    """解析移动端职位列表 HTML (Vue SSR 渲染)。"""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("a", class_="list-item-a")
    items: list[dict[str, Any]] = []

    for card in cards:
        href = str(card.get("href", "")).strip()
        if not href:
            continue

        # Extract source job ID from URL: /bj/siji/66344343769741x.shtml
        id_match = re.search(r"/(\d+)x\.shtml", href)
        if not id_match:
            continue
        source_job_id = id_match.group(1)

        if href.startswith("//"):
            detail_url = "https:" + href
        elif href.startswith("/"):
            detail_url = BASE_URL + href
        else:
            detail_url = href

        title_el = card.select_one(".info-title")
        title = clean_text(title_el.get_text()) if title_el else ""

        location_el = card.select_one(".local_quXianName")
        location_text = clean_text(location_el.get_text()) if location_el else ""

        salary_el = card.select_one(".info-salary")
        salary_text = clean_text(salary_el.get_text()) if salary_el else ""

        job_type_el = card.select_one(".info-job")
        job_type_text = clean_text(job_type_el.get_text()) if job_type_el else ""

        welfare_els = card.select(".info-tag")
        welfare_text = " ".join(clean_text(w.get_text()) for w in welfare_els) if welfare_els else ""

        company_el = card.select_one(".company")
        company_name = clean_text(company_el.get_text()) if company_el else ""

        employer_el = card.select_one(".employer")
        employer_name = clean_text(employer_el.get_text()) if employer_el else ""

        if not title or not company_name:
            continue

        exp_edu_text = ""
        exp_edu_el = card.select_one(".info-exp, .info-edu, .exp-edu")
        if exp_edu_el:
            exp_edu_text = clean_text(exp_edu_el.get_text())

        items.append({
            "source_job_id": source_job_id,
            "title": title,
            "company_name": company_name,
            "city_name": city_name,
            "salary_text": salary_text,
            "job_type_text": job_type_text,
            "welfare_text": welfare_text,
            "location_text": location_text,
            "employer_name": employer_name,
            "exp_edu_text": exp_edu_text,
            "detail_url": detail_url,
            "search_keyword": keyword,
        })

    return items


def fetch_job_list(
    city_name: str,
    keyword: str,
    max_pages: int,
    session: requests.Session,
    timeout: float,
    sleep_seconds: float,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    city_sub = resolve_city_subdomain(city_name)
    if not city_sub:
        emit_progress(progress_callback, f"58同城不支持该城市子域名: {city_name}", city_name=city_name, query=keyword)
        return []

    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name, query=keyword, page=page)

        list_url = build_list_url(city_sub, keyword, page)
        for attempt in range(3):
            ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name, query=keyword, page=page)
            try:
                resp = session.get(list_url, timeout=timeout, headers=REQUEST_HEADERS)
                if resp.status_code == 200:
                    resp.encoding = "utf-8"
                    break
                if attempt < 2:
                    time.sleep(2.0)
            except Exception:
                if attempt < 2:
                    time.sleep(2.0)
                else:
                    emit_progress(progress_callback, f"58同城列表请求失败: {list_url}", city_name=city_name, query=keyword, page=page)
                    return items

        if resp.status_code != 200:
            break

        page_items = parse_job_list_html(resp.text, city_name, keyword)
        if not page_items:
            break

        items.extend(page_items)
        emit_progress(
            progress_callback,
            f"58同城列表 {city_name}/{keyword} 第{page}页抓取 {len(page_items)} 条",
            city_name=city_name, query=keyword, page=page,
        )

        safe_sleep(sleep_seconds, should_stop_callback, progress_callback, city_name=city_name, query=keyword, page=page)

    return items


def normalize_job_record(item: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(item.get("title") or "")
    company_name = clean_text(item.get("company_name") or "")
    city_name = clean_text(item.get("city_name") or "")
    detail_url = clean_text(item.get("detail_url") or "")
    salary_text = clean_text(item.get("salary_text") or "")
    job_type_text = clean_text(item.get("job_type_text") or "")
    location_text = clean_text(item.get("location_text") or "")
    welfare_text = clean_text(item.get("welfare_text") or "")
    exp_edu_text = clean_text(item.get("exp_edu_text") or "")
    source_job_id = clean_text(item.get("source_job_id") or "")

    degree_text = ""
    experience_text = ""
    if exp_edu_text:
        parts = [p.strip() for p in exp_edu_text.replace("/", " ").split()]
        for part in parts:
            if any(kw in part for kw in ("本科", "大专", "硕士", "博士", "高中", "中专", "学历不限", "不限")):
                degree_text = part
            if any(kw in part for kw in ("经验", "年", "应届")):
                experience_text = part

    description_text = welfare_text if welfare_text else ""
    if job_type_text:
        prefix = f"职位类型: {job_type_text}"
        description_text = f"{prefix}\n{description_text}" if description_text else prefix

    unique_raw = f"wuba|{company_name}|{title}|{city_name}|{source_job_id}"
    unique_hash = hashlib.sha256(unique_raw.encode("utf-8")).hexdigest()[:32]

    content_raw = f"{title}|{salary_text}|{degree_text}|{experience_text}|{description_text}"
    content_hash = hashlib.sha256(content_raw.encode("utf-8")).hexdigest()[:32]

    return {
        "source_code": "wuba",
        "title": title,
        "company_name": company_name,
        "city_name": city_name,
        "salary_text": salary_text,
        "degree_text": degree_text,
        "experience_text": experience_text,
        "job_type": job_type_text,
        "description_text": description_text,
        "source_url": detail_url,
        "official_apply_url": "",
        "unique_hash": unique_hash,
        "content_hash": content_hash,
        "scale_text": "",
        "industry": "",
        "location_text": location_text,
    }


def upsert_job_record(conn: sqlite3.Connection, record: dict[str, Any]) -> int:
    source_code = record.get("source_code", "wuba")
    title = record.get("title", "")
    company_name = record.get("company_name", "")
    unique_hash = record.get("unique_hash", "")
    content_hash = record.get("content_hash", "")
    city_name = record.get("city_name", "")
    salary_text = record.get("salary_text", "")
    degree_text = record.get("degree_text", "")
    experience_text = record.get("experience_text", "")
    job_type = record.get("job_type", "")
    description_text = record.get("description_text", "")
    source_url = record.get("source_url", "")
    official_apply_url = record.get("official_apply_url", "")
    scale_text = record.get("scale_text", "")
    industry = record.get("industry", "")

    now_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    existing = conn.execute(
        "SELECT id, status, content_hash FROM jobs WHERE unique_hash = ?",
        (unique_hash,),
    ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO jobs (
                source_code, title, company_name, city_name, salary_text,
                degree_text, experience_text, job_type, description_text,
                source_url, official_apply_url, unique_hash, content_hash,
                status, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                source_code, title, company_name, city_name, salary_text,
                degree_text, experience_text, job_type, description_text,
                source_url, official_apply_url, unique_hash, content_hash,
                now_text, now_text,
            ),
        )
        return 1

    existing_row = dict(existing)
    existing_hash = str(existing_row.get("content_hash") or "")
    if content_hash != existing_hash:
        conn.execute(
            """
            UPDATE jobs SET content_hash = ?, salary_text = ?, degree_text = ?,
            experience_text = ?, description_text = ?, last_seen_at = ?,
            status = CASE WHEN status = 'inactive' THEN 'active' ELSE status END
            WHERE unique_hash = ?
            """,
            (content_hash, salary_text, degree_text, experience_text, description_text, now_text, unique_hash),
        )
        return 1

    conn.execute(
        "UPDATE jobs SET last_seen_at = ? WHERE unique_hash = ? AND last_seen_at < ?",
        (now_text, unique_hash, now_text),
    )
    return 0


def run_incremental_update(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    max_pages: int = 3,
    page_size: int = 30,
    runtime_mode: str = "requests_only",
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    source_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configure_stdio()

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    opts = normalize_source_options(source_options)

    emit_progress(
        progress_callback,
        f"58同城(m.58.com)开始抓取：{len(normalized_cities)} 个城市，{len(normalized_queries)} 个关键词",
        source_code="wuba",
    )

    total_fetched = 0
    new_to_db = 0

    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    try:
        session = build_session()

        for city_name in normalized_cities:
            ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name)

            city_sub = resolve_city_subdomain(city_name)
            if not city_sub:
                emit_progress(progress_callback, f"58同城跳过不支持的城市: {city_name}", city_name=city_name)
                continue

            for keyword in normalized_queries:
                ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name, query=keyword)

                list_items = fetch_job_list(
                    city_name=city_name,
                    keyword=keyword,
                    max_pages=max_pages,
                    session=session,
                    timeout=opts["request_timeout_seconds"],
                    sleep_seconds=opts["sleep_seconds"],
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )

                for item in list_items:
                    ensure_not_cancelled(should_stop_callback, progress_callback)

                    record = normalize_job_record(item)
                    if not record["title"] or not record["company_name"]:
                        continue

                    total_fetched += 1
                    try:
                        added = upsert_job_record(conn, record)
                        new_to_db += added
                    except Exception:
                        pass

                conn.commit()

        conn.commit()
    finally:
        conn.close()

    result = {
        "total_fetched": total_fetched,
        "new_to_db": new_to_db,
        "status": "success",
        "source_code": "wuba",
    }

    emit_progress(
        progress_callback,
        f"58同城抓取完成：抓取 {total_fetched} 条，新增 {new_to_db} 条",
        source_code="wuba",
    )

    return result


if __name__ == "__main__":
    print(run_incremental_update())
