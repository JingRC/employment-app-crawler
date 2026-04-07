from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None

try:
    import requests
except ImportError:
    requests = None


DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"
BASE_URL = "https://www.liepin.com/zhaopin/"
DEFAULT_QUERIES = ["Python", "Java", "前端", "测试"]
DEFAULT_CITIES = ["全国", "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州"]
DEFAULT_WAIT_SECONDS = 8.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_SOURCE_OPTIONS = {
    "city_mode": "precise_if_supported",
    "enable_request_probe": True,
    "probe_timeout_seconds": 8.0,
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
        emit_progress(progress_callback, "收到取消信号，准备停止猎聘采集", **context)
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


def retry_delay(attempt: int) -> float:
    return RETRY_BACKOFF_SECONDS * attempt


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
        raise RuntimeError("未安装 DrissionPage，无法执行猎聘浏览器采集")
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


def parse_bool_option(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def normalize_source_options(source_options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(DEFAULT_SOURCE_OPTIONS)
    options.update(source_options or {})
    city_mode = clean_text(options.get("city_mode")).lower() or DEFAULT_SOURCE_OPTIONS["city_mode"]
    if city_mode not in {"precise_if_supported", "result_filter_only"}:
        city_mode = DEFAULT_SOURCE_OPTIONS["city_mode"]
    try:
        probe_timeout_seconds = float(options.get("probe_timeout_seconds") or DEFAULT_SOURCE_OPTIONS["probe_timeout_seconds"])
    except (TypeError, ValueError):
        probe_timeout_seconds = DEFAULT_SOURCE_OPTIONS["probe_timeout_seconds"]
    return {
        "city_mode": city_mode,
        "enable_request_probe": parse_bool_option(options.get("enable_request_probe"), DEFAULT_SOURCE_OPTIONS["enable_request_probe"]),
        "probe_timeout_seconds": max(3.0, min(probe_timeout_seconds, 20.0)),
    }


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def build_search_url(query: str) -> str:
    return f"{BASE_URL}?{urlencode({'key': query})}"


def parse_list_response_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"items": []}
    data = (body.get("data") or {}).get("data") or {}
    return {
        "items": [item for item in (data.get("jobCardList") or []) if isinstance(item, dict)],
    }


def extract_list_payload(packet: Any) -> dict[str, Any]:
    response = getattr(packet, "response", None)
    body = getattr(response, "body", None)
    payload = parse_list_response_body(body)
    request = getattr(packet, "request", None)
    post_data = getattr(request, "postData", None) or {}
    form = ((post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(post_data, dict) else {}
    return {
        "items": list(payload.get("items") or []),
        "current_page": int(form.get("currentPage") or 0),
        "city_code": clean_text(form.get("city") or form.get("dq")),
    }


def build_cookie_header(page: Any) -> str:
    cookies = page.cookies(all_domains=True, all_info=False)
    if isinstance(cookies, dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if clean_text(key))
    return str(cookies or "")


def normalize_request_headers(headers: Any, *, cookie_header: str, referer: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if isinstance(headers, dict):
        iterator = headers.items()
    else:
        iterator = []
    for key, value in iterator:
        header_key = clean_text(key)
        header_value = clean_text(value)
        if not header_key or not header_value:
            continue
        if header_key.lower() in {"content-length", "host", "cookie"}:
            continue
        normalized[header_key] = header_value
    normalized.setdefault("Referer", referer)
    normalized.setdefault("Origin", "https://www.liepin.com")
    normalized.setdefault("Accept", "application/json, text/plain, */*")
    normalized.setdefault(
        "User-Agent",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    if cookie_header:
        normalized["Cookie"] = cookie_header
    return normalized


def extract_list_request_sample(packet: Any, page: Any, *, query: str, city_name: str) -> dict[str, Any]:
    request = getattr(packet, "request", None)
    request_url = clean_text(getattr(request, "url", ""))
    if not request_url:
        return {}
    post_data = getattr(request, "postData", None)
    raw_body_text = ""
    if isinstance(post_data, str):
        raw_body_text = post_data
    elif isinstance(post_data, dict):
        try:
            raw_body_text = json.dumps(post_data, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raw_body_text = ""
    referer = clean_text(getattr(page, "url", "")) or build_search_url(query)
    parsed_url = urlsplit(request_url)
    form = ((post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(post_data, dict) else {}
    return {
        "method": clean_text(getattr(request, "method", "POST")) or "POST",
        "url": request_url,
        "query_params": dict(parse_qsl(parsed_url.query, keep_blank_values=True)),
        "headers": normalize_request_headers(getattr(request, "headers", None), cookie_header=build_cookie_header(page), referer=referer),
        "post_data": post_data if isinstance(post_data, dict) else {},
        "raw_body_text": raw_body_text,
        "header_keys": sorted(str(key) for key in (getattr(request, "headers", None) or {}).keys()) if isinstance(getattr(request, "headers", None), dict) else [],
        "form_fields": sorted(str(key) for key in form.keys()) if isinstance(form, dict) else [],
        "query": query,
        "city_name": city_name,
        "referer": referer,
        "request_debug_context": extract_request_debug_context(packet),
    }


def replay_list_api_sample(sample: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    if requests is None:
        return {"ok": False, "reason": "requests_not_installed"}
    request_url = clean_text(sample.get("url"))
    if not request_url:
        return {"ok": False, "reason": "missing_url"}
    headers = sample.get("headers") if isinstance(sample.get("headers"), dict) else {}
    post_data = sample.get("post_data") if isinstance(sample.get("post_data"), dict) else {}
    raw_body_text = clean_text(sample.get("raw_body_text"))
    content_type = clean_text(headers.get("Content-Type") or headers.get("content-type")).lower()
    request_kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout_seconds}
    if "application/json" in content_type:
        request_kwargs["data"] = raw_body_text or json.dumps(post_data, ensure_ascii=False, separators=(",", ":"))
    elif "application/x-www-form-urlencoded" in content_type:
        request_kwargs["data"] = post_data
    else:
        request_kwargs["json"] = post_data
    try:
        response = requests.post(request_url, **request_kwargs)
        response.raise_for_status()
        try:
            response_json = response.json()
        except ValueError:
            return {
                "ok": False,
                "reason": "non_json_response",
                "status_code": int(getattr(response, "status_code", 0) or 0),
                "content_type": clean_text(response.headers.get("Content-Type")),
                "body_preview": clean_text(response.text)[:120],
            }
        payload = parse_list_response_body(response_json)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
    response_data = ((response_json.get("data") or {}).get("data") or {}) if isinstance(response_json, dict) else {}
    form = ((post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(post_data, dict) else {}
    return {
        "ok": bool(payload.get("items")),
        "items": len(payload.get("items") or []),
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "content_type": clean_text(response.headers.get("Content-Type")),
        "current_page": int(form.get("currentPage") or 0),
        "city_code": clean_text(form.get("city") or form.get("dq")),
        "response_keys": ",".join(sorted(str(key) for key in response_data.keys()))[:120],
        "reason": "empty_items" if not payload.get("items") else "",
        "body_preview": "",
    }


def summarize_request_sample(sample: dict[str, Any]) -> str:
    headers = sample.get("headers") if isinstance(sample.get("headers"), dict) else {}
    query_params = sample.get("query_params") if isinstance(sample.get("query_params"), dict) else {}
    post_data = sample.get("post_data") if isinstance(sample.get("post_data"), dict) else {}
    form = ((post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(post_data, dict) else {}
    content_type = clean_text(headers.get("Content-Type") or headers.get("content-type"))
    cookie_present = "yes" if clean_text(headers.get("Cookie") or headers.get("cookie")) else "no"
    header_keys = ",".join(str(key) for key in (sample.get("header_keys") or [])[:8]) or "-"
    form_fields = ",".join(str(key) for key in (sample.get("form_fields") or [])[:8]) or "-"
    city_context = sample.get("city_context") if isinstance(sample.get("city_context"), dict) else {}
    return (
        f"content_type={content_type or 'unknown'}, cookie={cookie_present}, referer={'yes' if clean_text(sample.get('referer')) else 'no'}, "
        f"query_keys={','.join(sorted(str(key) for key in query_params.keys()))[:80] or '-'}, "
        f"form_page={clean_text(form.get('currentPage')) or '-'}, form_city={clean_text(form.get('city') or form.get('dq')) or '-'}, "
        f"header_keys={header_keys}, form_fields={form_fields}, active_city={clean_text(city_context.get('active_city_name')) or '-'}"
    )


def summarize_page_state_context(page_state_context: dict[str, Any]) -> str:
    if not page_state_context:
        return "未捕获页面隐藏状态"
    state_hits = page_state_context.get("state_hits") if isinstance(page_state_context.get("state_hits"), list) else []
    hidden_fields = page_state_context.get("hidden_fields") if isinstance(page_state_context.get("hidden_fields"), list) else []
    script_preview = clean_text(page_state_context.get("script_preview"))
    first_hit = state_hits[0] if state_hits and isinstance(state_hits[0], dict) else {}
    first_hidden = hidden_fields[0] if hidden_fields and isinstance(hidden_fields[0], dict) else {}
    return (
        f"state_hits={len(state_hits)}, hidden_fields={len(hidden_fields)}, "
        f"first_state={clean_text(first_hit.get('path')) or '-'}:{clean_text(first_hit.get('city') or first_hit.get('dq')) or '-'}, "
        f"first_hidden={clean_text(first_hidden.get('name')) or '-'}:{clean_text(first_hidden.get('value')) or '-'}, "
        f"script={script_preview or '-'}"
    )


def summarize_request_debug_context(debug_context: dict[str, Any]) -> str:
    if not debug_context:
        return "未捕获请求对象附加字段"
    scalar_fields = debug_context.get("scalar_fields") if isinstance(debug_context.get("scalar_fields"), dict) else {}
    dict_fields = debug_context.get("dict_fields") if isinstance(debug_context.get("dict_fields"), dict) else {}
    extra_candidates = debug_context.get("extra_candidates") if isinstance(debug_context.get("extra_candidates"), list) else []
    object_fields = debug_context.get("object_fields") if isinstance(debug_context.get("object_fields"), dict) else {}
    return (
        f"attrs={','.join(str(item) for item in (debug_context.get('attribute_names') or [])[:12]) or '-'}, "
        f"header_like={','.join(str(item) for item in (debug_context.get('header_like_fields') or [])[:8]) or '-'}, "
        f"scalar={';'.join(f'{key}={value}' for key, value in list(scalar_fields.items())[:6]) or '-'}, "
        f"dict={';'.join(f'{key}={value}' for key, value in list(dict_fields.items())[:4]) or '-'}, "
        f"object={';'.join(f'{key}={value}' for key, value in list(object_fields.items())[:3]) or '-'}, "
        f"extra={';'.join(str(item) for item in extra_candidates[:6]) or '-'}, "
        f"preview={clean_text(debug_context.get('preview')) or '-'}"
    )


def diagnose_form_city_source(sample: dict[str, Any]) -> str:
    post_data = sample.get("post_data") if isinstance(sample.get("post_data"), dict) else {}
    form = ((post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(post_data, dict) else {}
    city_context = sample.get("city_context") if isinstance(sample.get("city_context"), dict) else {}
    page_state_context = sample.get("page_state_context") if isinstance(sample.get("page_state_context"), dict) else {}
    requested_city = clean_text(city_context.get("requested_city") or sample.get("city_name"))
    active_city = clean_text(city_context.get("active_city_name"))
    form_city = clean_text(form.get("city") or form.get("dq"))
    available_city_code = clean_text(city_context.get("available_city_code"))
    resolved_city_code = clean_text(city_context.get("resolved_city_code"))
    state_hits = page_state_context.get("state_hits") if isinstance(page_state_context.get("state_hits"), list) else []
    for hit in state_hits:
        if not isinstance(hit, dict):
            continue
        state_city = clean_text(hit.get("city") or hit.get("dq"))
        if form_city and state_city == form_city:
            return f"mainSearchPcConditionForm.city/dq={form_city} 已在页面状态树 {clean_text(hit.get('path')) or '-'} 中出现，优先追这条前端状态注入链路"
    hidden_fields = page_state_context.get("hidden_fields") if isinstance(page_state_context.get("hidden_fields"), list) else []
    for field in hidden_fields:
        if not isinstance(field, dict):
            continue
        hidden_value = clean_text(field.get("value"))
        field_name = clean_text(field.get("name"))
        if form_city and hidden_value == form_city:
            return f"mainSearchPcConditionForm.city/dq={form_city} 与隐藏字段 {field_name or '-'} 一致，优先检查 DOM 隐藏表单赋值链路"
    if form_city and active_city and not available_city_code and not resolved_city_code:
        return (
            f"页面活动城市为 {active_city}，但未解析到对应城市上下文码，"
            f"mainSearchPcConditionForm.city/dq 却保留 {form_city}，更像隐藏表单态残留"
        )
    if form_city and resolved_city_code and form_city != resolved_city_code:
        return f"请求体城市字段 {form_city} 与已解析城市上下文 {resolved_city_code} 不一致，优先检查 mainSearchPcConditionForm 生成逻辑"
    init_context = sample.get("init_context") if isinstance(sample.get("init_context"), dict) else {}
    init_form_city = clean_text(init_context.get("request_city"))
    if form_city and init_form_city and form_city == init_form_city:
        return f"mainSearchPcConditionForm.city/dq={form_city} 与 cond-init 请求里的城市字段一致，可优先追 cond-init 初始化链路"
    if form_city and not init_context:
        return f"首屏阶段未捕获到 cond-init，但 mainSearchPcConditionForm.city/dq 仍为 {form_city}，更像页面已注入的隐藏表单态"
    return "未发现明确的 form_city 来源错位"


def summarize_init_context(init_context: dict[str, Any]) -> str:
    if not init_context:
        return "未捕获 cond-init 初始化包"
    return (
        f"request_city={clean_text(init_context.get('request_city')) or '-'}, "
        f"url={clean_text(init_context.get('request_url')) or '-'}, "
        f"body={clean_text(init_context.get('body_preview')) or '-'}"
    )


def extract_cond_init_summary(packet: Any) -> dict[str, Any]:
    request = getattr(packet, "request", None)
    response = getattr(packet, "response", None)
    post_data = getattr(request, "postData", None) or {}
    body = getattr(response, "body", None)
    request_city = ""
    if isinstance(post_data, dict):
        request_city = clean_text(post_data.get("city") or post_data.get("dq") or ((post_data.get("data") or {}).get("city")))
    body_preview = ""
    if isinstance(body, dict):
        serialized = json.dumps(body, ensure_ascii=False)
        body_preview = clean_text(serialized)[:160]
    else:
        body_preview = clean_text(body)[:160]
    return {
        "request_city": request_city,
        "request_url": clean_text(getattr(request, "url", "")),
        "body_preview": body_preview,
    }


def summarize_sample_diff(previous_sample: dict[str, Any], current_sample: dict[str, Any]) -> str:
    previous_headers = previous_sample.get("headers") if isinstance(previous_sample.get("headers"), dict) else {}
    current_headers = current_sample.get("headers") if isinstance(current_sample.get("headers"), dict) else {}
    previous_post_data = previous_sample.get("post_data") if isinstance(previous_sample.get("post_data"), dict) else {}
    current_post_data = current_sample.get("post_data") if isinstance(current_sample.get("post_data"), dict) else {}
    previous_form = ((previous_post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(previous_post_data, dict) else {}
    current_form = ((current_post_data.get("data") or {}).get("mainSearchPcConditionForm") or {}) if isinstance(current_post_data, dict) else {}
    previous_context = previous_sample.get("city_context") if isinstance(previous_sample.get("city_context"), dict) else {}
    current_context = current_sample.get("city_context") if isinstance(current_sample.get("city_context"), dict) else {}
    changed_bits: list[str] = []
    if clean_text(previous_headers.get("Referer")) != clean_text(current_headers.get("Referer")):
        changed_bits.append("referer")
    if clean_text(previous_form.get("currentPage")) != clean_text(current_form.get("currentPage")):
        changed_bits.append(f"page:{clean_text(previous_form.get('currentPage')) or '-'}->{clean_text(current_form.get('currentPage')) or '-'}")
    if clean_text(previous_form.get("city") or previous_form.get("dq")) != clean_text(current_form.get("city") or current_form.get("dq")):
        changed_bits.append(
            f"city:{clean_text(previous_form.get('city') or previous_form.get('dq')) or '-'}->{clean_text(current_form.get('city') or current_form.get('dq')) or '-'}"
        )
    if clean_text(previous_context.get("active_city_name")) != clean_text(current_context.get("active_city_name")):
        changed_bits.append(
            f"active_city:{clean_text(previous_context.get('active_city_name')) or '-'}->{clean_text(current_context.get('active_city_name')) or '-'}"
        )
    previous_header_keys = set(str(key) for key in (previous_sample.get("header_keys") or []))
    current_header_keys = set(str(key) for key in (current_sample.get("header_keys") or []))
    if previous_header_keys != current_header_keys:
        changed_bits.append("header_keys_changed")
    if not changed_bits:
        return "无明显上下文字段变化"
    return "；".join(changed_bits)


def extract_page_city_context(page: Any) -> dict[str, Any]:
    try:
        payload = page.run_js(
            """
            const cityNodes = Array.from(document.querySelectorAll('[data-key="dq"][data-code]'));
            const active = cityNodes.find((el) => {
                const className = el.className || '';
                return className.includes('active') || className.includes('selected') || el.getAttribute('aria-current') === 'true';
            });
            return {
                current_url: location.href || '',
                title: document.title || '',
                city_option_count: cityNodes.length,
                active_city_name: active ? ((active.dataset.name || active.innerText || '').trim()) : '',
                active_city_code: active ? ((active.dataset.code || '').trim()) : '',
            };
            """
        )
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_page_state_context(page: Any) -> dict[str, Any]:
    try:
        payload = page.run_js(
            """
            const pickStateObject = (value) => {
                if (!value || typeof value !== 'object') {
                    return null;
                }
                const city = value.city ?? value.dq ?? '';
                const currentPage = value.currentPage ?? value.pageNo ?? value.pageIndex ?? '';
                if (!city && !currentPage && !Object.prototype.hasOwnProperty.call(value, 'mainSearchPcConditionForm')) {
                    return null;
                }
                return {
                    city: city == null ? '' : String(city),
                    dq: value.dq == null ? '' : String(value.dq),
                    currentPage: currentPage == null ? '' : String(currentPage),
                    keys: Object.keys(value).slice(0, 8),
                };
            };

            const stateHits = [];
            const seen = new WeakSet();
            const searchObject = (rootName, value, path, depth) => {
                if (!value || typeof value !== 'object' || depth > 5 || seen.has(value) || stateHits.length >= 12) {
                    return;
                }
                seen.add(value);
                const direct = pickStateObject(value);
                if (direct && (path.includes('mainSearchPcConditionForm') || direct.city || direct.dq || direct.currentPage)) {
                    stateHits.push({ root: rootName, path, ...direct });
                }
                for (const key of Object.keys(value)) {
                    if (stateHits.length >= 12) {
                        break;
                    }
                    let child;
                    try {
                        child = value[key];
                    } catch (error) {
                        continue;
                    }
                    if (!child || typeof child !== 'object') {
                        continue;
                    }
                    if (/mainSearchPcConditionForm|search|condition|form|city|dq|job/i.test(key) || depth < 2) {
                        searchObject(rootName, child, path ? `${path}.${key}` : key, depth + 1);
                    }
                }
            };

            const roots = {
                __INITIAL_STATE__: window.__INITIAL_STATE__,
                __NEXT_DATA__: window.__NEXT_DATA__,
                __NUXT__: window.__NUXT__,
                __PRELOADED_STATE__: window.__PRELOADED_STATE__,
                __APOLLO_STATE__: window.__APOLLO_STATE__,
                __pinia: window.__pinia,
                __STORE__: window.__STORE__,
            };
            for (const [rootName, value] of Object.entries(roots)) {
                searchObject(rootName, value, rootName, 0);
            }
            try {
                if (window.store && typeof window.store.getState === 'function') {
                    searchObject('window.store.getState()', window.store.getState(), 'window.store.getState()', 0);
                }
            } catch (error) {
            }

            const hiddenFields = Array.from(document.querySelectorAll('input[type="hidden"], input[name], textarea[name]'))
                .map((el) => ({
                    name: (el.name || el.getAttribute('name') || '').trim(),
                    value: (el.value || el.getAttribute('value') || '').trim(),
                }))
                .filter((item) => item.name || item.value)
                .filter((item) => /city|dq|mainSearchPcConditionForm|condition|search/i.test(item.name) || /^(010|020|021|022|023|024|025|027|028|029|410)$/.test(item.value))
                .slice(0, 12);

            const scripts = Array.from(document.scripts || []);
            const matchedScript = scripts
                .map((script) => (script.textContent || '').trim())
                .find((text) => text.includes('mainSearchPcConditionForm')) || '';

            return {
                state_hits: stateHits,
                hidden_fields: hiddenFields,
                script_preview: matchedScript ? matchedScript.slice(0, 160).replace(/\\s+/g, ' ') : '',
            };
            """
        )
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_request_debug_context(packet: Any) -> dict[str, Any]:
    request = getattr(packet, "request", None)
    if request is None:
        return {}
    attribute_names: list[str] = []
    header_like_fields: list[str] = []
    scalar_fields: dict[str, str] = {}
    dict_fields: dict[str, str] = {}
    object_fields: dict[str, str] = {}
    extra_candidates: list[str] = []
    preview_parts: list[str] = []
    try:
        for name in dir(request):
            if not name or name.startswith("_"):
                continue
            attribute_names.append(str(name))
    except Exception:
        attribute_names = []
    interesting_fields = [
        "headers",
        "header",
        "extra_info",
        "extraInfo",
        "cookies",
        "associatedCookies",
        "hasPostData",
        "initialPriority",
        "referrerPolicy",
        "mixedContentType",
        "method",
        "url",
        "postData",
        "postDataEntries",
        "resourceType",
        "isNavigationRequest",
    ]
    derived_fields = [name for name in attribute_names if any(token in name.lower() for token in ["header", "cookie", "origin", "refer", "site", "mode", "priority", "content", "sec"])]
    seen_field_names: set[str] = set()
    for name in [*interesting_fields, *derived_fields]:
        if name in seen_field_names:
            continue
        seen_field_names.add(name)
        try:
            value = getattr(request, name)
        except Exception:
            continue
        if value in (None, "", [], {}):
            continue
        if name in interesting_fields:
            header_like_fields.append(name)
        else:
            extra_candidates.append(name)
        if isinstance(value, dict):
            keys_preview = ",".join(sorted(str(key) for key in value.keys())[:8])
            dict_fields[name] = keys_preview or "-"
            preview_parts.append(f"{name}={keys_preview}")
        elif isinstance(value, (list, tuple)):
            dict_fields[name] = f"len={len(value)}"
            preview_parts.append(f"{name}[{len(value)}]")
        elif isinstance(value, (str, int, float, bool)):
            cleaned = clean_text(value)[:120]
            scalar_fields[name] = cleaned or "-"
            preview_parts.append(f"{name}={cleaned}")
        else:
            object_preview = inspect_debug_object(value)
            if object_preview:
                object_fields[name] = object_preview
                preview_parts.append(f"{name}={object_preview}")
            else:
                cleaned = clean_text(value)[:120]
                scalar_fields[name] = cleaned or "-"
                preview_parts.append(f"{name}={cleaned}")
    return {
        "attribute_names": attribute_names,
        "header_like_fields": header_like_fields,
        "scalar_fields": scalar_fields,
        "dict_fields": dict_fields,
        "object_fields": object_fields,
        "extra_candidates": extra_candidates,
        "preview": "；".join(preview_parts)[:240],
    }


def inspect_debug_object(value: Any) -> str:
    pairs: list[str] = []
    try:
        names = [name for name in dir(value) if name and not name.startswith("_")]
    except Exception:
        return ""
    for name in names:
        if len(pairs) >= 8:
            break
        try:
            attr_value = getattr(value, name)
        except Exception:
            continue
        if callable(attr_value) or attr_value in (None, "", [], {}):
            continue
        if isinstance(attr_value, dict):
            rendered = ",".join(sorted(str(key) for key in attr_value.keys())[:6]) or ["-"]
        elif isinstance(attr_value, (list, tuple)):
            rendered = f"len={len(attr_value)}"
        else:
            rendered = clean_text(attr_value)[:60] or "-"
        pairs.append(f"{name}={rendered}")
    return "|".join(pairs)[:240]


def attach_city_context(
    sample: dict[str, Any],
    *,
    page: Any,
    city_name: str,
    city_map: dict[str, str] | None = None,
    city_entry: dict[str, str] | None = None,
    footer_city_pages: dict[str, str] | None = None,
) -> dict[str, Any]:
    enriched = dict(sample)
    page_context = extract_page_city_context(page)
    page_state_context = extract_page_state_context(page)
    enriched["city_context"] = {
        "requested_city": city_name,
        "active_city_name": clean_text(page_context.get("active_city_name")),
        "active_city_code": clean_text(page_context.get("active_city_code")),
        "current_url": clean_text(page_context.get("current_url")),
        "title": clean_text(page_context.get("title")),
        "city_option_count": int(page_context.get("city_option_count") or 0),
        "available_city_code": clean_text((city_map or {}).get(city_name)),
        "resolved_city_code": clean_text((city_entry or {}).get("code")),
        "resolved_search_url": clean_text((city_entry or {}).get("search_url")),
        "footer_city_page": clean_text((footer_city_pages or {}).get(city_name)),
    }
    enriched["page_state_context"] = page_state_context
    return enriched


def extract_dom_job_cards(page: Any) -> list[dict[str, Any]]:
    try:
        payload = page.run_js(
            """
            return Array.from(document.querySelectorAll('.job-card-pc-container')).map((el) => {
                const lines = (el.innerText || '')
                    .split('\\n')
                    .map((item) => item.trim())
                    .filter(Boolean);
                const anchor = el.querySelector('a[data-nick="job-detail-job-info"]');
                const companyRoot = el.querySelector('[data-nick="job-detail-company-info"]');
                const companySpans = companyRoot ? Array.from(companyRoot.querySelectorAll('span')).map((node) => (node.innerText || '').trim()).filter(Boolean) : [];
                const recruiterBox = el.querySelector('.job-card-right-box');
                return {
                    title: lines[0] || '',
                    location: lines.find((line) => line.includes('-')) || '',
                    salary: lines.find((line) => /k|K|薪资面议|万/.test(line)) || '',
                    experience: lines.find((line) => /年|应届|实习/.test(line)) || '',
                    degree: lines.find((line) => /学历不限|本科|大专|硕士|博士|中专|高中/.test(line)) || '',
                    company_name: companySpans[0] || '',
                    company_industry: companySpans[1] || '',
                    company_stage: companySpans[2] || '',
                    company_scale: companySpans[3] || '',
                    recruiter_text: recruiterBox ? (recruiterBox.innerText || '').trim() : '',
                    source_url: anchor ? (anchor.href || '') : '',
                    description_text: lines.join('\\n'),
                };
            }).filter((item) => item.title && item.company_name);
            """
        )
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def extract_city_option_map(page: Any) -> dict[str, str]:
    try:
        payload = page.run_js(
            """
            return Array.from(document.querySelectorAll('[data-key="dq"][data-code]'))
                .map((el) => ({
                    name: (el.dataset.name || el.innerText || '').trim(),
                    code: (el.dataset.code || '').trim(),
                }))
                .filter((item) => item.name && item.code);
            """
        )
    except Exception:
        return {}
    city_map: dict[str, str] = {}
    for item in payload if isinstance(payload, list) else []:
        city_name = clean_text(item.get("name"))
        city_code = clean_text(item.get("code"))
        if city_name and city_code:
            city_map[city_name] = city_code
    return city_map


def extract_footer_city_page_map(page: Any) -> dict[str, str]:
    try:
        payload = page.run_js(
            """
            return Array.from(document.querySelectorAll('a'))
                .map((el) => ({
                    text: (el.innerText || '').trim(),
                    href: el.href || '',
                }))
                .filter((item) => item.href && item.text.endsWith('招聘网') && item.href.includes('/city-'));
            """
        )
    except Exception:
        return {}
    city_map: dict[str, str] = {}
    for item in payload if isinstance(payload, list) else []:
        text = clean_text(item.get("text"))
        href = clean_text(item.get("href"))
        city_name = clean_text(text.removesuffix("招聘网"))
        if city_name and href:
            city_map[city_name] = href
    return city_map


def build_city_search_url(entry_url: str, query: str) -> str:
    parts = urlsplit(entry_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["key"] = query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def resolve_city_entry_via_footer(
    city_name: str,
    city_page_url: str,
    query: str,
    *,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, str]:
    ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name, query=query)
    request = Request(city_page_url, headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(request, timeout=20).read().decode("utf-8", "replace")
    match = clean_text(next(iter(__import__("re").findall(r"https://www\.liepin\.com/city-[^\"\s<]+/zhaopin/[^\"\s<]+", html)), ""))
    if not match:
        relative = clean_text(next(iter(__import__("re").findall(r"city-[^\"\s<]+/zhaopin/[^\"\s<]+", html)), ""))
        if relative:
            match = f"https://www.liepin.com/{relative.lstrip('/')}"
    if not match:
        return {}
    params = dict(parse_qsl(urlsplit(match).query, keep_blank_values=True))
    city_code = clean_text(params.get("dq"))
    return {
        "code": city_code,
        "city_page_url": city_page_url,
        "search_entry_url": match,
        "search_url": build_city_search_url(match, query),
    }


def dom_card_to_job(item: dict[str, Any]) -> dict[str, Any]:
    city_name, district_name = split_city_district(item.get("location"))
    source_url = clean_text(item.get("source_url"))
    source_job_id = ""
    if "/job/" in source_url:
        source_job_id = source_url.split("/job/", 1)[1].split(".", 1)[0].strip("/")
    tag_values: list[str] = []
    for candidate in [clean_text(item.get("company_industry")), clean_text(item.get("company_stage"))]:
        if candidate and candidate not in tag_values:
            tag_values.append(candidate)
    return {
        "source_job_id": source_job_id,
        "title": clean_text(item.get("title")),
        "company_name": clean_text(item.get("company_name")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(item.get("salary")),
        "degree_text": clean_text(item.get("degree")),
        "experience_text": clean_text(item.get("experience")),
        "brand_scale": clean_text(item.get("company_scale")),
        "brand_stage": clean_text(item.get("company_stage")),
        "job_type": " / ".join(tag_values),
        "source_url": source_url,
        "official_apply_url": source_url,
        "description_text": clean_text(item.get("description_text")) or clean_text(item.get("recruiter_text")),
        "source_code": "liepin",
        "status": "active",
    }


def capture_current_page_payload(
    page: Any,
    *,
    query: str,
    city_name: str,
    city_mode: str,
    resolved_city_entries: dict[str, dict[str, str]],
    footer_city_pages: dict[str, str],
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    for attempt in range(1, MAX_RETRIES + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name)
        page.listen.start("searchfront4c")
        page.get(build_search_url(query))
        safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
        packets = list(page.listen.steps(count=30, timeout=4))
        init_context: dict[str, Any] = {}
        for packet in reversed(packets):
            request = getattr(packet, "request", None)
            request_url = str(getattr(request, "url", ""))
            if "cond-init" in request_url:
                init_context = extract_cond_init_summary(packet)
                break
        city_map = extract_city_option_map(page)
        footer_city_pages.update({k: v for k, v in extract_footer_city_page_map(page).items() if k not in footer_city_pages})
        for known_city, known_code in city_map.items():
            entry = dict(resolved_city_entries.get(known_city) or {})
            entry["code"] = known_code
            resolved_city_entries[known_city] = entry

        if city_mode == "precise_if_supported" and city_name and city_name != "全国":
            city_entry = dict(resolved_city_entries.get(city_name) or {})
            city_code = clean_text(city_map.get(city_name) or city_entry.get("code"))
            if not city_code:
                city_page_url = clean_text(footer_city_pages.get(city_name))
                if city_page_url:
                    resolved = resolve_city_entry_via_footer(
                        city_name,
                        city_page_url,
                        query,
                        should_stop_callback=should_stop_callback,
                        progress_callback=progress_callback,
                    )
                    if resolved:
                        resolved_city_entries[city_name] = resolved
                        city_entry = resolved
                        city_code = clean_text(resolved.get("code"))
            if city_code or clean_text(city_entry.get("search_url")):
                if city_name in city_map:
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 命中站内精确城市编码 {city_code}，切换到精确检索",
                        query=query,
                        city_name=city_name,
                        city_code=city_code,
                    )
                    clicked = bool(
                        page.run_js(
                            f"""
                            const target = Array.from(document.querySelectorAll('[data-key="dq"][data-code]'))
                                .find((el) => ((el.dataset.name || el.innerText || '').trim() === {json.dumps(city_name, ensure_ascii=False)}));
                            if (target) {{
                                target.click();
                                return true;
                            }}
                            return false;
                            """
                        )
                    )
                else:
                    clicked = False
                if clicked:
                    page.listen.start("pc-search-job")
                    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                    city_packets = list(page.listen.steps(count=30, timeout=4))
                    for packet in reversed(city_packets):
                        request = getattr(packet, "request", None)
                        request_url = str(getattr(request, "url", ""))
                        if "pc-search-job" in request_url and "cond-init" not in request_url:
                            payload = extract_list_payload(packet)
                            if payload.get("items"):
                                payload["request_sample"] = attach_city_context(
                                    extract_list_request_sample(packet, page, query=query, city_name=city_name),
                                    page=page,
                                    city_name=city_name,
                                    city_map=city_map,
                                    city_entry=city_entry,
                                    footer_city_pages=footer_city_pages,
                                )
                                payload["request_sample"]["init_context"] = init_context
                                payload["exact_city_selected"] = True
                                payload["city_code"] = city_code
                                return payload
                    dom_items = extract_dom_job_cards(page)
                    if dom_items:
                        return {
                            "items": dom_items,
                            "current_page": 0,
                            "from_dom": True,
                            "exact_city_selected": True,
                            "city_code": city_code,
                        }
                elif clean_text(city_entry.get("search_url")):
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 通过城市招聘网入口解析到城市搜索页，转入精确检索",
                        query=query,
                        city_name=city_name,
                        city_code=city_code,
                    )
                    page.listen.start("pc-search-job")
                    page.get(str(city_entry.get("search_url")))
                    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
                    city_packets = list(page.listen.steps(count=30, timeout=4))
                    for packet in reversed(city_packets):
                        request = getattr(packet, "request", None)
                        request_url = str(getattr(request, "url", ""))
                        if "pc-search-job" in request_url and "cond-init" not in request_url:
                            payload = extract_list_payload(packet)
                            if payload.get("items"):
                                payload["request_sample"] = attach_city_context(
                                    extract_list_request_sample(packet, page, query=query, city_name=city_name),
                                    page=page,
                                    city_name=city_name,
                                    city_map=city_map,
                                    city_entry=city_entry,
                                    footer_city_pages=footer_city_pages,
                                )
                                payload["request_sample"]["init_context"] = init_context
                                payload["exact_city_selected"] = True
                                payload["city_code"] = clean_text(payload.get("city_code")) or city_code
                                payload["city_search_url"] = str(city_entry.get("search_url"))
                                return payload
                    dom_items = extract_dom_job_cards(page)
                    if dom_items:
                        return {
                            "items": dom_items,
                            "current_page": 0,
                            "from_dom": True,
                            "exact_city_selected": True,
                            "city_code": city_code,
                            "city_search_url": str(city_entry.get("search_url")),
                        }
            else:
                emit_progress(
                    progress_callback,
                    f"猎聘 {query} - {city_name} 当前未解析到精确城市入口，回退到结果过滤",
                    query=query,
                    city_name=city_name,
                )

        for packet in reversed(packets):
            request = getattr(packet, "request", None)
            request_url = str(getattr(request, "url", ""))
            if "pc-search-job" in request_url and "cond-init" not in request_url:
                payload = extract_list_payload(packet)
                if payload.get("items"):
                    payload["request_sample"] = attach_city_context(
                        extract_list_request_sample(packet, page, query=query, city_name=city_name),
                        page=page,
                        city_name=city_name,
                        city_map=city_map,
                        city_entry=resolved_city_entries.get(city_name) or {},
                        footer_city_pages=footer_city_pages,
                    )
                    payload["request_sample"]["init_context"] = init_context
                    return payload
        dom_items = extract_dom_job_cards(page)
        if dom_items:
            return {"items": dom_items, "current_page": 0, "from_dom": True}
        if attempt < MAX_RETRIES:
            emit_progress(progress_callback, f"猎聘 {query} 首屏接口未命中，准备第 {attempt + 1} 次重试", query=query, city_name=city_name, page=1)
            safe_sleep(retry_delay(attempt), should_stop_callback, progress_callback, query=query, city_name=city_name, page=1)
    return {"items": [], "current_page": 0}


def load_page_via_click(
    page: Any,
    *,
    target_page_no: int,
    query: str,
    should_stop_callback: Callable[[], bool] | None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, page=target_page_no)
    button = None
    for locator in [
        f"tag:li@@text()={target_page_no}",
        f"tag:a@@text()={target_page_no}",
        f"tag:span@@text()={target_page_no}",
    ]:
        button = page.ele(locator, timeout=1)
        if button is not None:
            break
    if button is None:
        return {"items": [], "current_page": target_page_no - 1}
    page.listen.start("pc-search-job")
    button.click()
    safe_sleep(DEFAULT_WAIT_SECONDS, should_stop_callback, progress_callback, query=query, page=target_page_no)
    packets = list(page.listen.steps(count=30, timeout=4))
    for packet in reversed(packets):
        request = getattr(packet, "request", None)
        request_url = str(getattr(request, "url", ""))
        if "pc-search-job" in request_url and "cond-init" not in request_url:
            payload = extract_list_payload(packet)
            if payload.get("items"):
                payload["request_sample"] = attach_city_context(
                    extract_list_request_sample(packet, page, query=query, city_name=""),
                    page=page,
                    city_name="",
                )
                return payload
    dom_items = extract_dom_job_cards(page)
    if dom_items:
        return {"items": dom_items, "current_page": target_page_no - 1, "from_dom": True}
    return {"items": [], "current_page": target_page_no - 1}


def split_city_district(raw_text: str) -> tuple[str, str]:
    value = clean_text(raw_text)
    if not value:
        return "", ""
    if "-" in value:
        city_name, district_name = value.split("-", 1)
        return clean_text(city_name), clean_text(district_name)
    return value, ""


def normalize_job_item(item: dict[str, Any]) -> dict[str, Any]:
    job = item.get("job") or {}
    comp = item.get("comp") or {}
    recruiter = item.get("recruiter") or {}
    city_name, district_name = split_city_district(job.get("dq"))

    tag_values: list[str] = []
    for candidate in [clean_text(comp.get("compIndustry")), clean_text(job.get("jobKind"))]:
        if candidate and candidate not in tag_values:
            tag_values.append(candidate)
    for label in (job.get("labels") or [])[:8]:
        label_text = clean_text(label)
        if label_text and label_text not in tag_values:
            tag_values.append(label_text)

    description_parts: list[str] = []
    recruiter_name = clean_text(recruiter.get("recruiterName"))
    recruiter_title = clean_text(recruiter.get("recruiterTitle"))
    if recruiter_name or recruiter_title:
        description_parts.append(f"招聘方：{recruiter_name} {recruiter_title}".strip())
    recruiter_status = clean_text(recruiter.get("imShowText"))
    if recruiter_status:
        description_parts.append(f"在线状态：{recruiter_status}")
    for field_name, label in [("requireWorkYears", "经验"), ("requireEduLevel", "学历")]:
        value = clean_text(job.get(field_name))
        if value:
            description_parts.append(f"{label}：{value}")
    if tag_values:
        description_parts.append(f"标签：{'、'.join(tag_values)}")

    return {
        "source_job_id": clean_text(job.get("jobId")),
        "title": clean_text(job.get("title")),
        "company_name": clean_text(comp.get("compName")),
        "city_name": city_name,
        "district_name": district_name,
        "salary_text": clean_text(job.get("salary")),
        "degree_text": clean_text(job.get("requireEduLevel")),
        "experience_text": clean_text(job.get("requireWorkYears")),
        "brand_scale": clean_text(comp.get("compScale")),
        "brand_stage": clean_text(comp.get("compStage")),
        "job_type": " / ".join(tag_values),
        "source_url": clean_text(job.get("link")),
        "official_apply_url": clean_text(job.get("link")),
        "description_text": "\n\n".join(part for part in description_parts if part),
        "source_code": "liepin",
        "status": "active",
    }


def save_to_db(jobs: list[dict[str, Any]], source_code: str = "liepin") -> dict[str, int]:
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


def city_matches(expected_city: str, actual_city: str) -> bool:
    expected = clean_text(expected_city)
    actual = clean_text(actual_city)
    if not expected or expected == "全国":
        return True
    return actual == expected or actual.startswith(expected)


def extract_page_signature_token(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return clean_text(item)
    job = item.get("job") if isinstance(item.get("job"), dict) else {}
    return (
        clean_text(job.get("jobId"))
        or clean_text(job.get("link"))
        or clean_text(job.get("title"))
        or clean_text(item.get("source_job_id"))
        or clean_text(item.get("source_url"))
        or clean_text(item.get("title"))
        or clean_text(item.get("company_name"))
    )


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
    del output_dir, runtime_mode
    configure_stdio()
    ensure_db()

    if ChromiumPage is None:
        raise RuntimeError("未安装 DrissionPage，无法执行猎聘浏览器采集")

    normalized_queries = normalize_queries(queries)
    normalized_cities = normalize_cities(cities)
    normalized_source_options = normalize_source_options(source_options)
    target_pages = max(1, min(int(max_pages or 1), 8))
    target_page_size = max(1, min(int(page_size or 20), 40))

    total_fetched = 0
    total_new = 0
    total_updated = 0
    request_probe_attempts = 0
    request_probe_successes = 0
    seen_page_signatures: set[tuple[str, str, str]] = set()
    seen_job_ids: set[str] = set()
    resolved_city_entries: dict[str, dict[str, str]] = {}
    footer_city_pages: dict[str, str] = {}
    captured_request_samples: dict[str, dict[str, Any]] = {}
    liepin_request_trace: list[dict[str, Any]] = []

    options = build_browser_options()
    page = ChromiumPage(options)
    try:
        emit_progress(progress_callback, "猎聘采集启动，模式 browser_intercept_api")
        if normalized_source_options["city_mode"] == "result_filter_only":
            emit_progress(progress_callback, "猎聘城市模式：仅做结果过滤，不主动切换站内城市", source_code="liepin")
        else:
            emit_progress(progress_callback, "猎聘城市模式：热门城市优先走站内精确检索，其他城市回退结果过滤", source_code="liepin")
        for query in normalized_queries:
            for city_name in normalized_cities:
                city_fetched = 0
                city_new = 0
                city_updated = 0
                city_request_probe_attempts = 0
                city_request_probe_successes = 0
                pages_completed = 0
                stop_reason = ""
                captured_request_sample = False
                emit_progress(progress_callback, f"猎聘开始抓取 {query} - {city_name} 第 1 页", query=query, city_name=city_name, page=1)
                first_payload = capture_current_page_payload(
                    page,
                    query=query,
                    city_name=city_name,
                    city_mode=str(normalized_source_options["city_mode"]),
                    resolved_city_entries=resolved_city_entries,
                    footer_city_pages=footer_city_pages,
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                initial_request_sample = first_payload.get("request_sample") if isinstance(first_payload, dict) else {}
                if initial_request_sample:
                    captured_request_sample = True
                    captured_request_samples[f"{query}|{city_name}"] = initial_request_sample
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 首屏请求样本摘要：{summarize_request_sample(initial_request_sample)}",
                        query=query,
                        city_name=city_name,
                        page=1,
                    )
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} cond-init 诊断：{summarize_init_context(initial_request_sample.get('init_context') if isinstance(initial_request_sample.get('init_context'), dict) else {})}",
                        query=query,
                        city_name=city_name,
                        page=1,
                    )
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 页面状态诊断：{summarize_page_state_context(initial_request_sample.get('page_state_context') if isinstance(initial_request_sample.get('page_state_context'), dict) else {})}",
                        query=query,
                        city_name=city_name,
                        page=1,
                    )
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 请求对象诊断：{summarize_request_debug_context(initial_request_sample.get('request_debug_context') if isinstance(initial_request_sample.get('request_debug_context'), dict) else {})}",
                        query=query,
                        city_name=city_name,
                        page=1,
                    )
                    if normalized_source_options["enable_request_probe"]:
                        request_probe_attempts += 1
                        city_request_probe_attempts += 1
                        probe_result = replay_list_api_sample(
                            initial_request_sample,
                            timeout_seconds=float(normalized_source_options["probe_timeout_seconds"]),
                        )
                        if probe_result.get("ok"):
                            request_probe_successes += 1
                            city_request_probe_successes += 1
                            emit_progress(
                                progress_callback,
                                (
                                    f"猎聘 {query} - {city_name} requests 复放探针成功：返回 {probe_result.get('items', 0)} 条，"
                                    f"page={probe_result.get('current_page', 0)} city={clean_text(probe_result.get('city_code')) or '-'}"
                                ),
                                query=query,
                                city_name=city_name,
                                page=1,
                            )
                        else:
                            emit_progress(
                                progress_callback,
                                (
                                    f"猎聘 {query} - {city_name} requests 复放探针失败：{clean_text(probe_result.get('reason')) or '未返回职位'}；"
                                    f"status={probe_result.get('status_code', 0)}；response_keys={clean_text(probe_result.get('response_keys')) or '-'}；"
                                    f"body={clean_text(probe_result.get('body_preview')) or '-'}；sample={summarize_request_sample(initial_request_sample)}"
                                ),
                                query=query,
                                city_name=city_name,
                                page=1,
                            )
                            emit_progress(
                                progress_callback,
                                f"猎聘 {query} - {city_name} form_city 来源诊断：{diagnose_form_city_source(initial_request_sample)}",
                                query=query,
                                city_name=city_name,
                                page=1,
                            )
                current_payload = first_payload
                for page_no in range(1, target_pages + 1):
                    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city_name=city_name, page=page_no)
                    if page_no > 1:
                        emit_progress(progress_callback, f"猎聘开始抓取 {query} - {city_name} 第 {page_no} 页", query=query, city_name=city_name, page=page_no)
                        current_payload = load_page_via_click(
                            page,
                            target_page_no=page_no,
                            query=query,
                            should_stop_callback=should_stop_callback,
                            progress_callback=progress_callback,
                        )
                    request_sample = current_payload.get("request_sample") if isinstance(current_payload, dict) else {}
                    if request_sample:
                        captured_request_sample = True
                        previous_sample = captured_request_samples.get(f"{query}|{city_name}") or {}
                        captured_request_samples[f"{query}|{city_name}"] = request_sample
                        if previous_sample:
                            emit_progress(
                                progress_callback,
                                f"猎聘 {query} - {city_name} 第 {page_no} 页请求上下文变化：{summarize_sample_diff(previous_sample, request_sample)}",
                                query=query,
                                city_name=city_name,
                                page=page_no,
                            )
                    raw_items = list(current_payload.get("items") or [])
                    if not raw_items:
                        stop_reason = "empty"
                        emit_progress(progress_callback, f"猎聘 {query} - {city_name} 第 {page_no} 页未解析到职位", query=query, city_name=city_name, page=page_no)
                        break

                    page_signature = (query, city_name, "|".join(extract_page_signature_token(item) for item in raw_items[:5]))
                    if page_signature in seen_page_signatures:
                        stop_reason = "duplicate_page"
                        emit_progress(progress_callback, f"猎聘 {query} - {city_name} 第 {page_no} 页出现重复分页签名，提前结束", query=query, city_name=city_name, page=page_no)
                        break
                    seen_page_signatures.add(page_signature)

                    if current_payload.get("from_dom"):
                        page_jobs = [dom_card_to_job(item) for item in raw_items[:target_page_size]]
                    else:
                        page_jobs = [normalize_job_item(item) for item in raw_items[:target_page_size]]
                    page_jobs = [job for job in page_jobs if clean_text(job.get("title")) and clean_text(job.get("company_name"))]
                    page_jobs = [job for job in page_jobs if city_matches(city_name, str(job.get("city_name") or ""))]
                    if not page_jobs and city_name != "全国":
                        stop_reason = "city_filtered"
                        emit_progress(progress_callback, f"猎聘 {query} - {city_name} 第 {page_no} 页无匹配城市职位，继续尝试下一页", query=query, city_name=city_name, page=page_no)
                        continue
                    if not page_jobs:
                        stop_reason = "empty_normalized"
                        emit_progress(progress_callback, f"猎聘 {query} - {city_name} 第 {page_no} 页没有可入库职位", query=query, city_name=city_name, page=page_no)
                        break

                    all_seen_before_page = all(clean_text(job.get("source_job_id")) in seen_job_ids for job in page_jobs)
                    stats = save_to_db(page_jobs, source_code="liepin")
                    total_fetched += len(page_jobs)
                    total_new += stats["new"]
                    total_updated += stats["updated"]
                    city_fetched += len(page_jobs)
                    city_new += stats["new"]
                    city_updated += stats["updated"]
                    pages_completed += 1
                    seen_job_ids.update(clean_text(job.get("source_job_id")) for job in page_jobs if clean_text(job.get("source_job_id")))
                    emit_progress(
                        progress_callback,
                        f"猎聘 {query} - {city_name} 第 {page_no} 页完成：抓取 {len(page_jobs)} 条，新增 {stats['new']}，更新 {stats['updated']}",
                        query=query,
                        city_name=city_name,
                        page=page_no,
                    )
                    if all_seen_before_page:
                        stop_reason = "all_seen"
                        emit_progress(progress_callback, f"猎聘 {query} - {city_name} 第 {page_no} 页全部为已处理职位，提前结束", query=query, city_name=city_name, page=page_no)
                        break

                if not stop_reason:
                    stop_reason = "target_pages_reached"
                city_entry = dict(resolved_city_entries.get(city_name) or {})
                liepin_request_trace.append(
                    {
                        "query": query,
                        "location_name": city_name,
                        "status": stop_reason,
                        "pages_completed": pages_completed,
                        "fetched_count": city_fetched,
                        "new_count": city_new,
                        "updated_count": city_updated,
                        "request_probe_attempts": city_request_probe_attempts,
                        "request_probe_successes": city_request_probe_successes,
                        "captured_request_sample": captured_request_sample,
                        "resolved_city_code": clean_text(city_entry.get("code")),
                        "resolved_city_name": clean_text(city_entry.get("name")),
                        "resolved_search_url": clean_text(city_entry.get("search_url")),
                        "footer_city_page": clean_text(footer_city_pages.get(city_name)),
                    }
                )

        emit_progress(progress_callback, f"猎聘采集完成：抓取 {total_fetched} 条，新增 {total_new} 条，更新 {total_updated} 条")
        return {
            "total_fetched": total_fetched,
            "new_to_db": total_new,
            "updated": total_updated,
            "queries": len(normalized_queries),
            "cities": len(normalized_cities),
            "runtime_mode": "browser",
            "detail_mode": "intercept_api",
            "resolved_city_entries": resolved_city_entries,
            "footer_city_pages": footer_city_pages,
            "request_probe_attempts": request_probe_attempts,
            "request_probe_successes": request_probe_successes,
            "captured_request_samples": len(captured_request_samples),
            "liepin_request_trace": liepin_request_trace,
        }
    finally:
        try:
            page.quit()
        except Exception:
            pass


if __name__ == "__main__":
    result = run_incremental_update()
    print(json.dumps(result, ensure_ascii=False))