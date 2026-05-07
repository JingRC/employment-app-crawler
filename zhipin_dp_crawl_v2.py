"""
使用 DrissionPage (CDP) 批量采集 Boss 直聘的真实职位数据
通过监听网络请求拦截 API 响应，获取包含薪资等完整数据
检测到验证码时暂停 60 秒后重试
"""
import hashlib
import json
import os
import re
import socket
import sqlite3
import sys
import time
import random
import tempfile
from pathlib import Path
from typing import Any, Callable

from DrissionPage import ChromiumPage, ChromiumOptions
from zhipin_joblist_crawl import (
    _normalize_cookie_value,
    detect_browser_path,
    load_local_secrets,
    merge_cookie_strings,
    persist_cookie_bundle,
    resolve_browser_preference,
    resolve_browser_profile,
)

# ===== 配置 =====
DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"

QUERIES = ["Java", "Python", "前端", "测试", "C++", "产品经理"]
CITIES = {
    "101120200": "青岛",
    "101120100": "济南",
    "101010100": "北京",
    "101020100": "上海",
    "101210100": "杭州",
    "101280600": "深圳",
}

MAX_PAGES = 3


class CrawlCancelledError(Exception):
    pass


CITY_NAME_TO_CODE = {name: code for code, name in CITIES.items()}
DEFAULT_DEFERRED_HIGH_RISK_PAIRS = [{"query": "Java", "city": "北京"}]


def configure_stdio():
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
        emit_progress(progress_callback, "收到取消信号，准备停止浏览器采集", **context)
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


def ensure_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
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
    """)
    conn.execute("""
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
    """)
    conn.commit()
    conn.close()


def normalize_api_job(item, city_name_hint=""):
    """将 API 返回的 jobList item 转为统一格式"""
    job_name = item.get("jobName", "")
    brand_name = item.get("brandName", "")
    city = item.get("cityName", city_name_hint)
    area = item.get("areaDistrict", "")
    if not area:
        area = item.get("businessDistrict", "")

    sal_lo = item.get("salaryDesc", "")
    encrypt_id = item.get("encryptJobId", "")
    source_url = f"https://www.zhipin.com/job_detail/{encrypt_id}.html" if encrypt_id else ""

    skills = item.get("skills", [])
    job_type = ", ".join(skills) if skills else ""

    return {
        "job_name": job_name,
        "salary": sal_lo,
        "city": city,
        "area": area,
        "experience": item.get("jobExperience", ""),
        "degree": item.get("jobDegree", ""),
        "brand": brand_name,
        "brand_scale": item.get("brandScaleName", ""),
        "brand_stage": item.get("brandStageName", ""),
        "job_type": job_type,
        "encrypt_job_id": encrypt_id,
        "source_url": source_url,
    }


def parse_cards_from_html(page):
    """从渲染的 HTML 解析职位卡片 (备用方案)"""
    jobs = []
    cards = page.eles("css:.job-card-box")
    for card in cards:
        try:
            title = ""
            try:
                title = card.ele("css:.job-name").text.strip()
            except Exception:
                pass

            salary = ""
            try:
                salary = card.ele("css:.job-salary").text.strip()
            except Exception:
                pass

            city, district = "", ""
            try:
                loc_text = card.ele("css:.company-location").text.strip()
                parts = loc_text.split("·")
                city = parts[0].strip() if parts else ""
                district = parts[1].strip() if len(parts) > 1 else ""
            except Exception:
                pass

            company = ""
            try:
                company = card.ele("css:.boss-name").text.strip()
            except Exception:
                pass

            exp, degree = "", ""
            try:
                tags = card.eles("css:.tag-list li")
                for tag in tags:
                    t = tag.text.strip()
                    if any(k in t for k in ["年", "经验", "应届"]):
                        exp = t
                    elif any(k in t for k in ["本科", "硕士", "大专", "博士", "学历", "不限"]):
                        degree = t
            except Exception:
                pass

            source_url, enc_id = "", ""
            try:
                link = card.ele("css:a.job-name")
                href = link.attr("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.zhipin.com" + href
                source_url = href
                m = re.search(r"/job_detail/([^.?]+)", href)
                if m:
                    enc_id = m.group(1)
            except Exception:
                pass

            if title and company:
                jobs.append({
                    "job_name": title, "salary": salary, "city": city, "area": district,
                    "experience": exp, "degree": degree, "brand": company,
                    "brand_scale": "", "brand_stage": "", "job_type": "",
                    "encrypt_job_id": enc_id, "source_url": source_url,
                })
        except Exception:
            pass
    return jobs


def save_to_db(jobs, source_code="boss_dp"):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    for item in jobs:
        title = item.get("job_name", "")
        company = item.get("brand", "")
        city = item.get("city", "")
        if not title or not company:
            continue

        raw_u = f"{source_code}|{company}|{title}|{city}"
        u_hash = hashlib.sha256(raw_u.encode()).hexdigest()[:32]
        raw_c = f"{title}|{item.get('salary', '')}"
        c_hash = hashlib.sha256(raw_c.encode()).hexdigest()[:32]

        existing = conn.execute(
            "SELECT id, content_hash FROM jobs WHERE unique_hash = ?", (u_hash,)
        ).fetchone()

        if existing is None:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO jobs (
                    source_job_id, title, company_name, city_name, district_name,
                    salary_text, degree_text, experience_text, brand_scale, brand_stage,
                    job_type, source_url, unique_hash, content_hash, source_code, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active')""",
                (
                    item.get("encrypt_job_id", ""), title, company, city,
                    item.get("area", ""), item.get("salary", ""),
                    item.get("degree", ""), item.get("experience", ""),
                    item.get("brand_scale", ""), item.get("brand_stage", ""),
                    item.get("job_type", ""), item.get("source_url", ""),
                    u_hash, c_hash, source_code,
                ),
            )
            if cursor.rowcount > 0:
                stats["new"] += 1
                conn.execute(
                    "INSERT INTO notifications (notification_type,title,content,related_job_id) VALUES ('new_job',?,?,?)",
                    ("新职位发现", f"{company} 发布了 {title}（{city}）", cursor.lastrowid),
                )
        elif existing["content_hash"] != c_hash:
            conn.execute(
                """UPDATE jobs SET salary_text=?, degree_text=?, experience_text=?,
                   brand_scale=?, brand_stage=?, content_hash=?, last_seen_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (item.get("salary", ""), item.get("degree", ""), item.get("experience", ""),
                 item.get("brand_scale", ""), item.get("brand_stage", ""), c_hash, existing["id"]),
            )
            stats["updated"] += 1
        else:
            conn.execute("UPDATE jobs SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
            stats["unchanged"] += 1

    conn.commit()
    conn.close()
    return stats


def resolve_city_items(cities: list[str] | None) -> list[tuple[str, str]]:
    if not cities:
        return list(CITIES.items())

    resolved: list[tuple[str, str]] = []
    for item in cities:
        value = (item or "").strip()
        if not value:
            continue
        if value in CITIES:
            resolved.append((value, CITIES[value]))
            continue
        code = CITY_NAME_TO_CODE.get(value)
        if code:
            resolved.append((code, value))
    return resolved


def persist_browser_cookie_from_page(page: ChromiumPage, runtime_mode: str = "browser") -> bool:
    try:
        cookies = page.cookies(all_domains=True, all_info=False)
        cookie_value = _normalize_cookie_value(cookies).strip()
        if not cookie_value:
            return False
        local = load_local_secrets()
        merged_cookie = merge_cookie_strings(local.get("cookie", ""), cookie_value)
        persist_cookie_bundle(merged_cookie, runtime_mode=runtime_mode)
        return True
    except Exception:
        return False


def parse_bool_option(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def reserve_local_debug_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def ensure_chromium_debug_address(options: Any) -> str:
    raw_address = str(getattr(options, "address", "") or getattr(options, "_address", "") or "").strip()
    if raw_address and ":" in raw_address:
        return raw_address
    if raw_address.isdigit():
        normalized = f"127.0.0.1:{raw_address}"
        if hasattr(options, "set_address"):
            options.set_address(normalized)
        return normalized

    port = reserve_local_debug_port()
    if hasattr(options, "set_local_port"):
        options.set_local_port(port)
    elif hasattr(options, "set_address"):
        options.set_address(f"127.0.0.1:{port}")
    return str(getattr(options, "address", "") or getattr(options, "_address", "") or f"127.0.0.1:{port}")


def normalize_match_text(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_high_risk_pairs(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []

    parsed_items: list[dict[str, str]] = []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]

    for raw_item in raw_items:
        query = ""
        city = ""
        if isinstance(raw_item, dict):
            query = str(raw_item.get("query") or "").strip()
            city = str(raw_item.get("city") or raw_item.get("city_name") or raw_item.get("city_code") or "").strip()
        else:
            text = str(raw_item or "").strip()
            if not text:
                continue
            parts = re.split(r"[@|]", text, maxsplit=1)
            if len(parts) == 2:
                query, city = parts[0].strip(), parts[1].strip()
        if query and city:
            parsed_items.append({"query": query, "city": city})
    return parsed_items


def build_ordered_target_pairs(
    prepared_queries: list[str],
    city_items: list[tuple[str, str]],
    source_options: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str]:
    raw_pairs = [
        {"query": query.strip(), "city_code": city_code, "city_name": city_name}
        for query in prepared_queries
        for city_code, city_name in city_items
        if query.strip()
    ]
    if not raw_pairs:
        return [], [], "original"

    defer_high_risk_pairs = parse_bool_option(source_options.get("defer_high_risk_pairs", True), True)
    configured_high_risk_pairs = parse_high_risk_pairs(source_options.get("high_risk_pairs"))
    high_risk_pairs = configured_high_risk_pairs or (DEFAULT_DEFERRED_HIGH_RISK_PAIRS if defer_high_risk_pairs else [])
    if not high_risk_pairs:
        for index, pair in enumerate(raw_pairs):
            pair["schedule_order"] = index + 1
            pair["risk_bucket"] = "normal"
        return raw_pairs, [], "original"

    matchers = {
        (normalize_match_text(item.get("query")), normalize_match_text(item.get("city")))
        for item in high_risk_pairs
        if normalize_match_text(item.get("query")) and normalize_match_text(item.get("city"))
    }
    if not matchers:
        for index, pair in enumerate(raw_pairs):
            pair["schedule_order"] = index + 1
            pair["risk_bucket"] = "normal"
        return raw_pairs, [], "original"

    normal_pairs: list[dict[str, Any]] = []
    deferred_pairs: list[dict[str, Any]] = []
    applied_pairs: list[dict[str, str]] = []
    seen_applied_pairs: set[tuple[str, str]] = set()

    for pair in raw_pairs:
        match_key = (normalize_match_text(pair["query"]), normalize_match_text(pair["city_name"]))
        alt_match_key = (normalize_match_text(pair["query"]), normalize_match_text(pair["city_code"]))
        if match_key in matchers or alt_match_key in matchers:
            pair["risk_bucket"] = "deferred_high_risk"
            deferred_pairs.append(pair)
            applied_key = (pair["query"], pair["city_name"])
            if applied_key not in seen_applied_pairs:
                seen_applied_pairs.add(applied_key)
                applied_pairs.append({"query": pair["query"], "city": pair["city_name"]})
        else:
            pair["risk_bucket"] = "normal"
            normal_pairs.append(pair)

    ordered_pairs = normal_pairs + deferred_pairs
    for index, pair in enumerate(ordered_pairs):
        pair["schedule_order"] = index + 1
    ordering_strategy = "deferred_high_risk" if deferred_pairs else "original"
    return ordered_pairs, applied_pairs, ordering_strategy


def run_incremental_update(
    queries: list[str] | None = None,
    cities: list[str] | None = None,
    max_pages: int = MAX_PAGES,
    page_size: int = 30,
    output_dir: Path | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    runtime_mode: str = "hybrid",
    source_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configure_stdio()
    ensure_db()

    prepared_queries = [item.strip() for item in (queries or QUERIES) if str(item).strip()]
    city_items = resolve_city_items(cities)
    if not prepared_queries:
        prepared_queries = list(QUERIES)
    if not city_items:
        city_items = list(CITIES.items())

    source_options = source_options or {}
    ordered_pairs, applied_high_risk_pairs, pair_ordering_strategy = build_ordered_target_pairs(prepared_queries, city_items, source_options)
    requested_browser = resolve_browser_preference(str(source_options.get("browser_preference") or "edge"))
    actual_browser = requested_browser if requested_browser in {"edge", "chrome"} else "edge"
    if requested_browser == "firefox":
        print("Firefox 暂不支持 DrissionPage Chromium 链路，自动回退到 Edge。")
        emit_progress(progress_callback, "Boss 浏览器模式当前仅支持 Edge/Chrome，已自动回退到 Edge", requested_browser=requested_browser, actual_browser=actual_browser)
    default_profile = "Default"
    browser_profile = resolve_browser_profile(str(source_options.get("browser_profile") or default_profile))
    use_system_profile = parse_bool_option(source_options.get("use_system_profile", True), True)
    conservative_first_round = parse_bool_option(source_options.get("conservative_first_round", True), True)
    auto_expand_after_stable = parse_bool_option(source_options.get("auto_expand_after_stable", True), True)
    first_round_page_cap = max(1, min(max_pages, int(source_options.get("first_round_page_cap", 2) or 2)))
    homepage_warmup_seconds = max(3.0, min(20.0, float(source_options.get("homepage_warmup_seconds", 8 if conservative_first_round else 5) or 5)))
    result_page_warmup_seconds = max(3.0, min(20.0, float(source_options.get("result_page_warmup_seconds", 6 if conservative_first_round else 5) or 5)))
    browser_path = detect_browser_path(actual_browser)

    co = ChromiumOptions()
    co.auto_port(True)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-proxy-server")
    co.set_argument("--disable-gpu")
    co.set_argument("--window-size=1200,800")
    if browser_path:
        co.set_browser_path(browser_path)
    ensure_chromium_debug_address(co)

    temp_dir: str | None = None
    if use_system_profile:
        co.use_system_user_path(True)
        if browser_profile:
            co.set_user(browser_profile)
    else:
        temp_dir = tempfile.mkdtemp(prefix=f"zhipin_{actual_browser}_")
        co.set_user_data_path(temp_dir)
        if browser_profile:
            co.set_user(browser_profile)

    profile_mode_label = "system profile" if use_system_profile else f"fresh profile: {temp_dir}"
    browser_label = actual_browser.capitalize()
    print(f"Starting {browser_label} (anti-detect, {profile_mode_label})...")
    emit_progress(
        progress_callback,
        f"Boss 浏览器模式启动：{browser_label} / {browser_profile or 'Default'} / {'系统资料' if use_system_profile else '临时资料'}",
        requested_browser=requested_browser,
        actual_browser=actual_browser,
        browser_profile=browser_profile,
        use_system_profile=use_system_profile,
    )
    try:
        page = ChromiumPage(co)
    except Exception as exc:
        message = str(exc).strip()
        if use_system_profile:
            raise RuntimeError(
                f"Boss 浏览器启动失败：当前 Edge Profile {browser_profile or 'Default'} 可能正被已打开的浏览器占用，或调试端口连接冲突。请先关闭正在运行的 Edge 窗口后重试，或临时关闭‘使用系统资料’再试。原始错误：{message or exc.__class__.__name__}"
            ) from exc
        raise RuntimeError(f"Boss 浏览器启动失败：{message or exc.__class__.__name__}") from exc

    total_new = 0
    total_fetched = 0
    verify_count = 0
    cookie_refreshes = 0
    conservative_round_hits = 0
    stable_expansion_unlocked = not conservative_first_round
    boss_dp_trace: list[dict[str, Any]] = []
    if applied_high_risk_pairs:
        emit_progress(
            progress_callback,
            f"Boss 高风险组合已自动后置，共 {len(applied_high_risk_pairs)} 项",
            pair_ordering_strategy=pair_ordering_strategy,
            deferred_pairs=applied_high_risk_pairs,
        )

    try:
        # 先访问首页建立会话
        print("Loading homepage first...")
        emit_progress(progress_callback, "浏览器采集启动，准备建立会话")
        ensure_not_cancelled(should_stop_callback, progress_callback)
        page.get("https://www.zhipin.com")
        safe_sleep(homepage_warmup_seconds, should_stop_callback, progress_callback)
        if persist_browser_cookie_from_page(page, runtime_mode="browser"):
            cookie_refreshes += 1
            emit_progress(progress_callback, "已从 Boss 浏览器会话提取并保存 Cookie")
        print(f"  Homepage OK: {page.title}")
        safe_sleep(3, should_stop_callback, progress_callback)
        for pair_index, target_pair in enumerate(ordered_pairs):
            query = target_pair["query"].strip()
            city_code = target_pair["city_code"]
            city_name = target_pair["city_name"]
            risk_bucket = target_pair.get("risk_bucket") or "normal"
            schedule_order = int(target_pair.get("schedule_order") or (pair_index + 1))
            if verify_count >= 3:
                print(f"\n连续 {verify_count} 次验证码，停止采集")
                emit_progress(progress_callback, f"连续 {verify_count} 次触发验证码，停止当前来源采集", query=query)
                break
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code)

            print(f"\n{'='*60}")
            print(f"采集: {query} - {city_name}")
            emit_progress(
                progress_callback,
                f"开始采集 {query} - {city_name}",
                query=query,
                city_name=city_name,
                city=city_code,
                risk_bucket=risk_bucket,
                schedule_order=schedule_order,
            )

            all_jobs = []
            pages_completed = 0
            api_pages = 0
            html_fallback_pages = 0
            verify_hits = 0
            page_load_failures = 0
            stop_reason = "target_pages_reached"
            api_jobs: list[dict[str, Any]] = []
            is_first_round = conservative_first_round and pair_index == 0
            if is_first_round:
                current_max_pages = first_round_page_cap
            elif conservative_first_round and auto_expand_after_stable and not stable_expansion_unlocked:
                current_max_pages = first_round_page_cap
            else:
                current_max_pages = max_pages
            if is_first_round:
                conservative_round_hits += 1
                emit_progress(progress_callback, f"首轮保守模式启用：先以 {current_max_pages} 页建立 Boss 浏览器会话", query=query, city_name=city_name, city=city_code)
            for pg in range(1, current_max_pages + 1):
                url = f"https://www.zhipin.com/web/geek/job?query={query}&city={city_code}&page={pg}"
                print(f"  Page {pg}: loading...")
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code, page=pg)

                page.listen.start("wapi/zpgeek/search/joblist.json")

                try:
                    page.get(url)
                except Exception as e:
                    print(f"  Load error: {e}")
                    page_load_failures += 1
                    stop_reason = "page_load_failed"
                    page.listen.stop()
                    break

                safe_sleep(result_page_warmup_seconds if pg == 1 else 5, should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code, page=pg)

                if persist_browser_cookie_from_page(page, runtime_mode="browser"):
                    cookie_refreshes += 1

                cur_url = page.url

                if "verify" in cur_url or "passport" in cur_url:
                    print(f"  ⚠ 触发验证码! 暂停 60 秒后重试...")
                    emit_progress(progress_callback, f"{query} - {city_name} 第 {pg} 页触发验证码，暂停重试", query=query, city_name=city_name, city=city_code, page=pg)
                    verify_count += 1
                    verify_hits += 1
                    stop_reason = "verify_page"
                    page.listen.stop()
                    safe_sleep(60, should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code, page=pg)
                    break

                if "/web/geek/job" not in cur_url:
                    print(f"  Redirected to: {cur_url}")
                    stop_reason = "unexpected_redirect"
                    page.listen.stop()
                    break

                api_jobs = []
                try:
                    packet = page.listen.wait(timeout=8)
                    if packet and packet.response:
                        resp_body = packet.response.body
                        if isinstance(resp_body, str):
                            data = json.loads(resp_body)
                        elif isinstance(resp_body, dict):
                            data = resp_body
                        else:
                            data = {}

                        if data.get("code") == 0:
                            job_list = data.get("zpData", {}).get("jobList", [])
                            for ji in job_list:
                                api_jobs.append(normalize_api_job(ji, city_name))
                            print(f"  API: got {len(api_jobs)} jobs with full data")
                            emit_progress(progress_callback, f"{query} - {city_name} 第 {pg} 页 API 获取 {len(api_jobs)} 条职位", query=query, city_name=city_name, city=city_code, page=pg)
                            verify_count = 0
                            if api_jobs:
                                api_pages += 1
                except Exception as e:
                    print(f"  API intercept: {e}")

                page.listen.stop()

                if api_jobs:
                    all_jobs.extend(api_jobs)
                    pages_completed = pg
                else:
                    html_jobs = parse_cards_from_html(page)
                    if html_jobs:
                        all_jobs.extend(html_jobs)
                        print(f"  HTML: got {len(html_jobs)} jobs (no salary)")
                        emit_progress(progress_callback, f"{query} - {city_name} 第 {pg} 页 HTML 回退获取 {len(html_jobs)} 条职位", query=query, city_name=city_name, city=city_code, page=pg)
                        verify_count = 0
                        html_fallback_pages += 1
                        pages_completed = pg
                    else:
                        print(f"  No data on page {pg}")
                        stop_reason = "empty"
                        break

                print(f"  Total so far: {len(all_jobs)}")

                if is_first_round and pg == 1:
                    delay = random.uniform(14, 22)
                elif html_fallback_pages or verify_hits or risk_bucket != "normal":
                    delay = random.uniform(12, 20)
                else:
                    delay = random.uniform(8, 15)
                print(f"  Waiting {delay:.0f}s...")
                safe_sleep(delay, should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code, page=pg)

            if all_jobs:
                stats = save_to_db(all_jobs, source_code="boss_dp")
                total_new += stats["new"]
                total_fetched += len(all_jobs)
                print(f"  DB: new={stats['new']}, updated={stats['updated']}, unchanged={stats['unchanged']}")
                emit_progress(progress_callback, f"{query} - {city_name} 已写库：新增 {stats['new']}，更新 {stats['updated']}，未变 {stats['unchanged']}", query=query, city_name=city_name, city=city_code)
                boss_dp_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "city_code": city_code,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "fetched_count": len(all_jobs),
                        "new_count": int(stats["new"]),
                        "updated_count": int(stats["updated"]),
                        "api_pages": api_pages,
                        "html_fallback_pages": html_fallback_pages,
                        "verify_hits": verify_hits,
                        "page_load_failures": page_load_failures,
                        "runtime_mode": runtime_mode,
                        "risk_bucket": risk_bucket,
                        "schedule_order": schedule_order,
                    }
                )
                if is_first_round and auto_expand_after_stable:
                    stable_expansion_unlocked = verify_hits == 0 and page_load_failures == 0 and bool(api_jobs or html_fallback_pages or len(all_jobs))
                    if stable_expansion_unlocked:
                        emit_progress(progress_callback, "Boss 首轮会话建立稳定，后续任务将自动放大到完整页数范围", query=query, city_name=city_name, city=city_code)
            else:
                boss_dp_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "city_code": city_code,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "fetched_count": 0,
                        "new_count": 0,
                        "updated_count": 0,
                        "api_pages": api_pages,
                        "html_fallback_pages": html_fallback_pages,
                        "verify_hits": verify_hits,
                        "page_load_failures": page_load_failures,
                        "runtime_mode": runtime_mode,
                        "risk_bucket": risk_bucket,
                        "schedule_order": schedule_order,
                    }
                )
                if is_first_round and auto_expand_after_stable:
                    stable_expansion_unlocked = False

            if conservative_first_round and auto_expand_after_stable and not stable_expansion_unlocked:
                delay2 = random.uniform(28, 40)
            elif risk_bucket != "normal":
                delay2 = random.uniform(26, 38)
            else:
                delay2 = random.uniform(20, 35)
            print(f"  Next query in {delay2:.0f}s...")
            safe_sleep(delay2, should_stop_callback, progress_callback, query=query, city_name=city_name, city=city_code)

    finally:
        page.quit()

    print(f"\n{'='*60}")
    print(f"采集完成! 获取 {total_fetched} 条, 新增 {total_new} 条")

    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    companies = conn.execute("SELECT COUNT(DISTINCT company_name) FROM jobs").fetchone()[0]
    cities_list = [r[0] for r in conn.execute("SELECT DISTINCT city_name FROM jobs").fetchall() if r[0]]
    conn.close()
    print(f"数据库: {total} 职位, {companies} 企业, {len(cities_list)} 城市")
    print(f"城市: {', '.join(cities_list)}")
    emit_progress(progress_callback, f"浏览器拦截采集完成：抓取 {total_fetched} 条，新增 {total_new} 条")
    return {
        "total_fetched": total_fetched,
        "new_to_db": total_new,
        "cities": len(city_items),
        "queries": len(prepared_queries),
        "runtime_mode": runtime_mode,
        "boss_dp_summary": {
            "trace_count": len(boss_dp_trace),
            "api_pages": sum(int(item.get("api_pages") or 0) for item in boss_dp_trace),
            "html_fallback_pages": sum(int(item.get("html_fallback_pages") or 0) for item in boss_dp_trace),
            "verify_hits": sum(int(item.get("verify_hits") or 0) for item in boss_dp_trace),
            "page_load_failures": sum(int(item.get("page_load_failures") or 0) for item in boss_dp_trace),
            "cookie_refreshes": cookie_refreshes,
            "conservative_first_round": conservative_first_round,
            "conservative_round_hits": conservative_round_hits,
            "first_round_page_cap": first_round_page_cap,
            "auto_expand_after_stable": auto_expand_after_stable,
            "stable_expansion_unlocked": stable_expansion_unlocked,
            "runtime_mode": runtime_mode,
            "requested_browser": requested_browser,
            "actual_browser": actual_browser,
            "browser_profile": browser_profile,
            "use_system_profile": use_system_profile,
            "pair_ordering_strategy": pair_ordering_strategy,
            "deferred_pair_count": len(applied_high_risk_pairs),
            "deferred_pairs": applied_high_risk_pairs,
        },
        "boss_dp_trace": boss_dp_trace,
    }


def main():
    queries = os.getenv("BATCH_QUERIES", ",".join(QUERIES)).split(",")
    city_keys = os.getenv("BATCH_CITIES", ",".join(CITIES.keys())).split(",")
    max_pages = int(os.getenv("BATCH_MAX_PAGES", str(MAX_PAGES)))
    result = run_incremental_update(queries=queries, cities=city_keys, max_pages=max_pages)
    print(result)


if __name__ == "__main__":
    main()
