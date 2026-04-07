import csv
import hashlib
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import quote

import requests
import urllib3

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:
    ChromiumOptions = None
    ChromiumPage = None


SECRETS_FILE = Path(__file__).with_name("zhipin_secrets.json")
API_URL = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
DEFAULT_OUTPUT_DIR = Path(r"D:\file\python网络爬虫\实验三\代码\提交")

# 数据库路径 — 与 backend_api 共享同一个 SQLite
DB_DIR = Path(__file__).parent / "就业App原型" / "backend_api" / "data"
DB_PATH = DB_DIR / "jobs.db"

RISK_CONTROL_CODES = {"35", "37"}
REQUIRED_COOKIE_KEYS = {"__zp_stoken__", "wt2", "wbg", "zp_at"}
DEFAULT_RUNTIME_MODE = "requests_only"
DEFAULT_BROWSER_PREFERENCE = "edge"
DEFAULT_BROWSER_PROFILE = "Default"
DEFAULT_COOKIE_LOGIN_WAIT_SECONDS = 40.0


class CrawlCancelledError(Exception):
    pass


class PersistedCookieError(RuntimeError):
    pass


def emit_progress(progress_callback: Optional[Callable[[str, Dict[str, Any]], None]], message: str, **context: Any) -> None:
    if progress_callback is not None:
        progress_callback(message, context)


def ensure_not_cancelled(
    should_stop_callback: Optional[Callable[[], bool]],
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    **context: Any,
) -> None:
    if should_stop_callback is not None and should_stop_callback():
        emit_progress(progress_callback, "收到取消信号，准备停止任务", **context)
        raise CrawlCancelledError("crawl cancelled")


def configure_stdio_encoding() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass


def load_local_secrets() -> Dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}

    try:
        data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, str] = {}
    for key in ("cookie", "zp_token", "token", "verify_ssl", "ca_bundle", "cookie_refreshed_at", "cookie_runtime_mode"):
        value = data.get(key, "")
        if isinstance(value, str):
            result[key] = value.strip()
    return result


def save_local_secrets(values: Dict[str, str]) -> None:
    merged = load_local_secrets()
    merged.update({key: value for key, value in values.items() if isinstance(value, str)})

    ordered: Dict[str, str] = {}
    for key in ("cookie", "zp_token", "token", "verify_ssl", "ca_bundle", "cookie_refreshed_at", "cookie_runtime_mode"):
        ordered[key] = merged.get(key, "")

    SECRETS_FILE.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ssl_options(local: Dict[str, str]) -> Union[bool, str]:
    verify_ssl_raw = os.getenv("ZHIPIN_VERIFY_SSL", local.get("verify_ssl", "true")).strip().lower()
    ca_bundle = os.getenv("ZHIPIN_CA_BUNDLE", local.get("ca_bundle", "")).strip()

    if ca_bundle:
        return ca_bundle
    return verify_ssl_raw not in {"0", "false", "no", "off"}


def resolve_browser_preference(browser_preference: str = DEFAULT_BROWSER_PREFERENCE) -> str:
    raw_value = os.getenv("ZHIPIN_BROWSER", browser_preference or DEFAULT_BROWSER_PREFERENCE).strip().lower()
    if raw_value in {"edge", "msedge", "microsoft-edge"}:
        return "edge"
    if raw_value in {"chrome", "google-chrome"}:
        return "chrome"
    if raw_value in {"firefox", "mozilla", "mozilla-firefox"}:
        return "firefox"
    return DEFAULT_BROWSER_PREFERENCE


def resolve_browser_profile(browser_profile: str = DEFAULT_BROWSER_PROFILE) -> str:
    raw_value = os.getenv("ZHIPIN_BROWSER_PROFILE", browser_profile or DEFAULT_BROWSER_PROFILE).strip()
    return raw_value or DEFAULT_BROWSER_PROFILE


def _candidate_browser_paths(browser_preference: str) -> List[Path]:
    browser = resolve_browser_preference(browser_preference)
    env_browser_path = os.getenv("ZHIPIN_BROWSER_PATH", "").strip()
    candidates: List[Path] = []
    if env_browser_path:
        candidates.append(Path(env_browser_path))

    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        roaming_app_data = Path(os.environ.get("APPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", ""))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", ""))
        if browser == "edge":
            candidates.extend(
                [
                    local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                ]
            )
        elif browser == "chrome":
            candidates.extend(
                [
                    local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
                    program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
                    program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                ]
            )
        elif browser == "firefox":
            candidates.extend(
                [
                    program_files / "Mozilla Firefox" / "firefox.exe",
                    program_files_x86 / "Mozilla Firefox" / "firefox.exe",
                    local_app_data / "Mozilla Firefox" / "firefox.exe",
                    roaming_app_data / "Mozilla" / "Firefox" / "firefox.exe",
                ]
            )

    unique_candidates: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        path_text = str(path)
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        unique_candidates.append(path)
    return unique_candidates


def detect_browser_path(browser_preference: str = DEFAULT_BROWSER_PREFERENCE) -> str:
    for candidate in _candidate_browser_paths(browser_preference):
        if candidate.is_file():
            return str(candidate)
    return ""


def _browser_label(browser_preference: str) -> str:
    labels = {
        "edge": "Edge",
        "chrome": "Chrome",
        "firefox": "Firefox",
    }
    return labels.get(resolve_browser_preference(browser_preference), resolve_browser_preference(browser_preference) or "浏览器")


def _match_browser_profile(profile_name: str, desired_profile: str) -> bool:
    normalized_profile = str(profile_name or "").strip().lower()
    normalized_desired = str(desired_profile or "").strip().lower()
    if not normalized_desired:
        return True
    return normalized_profile == normalized_desired or normalized_desired in normalized_profile


def _iter_browser_cookie_files(browser_preference: str) -> List[tuple[str, Path]]:
    browser = resolve_browser_preference(browser_preference)
    items: List[tuple[str, Path]] = []
    if os.name != "nt":
        return items

    if browser == "edge":
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"
        if (root / "Default" / "Cookies").exists():
            items.append(("Default", root / "Default" / "Cookies"))
        for profile_dir in sorted(root.glob("Profile *")):
            cookie_file = profile_dir / "Cookies"
            if cookie_file.exists():
                items.append((profile_dir.name, cookie_file))
    elif browser == "chrome":
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
        if (root / "Default" / "Cookies").exists():
            items.append(("Default", root / "Default" / "Cookies"))
        for profile_dir in sorted(root.glob("Profile *")):
            cookie_file = profile_dir / "Cookies"
            if cookie_file.exists():
                items.append((profile_dir.name, cookie_file))
    elif browser == "firefox":
        root = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        for profile_dir in sorted(root.glob("*")):
            cookie_file = profile_dir / "cookies.sqlite"
            if profile_dir.is_dir() and cookie_file.exists():
                items.append((profile_dir.name, cookie_file))
    return items


def _extract_cookie_map_from_jar(jar: Any) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for cookie in jar:
        domain = str(getattr(cookie, "domain", "") or "")
        if "zhipin.com" not in domain:
            continue
        name = str(getattr(cookie, "name", "") or "").strip()
        value = str(getattr(cookie, "value", "") or "").strip()
        if name and value:
            cookies[name] = value
    return cookies


def extract_browser_cookie_bundle(
    browser_preference: str = DEFAULT_BROWSER_PREFERENCE,
    browser_profile: str = DEFAULT_BROWSER_PROFILE,
) -> Dict[str, Any]:
    try:
        import browser_cookie3 as bc3
    except ImportError:
        return {
            "cookie": "",
            "browser": resolve_browser_preference(browser_preference),
            "profile": browser_profile,
            "message": "当前环境未安装 browser_cookie3，无法从本地浏览器资料提取 Cookie。",
        }

    browser = resolve_browser_preference(browser_preference)
    extractor_map = {
        "edge": getattr(bc3, "edge", None),
        "chrome": getattr(bc3, "chrome", None),
        "firefox": getattr(bc3, "firefox", None),
    }
    extractor = extractor_map.get(browser)
    if extractor is None:
        return {
            "cookie": "",
            "browser": browser,
            "profile": browser_profile,
            "message": f"当前浏览器 {browser} 暂不支持本地 Cookie 提取。",
        }

    candidates = _iter_browser_cookie_files(browser)
    if candidates:
        preferred = [item for item in candidates if _match_browser_profile(item[0], browser_profile)]
        ordered = preferred + [item for item in candidates if item not in preferred]
        for profile_name, cookie_file in ordered:
            try:
                jar = extractor(cookie_file=str(cookie_file), domain_name=".zhipin.com")
            except Exception as exc:
                continue
            cookie_map = _extract_cookie_map_from_jar(jar)
            if cookie_map:
                return {
                    "cookie": _normalize_cookie_value(cookie_map),
                    "browser": browser,
                    "profile": profile_name,
                    "message": f"已从 {browser} 的 {profile_name} 提取到本地 Cookie。",
                }

    try:
        jar = extractor(domain_name=".zhipin.com")
        cookie_map = _extract_cookie_map_from_jar(jar)
        if cookie_map:
            return {
                "cookie": _normalize_cookie_value(cookie_map),
                "browser": browser,
                "profile": browser_profile,
                "message": f"已从 {browser} 默认资料提取到本地 Cookie。",
            }
    except Exception as exc:
        return {
            "cookie": "",
            "browser": browser,
            "profile": browser_profile,
            "message": f"本地 Cookie 提取失败: {exc}",
        }

    return {
        "cookie": "",
        "browser": browser,
        "profile": browser_profile,
        "message": f"未在 {browser} 的 {browser_profile} 中找到 zhipin.com Cookie。",
    }


def launch_visible_browser_for_login(
    query: str,
    city: str,
    browser_preference: str = DEFAULT_BROWSER_PREFERENCE,
    browser_profile: str = DEFAULT_BROWSER_PROFILE,
) -> Dict[str, Any]:
    browser = resolve_browser_preference(browser_preference)
    browser_path = detect_browser_path(browser)
    browser_label = _browser_label(browser)
    home_url = "https://www.zhipin.com/"
    search_url = f"https://www.zhipin.com/web/geek/job?query={query}&city={city}"
    if not browser_path:
        return {
            "launched": False,
            "browser": browser,
            "profile": browser_profile,
            "message": f"未找到 {browser_label} 可执行文件，无法自动拉起登录页。",
        }

    args = [browser_path]
    if browser == "edge":
        args.append(f"--profile-directory={resolve_browser_profile(browser_profile)}")
        args.extend([home_url, search_url])
    elif browser == "firefox":
        args.extend(["-P", resolve_browser_profile(browser_profile), "-new-tab", home_url, "-new-tab", search_url])
    else:
        args.extend([home_url, search_url])

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {
            "launched": True,
            "browser": browser,
            "profile": browser_profile,
            "message": f"已尝试拉起 {browser_label} 的 {browser_profile}，并打开 Boss 首页与搜索页做登录预热。",
        }
    except Exception as exc:
        return {
            "launched": False,
            "browser": browser,
            "profile": browser_profile,
            "message": f"自动拉起 {browser_label} 失败: {exc}",
        }


def build_headers(local: Dict[str, str], query: str, city: str) -> Dict[str, str]:
    cookie = os.getenv("ZHIPIN_COOKIE", local.get("cookie", "")).strip()
    zp_token = os.getenv("ZHIPIN_ZP_TOKEN", local.get("zp_token", "")).strip()
    token = os.getenv("ZHIPIN_TOKEN", local.get("token", "")).strip()

    encoded_query = quote(query, safe="")
    encoded_city = quote(city, safe="")

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.zhipin.com/web/geek/jobs?query={encoded_query}&city={encoded_city}",
    }

    if cookie:
        headers["Cookie"] = cookie
    if zp_token:
        headers["zp_token"] = zp_token
    if token:
        headers["token"] = token

    return headers


def _normalize_cookie_value(cookies: Any) -> str:
    if isinstance(cookies, str):
        return cookies.strip()

    parts: List[str] = []
    if isinstance(cookies, dict):
        for key, value in cookies.items():
            if key and value is not None:
                parts.append(f"{key}={value}")
        return "; ".join(parts)

    if isinstance(cookies, list):
        for item in cookies:
            if isinstance(item, dict):
                name = item.get("name") or item.get("Name")
                value = item.get("value") or item.get("Value")
                if name and value is not None:
                    parts.append(f"{name}={value}")
        return "; ".join(parts)

    return ""


def _parse_cookie_string(cookie_value: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for chunk in cookie_value.split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def merge_cookie_strings(base_cookie: str, fresh_cookie: str) -> str:
    merged = _parse_cookie_string(base_cookie)
    merged.update(_parse_cookie_string(fresh_cookie))
    return "; ".join(f"{key}={value}" for key, value in merged.items())


def missing_required_cookie_keys(cookie_value: str) -> List[str]:
    cookie_map = _parse_cookie_string(cookie_value)
    return [key for key in sorted(REQUIRED_COOKIE_KEYS) if not cookie_map.get(key)]


def validate_persisted_cookie(cookie_value: str) -> None:
    missing = missing_required_cookie_keys(cookie_value)
    if missing:
        raise PersistedCookieError(f"持久化 cookie 不完整，缺少: {', '.join(missing)}。请先运行 prepare_cookie 重新补全。")


def persist_cookie_bundle(cookie_value: str, runtime_mode: str = DEFAULT_RUNTIME_MODE) -> None:
    validate_persisted_cookie(cookie_value)
    save_local_secrets(
        {
            "cookie": cookie_value,
            "cookie_refreshed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cookie_runtime_mode": runtime_mode,
        }
    )


class RequestPacer:
    def __init__(self, base_delay: float = 1.2):
        self.base_delay = base_delay
        self.last_request_time = 0.0
        self.recent_request_times: deque[float] = deque(maxlen=12)
        self.rate_limit_count = 0

    def wait(
        self,
        *,
        should_stop_callback: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        **context: Any,
    ) -> None:
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.base_delay:
            jitter = max(0.0, random.gauss(0.35, 0.15))
            if random.random() < 0.05:
                jitter += random.uniform(1.5, 3.5)
            sleep_for = self.base_delay - elapsed + jitter
            safe_sleep(sleep_for, sleep_for, "request pacing", should_stop_callback=should_stop_callback, progress_callback=progress_callback, **context)

        penalty = self._burst_penalty_delay()
        if penalty > 0:
            safe_sleep(penalty, penalty, "burst cooldown", should_stop_callback=should_stop_callback, progress_callback=progress_callback, **context)

    def mark(self) -> None:
        now = time.time()
        self.last_request_time = now
        self.recent_request_times.append(now)

    def _burst_penalty_delay(self) -> float:
        now = time.time()
        recent_15s = sum(1 for ts in self.recent_request_times if now - ts <= 15)
        recent_45s = sum(1 for ts in self.recent_request_times if now - ts <= 45)
        if recent_45s >= 6:
            return random.uniform(4.0, 7.0)
        if recent_15s >= 3:
            return random.uniform(1.2, 2.8)
        return 0.0

    def rate_limit_backoff(self) -> float:
        self.rate_limit_count += 1
        return min(60.0, 10.0 * (2 ** (self.rate_limit_count - 1)))

    def reset_rate_limit(self) -> None:
        self.rate_limit_count = 0


def _build_browser_options(
    browser_preference: str = DEFAULT_BROWSER_PREFERENCE,
    browser_profile: str = DEFAULT_BROWSER_PROFILE,
    use_system_profile: Optional[bool] = None,
) -> Optional["ChromiumOptions"]:
    if ChromiumOptions is None:
        return None

    options = ChromiumOptions()
    options.auto_port(True)
    browser_path = detect_browser_path(browser_preference)
    if use_system_profile is None:
        use_system_profile = os.getenv("ZHIPIN_USE_SYSTEM_PROFILE", "true").strip().lower() not in {"0", "false", "no"}
    if browser_path:
        options.set_browser_path(browser_path)
    # 优先复用系统浏览器资料，避免用户在 Edge 已登录但保存 Cookie 时又拉起一个全新未登录实例。
    if use_system_profile:
        options.use_system_user_path(True)
        options.set_user(resolve_browser_profile(browser_profile))
    else:
        options.set_user_data_path(tempfile.mkdtemp(prefix="zhipin_bootstrap_"))
        options.set_user(resolve_browser_profile(browser_profile))
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument("--disable-gpu")
    options.set_argument("--no-proxy-server")
    options.set_argument("--window-size=1280,900")
    return options


def bootstrap_cookie_via_browser(
    query: str,
    city: str,
    warmup_seconds: float = 6.0,
    manual_wait_seconds: float = 0.0,
    browser_preference: str = DEFAULT_BROWSER_PREFERENCE,
    browser_profile: str = DEFAULT_BROWSER_PROFILE,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> str:
    if ChromiumPage is None:
        print("Browser bootstrap skipped: DrissionPage not installed")
        return ""

    resolved_browser = resolve_browser_preference(browser_preference)
    resolved_profile = resolve_browser_profile(browser_profile)
    browser_label = resolved_browser.capitalize()

    def _attempt_bootstrap(*, use_system_profile: bool) -> str:
        options = _build_browser_options(resolved_browser, resolved_profile, use_system_profile=use_system_profile)
        if options is None:
            return ""

        try:
            page = ChromiumPage(options)
        except Exception as exc:
            message = str(exc).strip()
            mode_label = "系统资料" if use_system_profile else "临时资料"
            print(f"Browser bootstrap failed to start {browser_label} ({mode_label}): {message or exc.__class__.__name__}")
            return ""

        try:
            home_url = "https://www.zhipin.com/"
            search_url = f"https://www.zhipin.com/web/geek/job?query={query}&city={city}"

            print(f"Bootstrapping browser session with {resolved_browser} / profile {resolved_profile} / {'system' if use_system_profile else 'fresh'}...")
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city=city)
            page.get(home_url)
            safe_sleep(3, 3, "homepage warmup", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city)
            ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city=city)
            page.get(search_url)
            emit_progress(progress_callback, "已打开 Boss 页面，等待登录完成后自动检测 Cookie", query=query, city=city)
            safe_sleep(warmup_seconds, warmup_seconds, "search warmup", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city)

            interactive_deadline = time.time() + max(0.0, manual_wait_seconds)
            prompted_manual_step = False
            while True:
                ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city=city)
                current_url = page.url or ""
                cookies = page.cookies(all_domains=True, all_info=False)
                cookie_value = _normalize_cookie_value(cookies)
                blocked = "verify" in current_url or "passport" in current_url
                if "__zp_stoken__" in cookie_value and not blocked:
                    print("Browser bootstrap success: got __zp_stoken__")
                    return cookie_value
                if time.time() < interactive_deadline:
                    if not prompted_manual_step:
                        prompted_manual_step = True
                        if blocked:
                            message = f"检测到登录/验证页，请在 {resolved_browser} 的 {resolved_profile} 资料页中手动完成，最长等待 {int(manual_wait_seconds)} 秒"
                        else:
                            message = f"已打开 Boss 页面，请在 {resolved_browser} 的 {resolved_profile} 资料页中完成登录，系统会在 {int(manual_wait_seconds)} 秒后自动检测并保存 Cookie"
                        print(message)
                        emit_progress(progress_callback, message, query=query, city=city)
                    time.sleep(1)
                    continue
                if blocked:
                    print(f"Browser bootstrap blocked at: {current_url}")
                    return ""
                print("Browser bootstrap finished, but __zp_stoken__ missing")
                return cookie_value
        except CrawlCancelledError:
            raise
        except Exception as exc:
            print(f"Browser bootstrap failed: {exc}")
            return ""
        finally:
            try:
                page.quit()
            except Exception:
                pass

    cookie_value = _attempt_bootstrap(use_system_profile=True)
    if cookie_value:
        return cookie_value

    emit_progress(
        progress_callback,
        f"Boss 接口预热：{browser_label} / {resolved_profile} 的系统资料预热失败，回退到临时资料重试一次。若系统 Edge 正在运行，建议先关闭后再重试。",
        query=query,
        city=city,
        browser=resolved_browser,
        browser_profile=resolved_profile,
    )
    return _attempt_bootstrap(use_system_profile=False)


def safe_sleep(
    min_seconds: float,
    max_seconds: float,
    reason: str,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    **context: Any,
) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    print(f"Sleep {delay:.1f}s: {reason}")
    remaining = delay
    while remaining > 0:
        ensure_not_cancelled(should_stop_callback, progress_callback, **context)
        step = min(0.5, remaining)
        time.sleep(step)
        remaining -= step


def find_job_list(node: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(node, dict):
        for key in ("jobList", "list", "jobs"):
            value = node.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value

        for value in node.values():
            result = find_job_list(value)
            if result:
                return result

    if isinstance(node, list):
        if node and isinstance(node[0], dict) and (
            "jobName" in node[0] or "salaryDesc" in node[0] or "jobId" in node[0]
        ):
            return node
        for value in node:
            result = find_job_list(value)
            if result:
                return result

    return None


def pick_text(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float)):
            return str(value)
    return ""


def normalize_job(item: Dict[str, Any]) -> Dict[str, str]:
    brand = item.get("brandName")
    if not brand and isinstance(item.get("brand"), dict):
        brand = pick_text(item["brand"], "brandName", "name")

    city = item.get("cityName")
    if not city and isinstance(item.get("city"), dict):
        city = pick_text(item["city"], "name", "cityName")

    area = item.get("areaDistrict")
    if not area and isinstance(item.get("areaDistrict"), dict):
        area = pick_text(item["areaDistrict"], "name")

    return {
        "job_name": pick_text(item, "jobName", "title", "positionName"),
        "salary": pick_text(item, "salaryDesc", "salary"),
        "city": str(city or ""),
        "area": str(area or ""),
        "experience": pick_text(item, "jobExperience", "experienceName"),
        "degree": pick_text(item, "jobDegree", "degreeName"),
        "brand": str(brand or ""),
        "brand_scale": pick_text(item, "brandScaleName", "brandScale"),
        "brand_stage": pick_text(item, "brandStageName", "brandStage"),
        "job_type": pick_text(item, "jobType", "jobTypeDesc"),
        "encrypt_job_id": pick_text(item, "encryptJobId", "securityId", "jobId"),
        "source_url": _build_job_url(item),
    }


def _build_job_url(item: Dict[str, Any]) -> str:
    """根据 encryptJobId 和 lid 构造 Boss 直聘职位详情页 URL。"""
    eid = pick_text(item, "encryptJobId", "securityId")
    lid = pick_text(item, "lid")
    if eid:
        url = f"https://www.zhipin.com/job_detail/{eid}.html"
        if lid:
            url += f"?lid={lid}"
        return url
    return ""


def fetch_one_page(
    session: requests.Session,
    headers: Dict[str, str],
    city: str,
    query: str,
    page: int,
    page_size: int,
    verify: Union[bool, str],
) -> Dict[str, Any]:
    params = {
        "scene": "1",
        "query": query,
        "city": city,
        "page": str(page),
        "pageSize": str(page_size),
        "_": str(int(time.time() * 1000)),
    }

    response = session.get(API_URL, headers=headers, params=params, timeout=20, verify=verify)
    response.raise_for_status()

    text = response.content.decode("utf-8", errors="replace")
    data = json.loads(text)
    return data


def build_local_context(local: Dict[str, str], cookie_value: str) -> Dict[str, str]:
    local_with_cookie = dict(local)
    if cookie_value:
        local_with_cookie["cookie"] = cookie_value
    return local_with_cookie


def probe_persisted_cookie(
    query: str = "Java",
    city: str = "101010100",
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
) -> Dict[str, Any]:
    local = load_local_secrets()
    cookie_value = local.get("cookie", "")
    missing = missing_required_cookie_keys(cookie_value)
    cookie_present = bool(cookie_value.strip())
    result: Dict[str, Any] = {
        "cookie_present": cookie_present,
        "cookie_valid": False,
        "missing_keys": missing,
        "cookie_refreshed_at": str(local.get("cookie_refreshed_at", "") or ""),
        "cookie_runtime_mode": str(local.get("cookie_runtime_mode", "") or ""),
        "validation_mode": "api_probe",
        "probe_code": "",
        "probe_message": "",
        "runtime_mode": runtime_mode,
        "query": query,
        "city": city,
    }
    if not cookie_present:
        result["message"] = "当前还没有 Boss Cookie"
        return result
    if missing:
        result["message"] = f"Boss Cookie 不完整，缺少: {', '.join(missing)}"
        return result

    verify = load_ssl_options(local)
    if verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        with requests.Session() as session:
            headers = build_headers(build_local_context(local, cookie_value), query, city)
            data = fetch_one_page(session, headers, city, query, 1, 1, verify)
        probe_code = str(data.get("code", ""))
        probe_message = str(data.get("message", "") or "")
        result["probe_code"] = probe_code
        result["probe_message"] = probe_message
        if probe_code == "0":
            result["cookie_valid"] = True
            result["message"] = "Boss Cookie 可用"
            return result
        if probe_code in RISK_CONTROL_CODES:
            result["message"] = "Boss Cookie 已失效或命中校验，需重新登录后保存"
            return result
        result["message"] = probe_message or f"Boss Cookie 校验失败，code={probe_code or 'unknown'}"
        return result
    except requests.RequestException as exc:
        result["validation_mode"] = "api_probe_request_exception"
        result["message"] = f"Boss Cookie 校验请求失败: {exc}"
        result["probe_message"] = str(exc)
        return result
    except Exception as exc:
        result["validation_mode"] = "api_probe_exception"
        result["message"] = f"Boss Cookie 校验异常: {exc}"
        result["probe_message"] = str(exc)
        return result


def prepare_persisted_cookie(
    query: str,
    city: str,
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
    browser_preference: str = DEFAULT_BROWSER_PREFERENCE,
    browser_profile: str = DEFAULT_BROWSER_PROFILE,
    login_wait_seconds: float = DEFAULT_COOKIE_LOGIN_WAIT_SECONDS,
) -> str:
    local = load_local_secrets()
    browser = resolve_browser_preference(browser_preference)
    launch_result = launch_visible_browser_for_login(
        query=query,
        city=city,
        browser_preference=browser,
        browser_profile=browser_profile,
    )
    print(launch_result.get("message", ""))
    wait_seconds = max(0.0, float(login_wait_seconds or DEFAULT_COOKIE_LOGIN_WAIT_SECONDS))
    if wait_seconds > 0:
        print(f"Waiting {wait_seconds:.0f}s for manual login...")
        time.sleep(wait_seconds)

    extracted = extract_browser_cookie_bundle(browser_preference=browser, browser_profile=browser_profile)
    browser_cookie = str(extracted.get("cookie", "") or "").strip()
    if browser_cookie:
        merged_cookie = merge_cookie_strings(local.get("cookie", ""), browser_cookie)
        try:
            persist_cookie_bundle(merged_cookie, runtime_mode=runtime_mode)
            return merged_cookie
        except PersistedCookieError:
            pass

    extraction_message = str(extracted.get("message", "") or "").strip()
    fallback_cookie = bootstrap_cookie_via_browser(
        query=query,
        city=city,
        warmup_seconds=4.0,
        manual_wait_seconds=min(max(wait_seconds, 0.0), 20.0),
        browser_preference=browser,
        browser_profile=browser_profile,
    ).strip()
    if fallback_cookie:
        merged_cookie = merge_cookie_strings(local.get("cookie", ""), fallback_cookie)
        try:
            persist_cookie_bundle(merged_cookie, runtime_mode=runtime_mode)
            return merged_cookie
        except PersistedCookieError:
            extraction_message = extraction_message or "浏览器活动页已返回 Cookie，但关键字段仍不完整。"

    browser_label = _browser_label(browser)
    raise PersistedCookieError(
        extraction_message
        or f"未能从 {browser_label} 的 {browser_profile} 获取完整 Boss Cookie，请确认已在该浏览器访问 Boss 页面并完成登录。"
    )


def crawl_jobs_with_context(
    session: requests.Session,
    local_with_cookie: Dict[str, str],
    query: str,
    city: str,
    max_pages: int,
    page_size: int,
    verify: Union[bool, str],
    use_browser_bootstrap: bool,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
    request_pacer: Optional[RequestPacer] = None,
) -> tuple[List[Dict[str, str]], Dict[str, str], Dict[str, Any]]:
    ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city=city)
    headers = build_headers(local_with_cookie, query, city)
    pacer = request_pacer or RequestPacer()

    emit_progress(progress_callback, "开始接口抓取", query=query, city=city)

    print("Header keys present:")
    print(f"- Cookie: {'Cookie' in headers}")
    print(f"- zp_token: {'zp_token' in headers}")
    print(f"- token: {'token' in headers}")
    print(f"- SSL verify setting: {verify}")

    results: List[Dict[str, str]] = []
    refresh_attempts = 0
    pages_completed = 0
    request_failures = 0
    rate_limit_hits = 0
    risk_control_hits = 0
    cookie_refreshes = 0
    last_code = "0"
    stop_reason = "target_pages_reached"

    for page in range(1, max_pages + 1):
        ensure_not_cancelled(should_stop_callback, progress_callback, query=query, city=city, page=page)
        emit_progress(progress_callback, f"抓取第 {page} 页", query=query, city=city, page=page)
        pacer.wait(should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city, page=page)
        try:
            data = fetch_one_page(session, headers, city, query, page, page_size, verify)
            pacer.mark()
        except requests.RequestException as exc:
            request_failures += 1
            print(f"Page {page}: request failed: {exc}")
            emit_progress(progress_callback, f"第 {page} 页请求失败: {exc}", query=query, city=city, page=page)
            if page == 1 and use_browser_bootstrap and refresh_attempts < 2:
                refresh_attempts += 1
                fresh_cookie = bootstrap_cookie_via_browser(
                    query,
                    city,
                    warmup_seconds=8,
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                if fresh_cookie:
                    cookie_refreshes += 1
                    merged_cookie = merge_cookie_strings(local_with_cookie.get("cookie", ""), fresh_cookie)
                    local_with_cookie = build_local_context(local_with_cookie, merged_cookie)
                    headers = build_headers(local_with_cookie, query, city)
                    safe_sleep(2.5, 4.0, "refresh session after request failure", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city, page=page)
                    data = fetch_one_page(session, headers, city, query, page, page_size, verify)
                    pacer.mark()
                else:
                    stop_reason = "request_failed"
                    break
            else:
                stop_reason = "request_failed"
                break

        code = data.get("code")
        last_code = str(code)
        message = data.get("message")
        print(f"Page {page}: code={code}, message={message}")

        if code != 0:
            if str(code) == "9":
                rate_limit_hits += 1
                cooldown = pacer.rate_limit_backoff()
                emit_progress(progress_callback, f"接口限流 code=9，冷却 {cooldown:.0f} 秒后重试", query=query, city=city, page=page)
                safe_sleep(cooldown, cooldown, "api rate-limit cooldown", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city, page=page)
                try:
                    data = fetch_one_page(session, headers, city, query, page, page_size, verify)
                    pacer.mark()
                except requests.RequestException as exc:
                    request_failures += 1
                    stop_reason = "rate_limit_retry_failed"
                    emit_progress(progress_callback, f"限流重试失败: {exc}", query=query, city=city, page=page)
                    break
                code = data.get("code")
                last_code = str(code)
                message = data.get("message")
                print(f"Retry page {page}: code={code}, message={message}")

            if str(code) in RISK_CONTROL_CODES and use_browser_bootstrap and refresh_attempts < 2:
                risk_control_hits += 1
                refresh_attempts += 1
                print(f"Risk control triggered (code={code}), refreshing browser cookie and retrying page {page}.")
                emit_progress(progress_callback, f"命中风控 code={code}，刷新 cookie 后重试", query=query, city=city, page=page)
                fresh_cookie = bootstrap_cookie_via_browser(
                    query,
                    city,
                    warmup_seconds=8,
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                )
                if not fresh_cookie:
                    print("Cookie refresh failed, stop current query.")
                    stop_reason = "cookie_refresh_failed"
                    emit_progress(progress_callback, "cookie 刷新失败，终止当前关键词", query=query, city=city, page=page)
                    break
                cookie_refreshes += 1
                merged_cookie = merge_cookie_strings(local_with_cookie.get("cookie", ""), fresh_cookie)
                local_with_cookie = build_local_context(local_with_cookie, merged_cookie)
                headers = build_headers(local_with_cookie, query, city)
                safe_sleep(8.0, 14.0, "cooldown after risk-control response", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city, page=page)
                try:
                    data = fetch_one_page(session, headers, city, query, page, page_size, verify)
                    pacer.mark()
                except requests.RequestException as exc:
                    request_failures += 1
                    stop_reason = "risk_control_retry_failed"
                    print(f"Retry failed on page {page}: {exc}")
                    break
                code = data.get("code")
                last_code = str(code)
                message = data.get("message")
                print(f"Retry page {page}: code={code}, message={message}")

            if code != 0:
                if str(code) in RISK_CONTROL_CODES and runtime_mode == "requests_only":
                    raise PersistedCookieError("持久化 cookie 已失效或命中校验，请先运行 prepare_cookie 重新补全后再执行 requests-only 模式。")
                if str(code) == "37":
                    print("Stop reason: risk control triggered (code=37, environment abnormal).")
                elif str(code) == "35":
                    print("Stop reason: verification page triggered (code=35).")
                else:
                    print(f"Stop on page {page}: business failed")
                stop_reason = f"code_{code}"
                emit_progress(progress_callback, f"第 {page} 页业务失败，code={code}", query=query, city=city, page=page)
                break

        refresh_attempts = 0
        pacer.reset_rate_limit()

        job_list_raw = find_job_list(data) or []
        page_jobs = [normalize_job(x) for x in job_list_raw if isinstance(x, dict)]

        if not page_jobs:
            print(f"Page {page}: no job data found, stop.")
            stop_reason = "empty"
            emit_progress(progress_callback, f"第 {page} 页无职位数据", query=query, city=city, page=page)
            break

        results.extend(page_jobs)
        pages_completed = page
        print(f"Page {page}: +{len(page_jobs)} jobs, total={len(results)}")
        emit_progress(progress_callback, f"第 {page} 页获取 {len(page_jobs)} 条，累计 {len(results)} 条", query=query, city=city, page=page)

        if page < max_pages:
            safe_sleep(1.8, 4.2, "normal request pacing", should_stop_callback=should_stop_callback, progress_callback=progress_callback, query=query, city=city, page=page)

    trace = {
        "query": query,
        "city_code": city,
        "status": stop_reason,
        "pages_completed": pages_completed,
        "fetched_count": len(results),
        "request_failures": request_failures,
        "rate_limit_hits": rate_limit_hits,
        "risk_control_hits": risk_control_hits,
        "cookie_refreshes": cookie_refreshes,
        "last_code": last_code,
        "runtime_mode": runtime_mode,
    }
    return results, local_with_cookie, trace


def crawl_jobs(
    query: str,
    city: str,
    max_pages: int = 3,
    page_size: int = 30,
    use_browser_bootstrap: bool = True,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
) -> List[Dict[str, str]]:
    local = load_local_secrets()
    verify = load_ssl_options(local)

    if verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    cookie_value = local.get("cookie", "")
    if runtime_mode == "requests_only":
        validate_persisted_cookie(cookie_value)
    elif use_browser_bootstrap:
        fresh_cookie = bootstrap_cookie_via_browser(
            query,
            city,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
        )
        if fresh_cookie:
            cookie_value = merge_cookie_strings(cookie_value, fresh_cookie)

    local_with_cookie = build_local_context(local, cookie_value)

    with requests.Session() as session:
        results, _, _ = crawl_jobs_with_context(
            session=session,
            local_with_cookie=local_with_cookie,
            query=query,
            city=city,
            max_pages=max_pages,
            page_size=page_size,
            verify=verify,
            use_browser_bootstrap=use_browser_bootstrap,
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
            runtime_mode=runtime_mode,
        )

    return results


def crawl_jobs_hybrid_batch(
    queries: List[str],
    cities: List[str],
    max_pages: int,
    page_size: int,
    output_dir: Path,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
) -> Dict[str, Any]:
    total_new = 0
    total_all = 0
    prepared_queries = [query.strip() for query in queries if query.strip()]
    boss_trace: List[Dict[str, Any]] = []
    local = load_local_secrets()
    verify = load_ssl_options(local)
    base_cookie = local.get("cookie", "")

    if runtime_mode == "requests_only":
        validate_persisted_cookie(base_cookie)

    for city_name in cities:
        ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name)
        city_name = city_name.strip()
        city_code = CITY_CODES.get(city_name, "")
        if not city_code:
            print(f"Unknown city: {city_name}, skip")
            continue

        if not prepared_queries:
            continue

        seed_query = prepared_queries[0]
        city_cookie = base_cookie
        if runtime_mode != "requests_only":
            emit_progress(progress_callback, f"城市 {city_name} 开始预热浏览器", city_name=city_name, city=city_code)
            fresh_cookie = bootstrap_cookie_via_browser(
                seed_query,
                city_code,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            if fresh_cookie:
                city_cookie = merge_cookie_strings(city_cookie, fresh_cookie)
        local_with_cookie = build_local_context(local, city_cookie)

        print(f"\n{'=' * 60}")
        print(f"City batch start: {city_name}({city_code}), queries={len(prepared_queries)}, max_pages={max_pages}")
        emit_progress(progress_callback, f"进入城市批次 {city_name}，共 {len(prepared_queries)} 个关键词", city_name=city_name, city=city_code)

        with requests.Session() as session:
            pacer = RequestPacer(base_delay=1.2 if runtime_mode == "requests_only" else 1.0)
            for q in prepared_queries:
                ensure_not_cancelled(should_stop_callback, progress_callback, city_name=city_name, query=q, city=city_code)
                print(f"\n-- Query: {q} @ {city_name}")
                emit_progress(progress_callback, f"开始抓取关键词 {q}", query=q, city_name=city_name, city=city_code)
                jobs, local_with_cookie, trace_meta = crawl_jobs_with_context(
                    session=session,
                    local_with_cookie=local_with_cookie,
                    query=q,
                    city=city_code,
                    max_pages=max_pages,
                    page_size=page_size,
                    verify=verify,
                    use_browser_bootstrap=(runtime_mode != "requests_only"),
                    progress_callback=progress_callback,
                    should_stop_callback=should_stop_callback,
                    runtime_mode=runtime_mode,
                    request_pacer=pacer,
                )
                print(f"Got {len(jobs)} jobs")
                emit_progress(progress_callback, f"关键词 {q} 抓取完成，共 {len(jobs)} 条", query=q, city_name=city_name, city=city_code)

                trace_entry: Dict[str, Any] = {
                    "query": q,
                    "location_name": city_name,
                    "city_code": city_code,
                    **trace_meta,
                    "new_count": 0,
                    "updated_count": 0,
                }

                if jobs:
                    save_results(output_dir, q, city_code, jobs)
                    stats = save_to_database(jobs, source_code="boss")
                    total_new += stats["new"]
                    total_all += len(jobs)
                    trace_entry["new_count"] = int(stats["new"])
                    trace_entry["updated_count"] = int(stats["updated"])
                    print(f"DB: new={stats['new']}, updated={stats['updated']}, unchanged={stats['unchanged']}")
                    emit_progress(
                        progress_callback,
                        f"关键词 {q} 已写库：新增 {stats['new']}，更新 {stats['updated']}，未变 {stats['unchanged']}",
                        query=q,
                        city_name=city_name,
                        city=city_code,
                    )

                boss_trace.append(trace_entry)

                safe_sleep(4.0, 8.0, "same-city query pacing", should_stop_callback=should_stop_callback, progress_callback=progress_callback, city_name=city_name, query=q, city=city_code)

            safe_sleep(12.0, 22.0, "cooldown between cities", should_stop_callback=should_stop_callback, progress_callback=progress_callback, city_name=city_name, city=city_code)
        emit_progress(progress_callback, f"城市 {city_name} 批次完成", city_name=city_name, city=city_code)

    print(f"\n{'=' * 60}")
    print(f"Hybrid batch done! Total fetched={total_all}, new to DB={total_new}")
    emit_progress(progress_callback, f"增量批次完成：抓取 {total_all} 条，新增 {total_new} 条")
    return {
        "total_fetched": total_all,
        "new_to_db": total_new,
        "cities": len(cities),
        "queries": len(prepared_queries),
        "runtime_mode": runtime_mode,
        "boss_summary": {
            "trace_count": len(boss_trace),
            "risk_control_hits": sum(int(item.get("risk_control_hits") or 0) for item in boss_trace),
            "rate_limit_hits": sum(int(item.get("rate_limit_hits") or 0) for item in boss_trace),
            "request_failures": sum(int(item.get("request_failures") or 0) for item in boss_trace),
            "cookie_refreshes": sum(int(item.get("cookie_refreshes") or 0) for item in boss_trace),
            "runtime_mode": runtime_mode,
        },
        "boss_trace": boss_trace,
    }


def run_incremental_update(
    queries: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    max_pages: int = 2,
    page_size: int = 30,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_stop_callback: Optional[Callable[[], bool]] = None,
    runtime_mode: str = DEFAULT_RUNTIME_MODE,
) -> Dict[str, Any]:
    actual_queries = queries or ["Java", "Python", "前端", "测试"]
    actual_cities = cities or ["青岛", "济南", "北京", "上海"]
    actual_output_dir = output_dir or DEFAULT_OUTPUT_DIR
    return crawl_jobs_hybrid_batch(
        actual_queries,
        actual_cities,
        max_pages,
        page_size,
        actual_output_dir,
        progress_callback=progress_callback,
        should_stop_callback=should_stop_callback,
        runtime_mode=runtime_mode,
    )


def save_results(base_dir: Path, query: str, city: str, jobs: List[Dict[str, str]]) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"joblist_{query}_{city}".replace(" ", "_")
    json_path = base_dir / f"{base_name}.json"
    csv_path = base_dir / f"{base_name}.csv"

    json_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "job_name",
        "salary",
        "city",
        "area",
        "experience",
        "degree",
        "brand",
        "brand_scale",
        "brand_stage",
        "job_type",
        "encrypt_job_id",
        "source_url",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)

    print("=" * 60)
    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV : {csv_path}")


def _compute_unique_hash(source_code: str, company: str, title: str, city: str) -> str:
    raw = f"{source_code}|{company}|{title}|{city}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compute_content_hash(title: str, salary: str) -> str:
    raw = f"{title}|{salary}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def save_to_database(jobs: List[Dict[str, str]], source_code: str = "boss") -> Dict[str, int]:
    """将爬取结果同步到 SQLite 数据库，去重 + 更新检测 + 自动生成通知。"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 确保表结构存在
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

    stats: Dict[str, int] = {"new": 0, "updated": 0, "unchanged": 0}

    for item in jobs:
        title = item.get("job_name", "")
        company = item.get("brand", "")
        city = item.get("city", "")

        if not title or not company:
            continue

        u_hash = _compute_unique_hash(source_code, company, title, city)
        c_hash = _compute_content_hash(title, item.get("salary", ""))

        existing = conn.execute(
            "SELECT id, content_hash FROM jobs WHERE unique_hash = ?",
            (u_hash,),
        ).fetchone()

        if existing is None:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    source_job_id, title, company_name, city_name, district_name,
                    salary_text, degree_text, experience_text, brand_scale, brand_stage,
                    job_type, source_url, unique_hash, content_hash, source_code, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    item.get("encrypt_job_id", ""),
                    title,
                    company,
                    city,
                    item.get("area", ""),
                    item.get("salary", ""),
                    item.get("degree", ""),
                    item.get("experience", ""),
                    item.get("brand_scale", ""),
                    item.get("brand_stage", ""),
                    item.get("job_type", ""),
                    item.get("source_url", ""),
                    u_hash,
                    c_hash,
                    source_code,
                ),
            )
            if cursor.rowcount > 0:
                stats["new"] += 1
                conn.execute(
                    """
                    INSERT INTO notifications (notification_type, title, content, related_job_id)
                    VALUES ('new_job', ?, ?, ?)
                    """,
                    ("新职位发现", f"{company} 发布了 {title}（{city}）", cursor.lastrowid),
                )

        elif existing["content_hash"] != c_hash:
            conn.execute(
                """
                UPDATE jobs SET
                    salary_text = ?, degree_text = ?, experience_text = ?,
                    brand_scale = ?, brand_stage = ?, job_type = ?,
                    content_hash = ?, last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    item.get("salary", ""),
                    item.get("degree", ""),
                    item.get("experience", ""),
                    item.get("brand_scale", ""),
                    item.get("brand_stage", ""),
                    item.get("job_type", ""),
                    c_hash,
                    existing["id"],
                ),
            )
            stats["updated"] += 1
            conn.execute(
                """
                INSERT INTO notifications (notification_type, title, content, related_job_id)
                VALUES ('job_updated', ?, ?, ?)
                """,
                ("职位信息更新", f"{title}（{company}）信息已更新", existing["id"]),
            )

        else:
            conn.execute(
                "UPDATE jobs SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
            stats["unchanged"] += 1

    conn.commit()
    conn.close()
    return stats


# Boss 直聘城市编码
CITY_CODES: Dict[str, str] = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "青岛": "101120200",
    "济南": "101120100",
    "西安": "101110100",
    "天津": "101030100",
    "重庆": "101040100",
    "长沙": "101250100",
    "郑州": "101180100",
    "合肥": "101220100",
    "苏州": "101190400",
    "厦门": "101230200",
    "大连": "101070200",
    "全国": "100010000",
}


def main() -> None:
    configure_stdio_encoding()

    mode = os.getenv("ZHIPIN_MODE", "single")  # single / batch / prepare_cookie
    max_pages = int(os.getenv("ZHIPIN_MAX_PAGES", "3"))
    page_size = int(os.getenv("ZHIPIN_PAGE_SIZE", "30"))
    output_dir = Path(os.getenv("ZHIPIN_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    runtime_mode = os.getenv("ZHIPIN_RUNTIME_MODE", DEFAULT_RUNTIME_MODE).strip().lower() or DEFAULT_RUNTIME_MODE

    if mode == "prepare_cookie":
        query = os.getenv("ZHIPIN_QUERY", "Java")
        city = os.getenv("ZHIPIN_CITY", "101120200")
        prepare_persisted_cookie(query=query, city=city, runtime_mode=runtime_mode)
        local = load_local_secrets()
        print("Cookie prepared and saved.")
        print(f"Refreshed at: {local.get('cookie_refreshed_at', '')}")
        print(f"Runtime mode: {local.get('cookie_runtime_mode', runtime_mode)}")
        return

    if mode == "batch":
        queries = os.getenv("ZHIPIN_QUERIES", "Java,Python,前端,测试,产品经理,运维").split(",")
        cities = os.getenv("ZHIPIN_CITIES", "青岛,济南,北京,上海,杭州,深圳").split(",")

        crawl_jobs_hybrid_batch(queries, cities, max_pages, page_size, output_dir, runtime_mode=runtime_mode)

    else:
        query = os.getenv("ZHIPIN_QUERY", "Java")
        city = os.getenv("ZHIPIN_CITY", "101120200")
        use_browser_bootstrap = runtime_mode != "requests_only" and os.getenv("ZHIPIN_USE_BROWSER_BOOTSTRAP", "true").strip().lower() not in {"0", "false", "no"}

        print(f"Start crawl: query={query}, city={city}, max_pages={max_pages}, page_size={page_size}, runtime_mode={runtime_mode}")

        jobs = crawl_jobs(
            query=query,
            city=city,
            max_pages=max_pages,
            page_size=page_size,
            use_browser_bootstrap=use_browser_bootstrap,
            runtime_mode=runtime_mode,
        )
        print(f"Crawl done, total jobs={len(jobs)}")

        if jobs:
            save_results(output_dir, query, city, jobs)
            print("Sample rows:")
            for row in jobs[:5]:
                print(f"- {row['job_name']} | {row['salary']} | {row['brand']}")

            print("\nSyncing to database...")
            stats = save_to_database(jobs, source_code="boss")
            print(f"DB sync done: new={stats['new']}, updated={stats['updated']}, unchanged={stats['unchanged']}")


if __name__ == "__main__":
    main()
