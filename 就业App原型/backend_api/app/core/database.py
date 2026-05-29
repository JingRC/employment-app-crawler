import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.featured_seed_catalog import NIUKE_CAMPUS_SEEDS
from app.core.dxy_job_sync import DXY_JOB_ARTICLE_URL, DXY_JOB_CAMPUS_URL, DXY_JOB_FAIR_URL, DXY_JOB_HOME_URL, fetch_dxy_job_campus_featured_companies, fetch_dxy_job_campus_notice_featured_companies, fetch_dxy_job_career_news_featured_companies, fetch_dxy_job_fair_company_featured_companies, fetch_dxy_job_fair_featured_companies, fetch_dxy_job_homepage_featured_companies, fetch_dxy_job_notice_detail_meta, is_dxy_job_notice_detail_url
from app.core.job_sources import get_source_name
from app.core.niuke_campus_sync import NIUKE_CAMPUS_HOME_URL, NIUKE_CAMPUS_SCHEDULE_URL, _cleanup_schedule_company_name, _is_non_company_schedule_name, fetch_niuke_campus_featured_companies, fetch_niuke_campus_schedule_featured_companies
from app.core.yingjiesheng_sync import YINGJIESHENG_DEADLINE_URL, YINGJIESHENG_HOME_URL, fetch_yingjiesheng_deadline_featured_companies, fetch_yingjiesheng_homepage_featured_companies

CODE_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "jobs.db"
SAMPLE_JSON_PATH = CODE_ROOT / "提交" / "joblist_Java_101120200.json"
JOB_MARKET_ANALYTICS_CACHE_DIR = DATA_DIR / "cache"
JOB_MARKET_ANALYTICS_CACHE_TTL_SECONDS = 180
_JOB_MARKET_ANALYTICS_MEMORY_CACHE: dict[str, dict[str, Any]] = {}

FEATURED_BOARD_LABELS = {
    "featured_famous": "名企",
    "featured_soe": "央国企",
}

FEATURED_COMPANY_TYPE_LABELS = {
    "famous_enterprise": "名企",
    "central_soe": "央企",
    "local_soe": "地方国企",
    "state_owned_enterprise": "国企",
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

MANUAL_STATE_OWNED_SEEDS = (
    {"company_name": "国家电网", "company_type": "central_soe", "group_name": "电力能源央国企", "industry": "电力/能源", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.sgcc.com.cn/", "career_site_url": "https://zhaopin.sgcc.com.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "南方电网", "company_type": "central_soe", "group_name": "电力能源央国企", "industry": "电力/能源", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.csg.cn/", "career_site_url": "https://zhaopin.csg.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "国家能源集团", "company_type": "central_soe", "group_name": "电力能源央国企", "industry": "电力/能源", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.chnenergy.com.cn/", "career_site_url": "https://zhaopin.chnenergy.com.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "三峡集团", "company_type": "central_soe", "group_name": "电力能源央国企", "industry": "电力/能源", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.ctg.com.cn/", "career_site_url": "https://www.zhipin.com/dz/sxjt", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中广核", "company_type": "central_soe", "group_name": "电力能源央国企", "industry": "电力/能源", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cgnpc.com.cn/", "career_site_url": "https://job.cgnpc.com.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国移动", "company_type": "central_soe", "group_name": "通信运营商", "industry": "通信/运营商", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.chinamobile.com/", "career_site_url": "https://job.10086.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国联通", "company_type": "central_soe", "group_name": "通信运营商", "industry": "通信/运营商", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.chinaunicom.com.cn/", "career_site_url": "https://www.chinaunicom.com.cn/46/menu01/528/column06", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国电信", "company_type": "central_soe", "group_name": "通信运营商", "industry": "通信/运营商", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.chinatelecom.com.cn/", "career_site_url": "https://job.189.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国建筑", "company_type": "central_soe", "group_name": "基建交通央国企", "industry": "建筑/基建/交通", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cscec.com/", "career_site_url": "https://job.cscec.com/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国中铁", "company_type": "central_soe", "group_name": "基建交通央国企", "industry": "建筑/基建/交通", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.crecg.com/", "career_site_url": "https://www.crecg.com/web/rlzy65/rczp11/index.html", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国铁建", "company_type": "central_soe", "group_name": "基建交通央国企", "industry": "建筑/基建/交通", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.crcc.cn/", "career_site_url": "https://www.crcc.cn/col/col214/index.html", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国交建", "company_type": "central_soe", "group_name": "基建交通央国企", "industry": "建筑/基建/交通", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.ccccltd.cn/", "career_site_url": "http://zhaopin.ccccltd.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国电子", "company_type": "central_soe", "group_name": "军工电子央国企", "industry": "电子/军工", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cec.com.cn/", "career_site_url": "http://campus.cec.com.cn/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中国电科", "company_type": "central_soe", "group_name": "军工电子央国企", "industry": "电子/军工", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cetc.com.cn/", "career_site_url": "https://www.cetc.com.cn/zgdk/1593022/1646556/1646667/index.html", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中航工业", "company_type": "central_soe", "group_name": "军工电子央国企", "industry": "航空/军工", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.avic.com/", "career_site_url": "https://www.avic.com/sycd/rczp/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中船集团", "company_type": "central_soe", "group_name": "军工电子央国企", "industry": "船舶/军工", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cssc.net.cn/", "career_site_url": "http://www.cssc.net.cn/n9/n63/index.html", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "华润集团", "company_type": "central_soe", "group_name": "综合央国企", "industry": "综合集团", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.crc.com.cn/", "career_site_url": "https://runjob.crc.com.cn/#/complex/homepage?id=1769554545615040514", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "招商局集团", "company_type": "central_soe", "group_name": "综合央国企", "industry": "综合集团", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cmhk.com/", "career_site_url": "https://cmhk.zhiye.com/custom/index?hideMenu=1", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中粮集团", "company_type": "central_soe", "group_name": "综合央国企", "industry": "综合集团", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.cofco.com/", "career_site_url": "http://cofco-campus.zhaopin.com/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
    {"company_name": "中远海运", "company_type": "central_soe", "group_name": "综合央国企", "industry": "综合集团", "scale_text": "大型央企", "city_text": "全国", "official_site_url": "https://www.coscoshipping.com/", "career_site_url": "https://coscoshipping.iguopin.com/job/", "description_text": "央国企专题初始化种子目录，可结合国聘和官网招聘页继续跟进。"},
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

NOTIFICATION_ACTION_SOURCES = {
    "new_job": ("auto_crawl", "自动抓取"),
    "job_updated": ("auto_crawl", "自动抓取"),
    "company_new_job": ("subscription", "订阅提醒"),
    "job_closed": ("auto_detection", "自动检测"),
    "job_manual_verify": ("manual_verify", "手动复核"),
    "job_manual_restore": ("manual_restore", "手动恢复"),
    "job_batch_verify": ("batch_verify", "批量复核"),
    "job_batch_restore": ("batch_restore", "批量恢复"),
}

ACTION_SOURCE_NOTIFICATION_TYPES: dict[str, tuple[str, ...]] = {}
for _notification_type, (_action_source, _) in NOTIFICATION_ACTION_SOURCES.items():
    ACTION_SOURCE_NOTIFICATION_TYPES[_action_source] = ACTION_SOURCE_NOTIFICATION_TYPES.get(_action_source, tuple()) + (
        _notification_type,
    )

DEFAULT_JOB_STALE_HOURS = 72
_JOB_STALE_HOURS = DEFAULT_JOB_STALE_HOURS
EVENT_NOTIFICATION_DEDUPE_WINDOW_HOURS = 12
DEFAULT_OFFLINE_STRONG_CHECK_LIMIT = 5
DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS = 6.0
DEFAULT_SAFE_VERIFY_LIMIT = 12
DEFAULT_SAFE_VERIFY_TIMEOUT_SECONDS = 6.0
DEFAULT_SAFE_VERIFY_RECENT_ACTIVE_HOURS = 24 * 14
OFFLINE_INVALID_PAGE_KEYWORDS = (
    "职位不存在",
    "职位已下线",
    "岗位已下架",
    "岗位已关闭",
    "招聘结束",
    "页面不存在",
    "内容不存在",
    "已停止招聘",
    "已删除",
    "失效",
)


@contextmanager
def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _safe_connect()
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _safe_connect() -> sqlite3.Connection:
    """Connect to the database, removing the file if it is corrupt (e.g. LFS pointer)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.DatabaseError:
        conn.close()
        DB_PATH.unlink(missing_ok=True)
        return sqlite3.connect(DB_PATH)


def set_job_stale_hours(stale_after_hours: int | None) -> int:
    global _JOB_STALE_HOURS
    normalized = max(int(stale_after_hours or DEFAULT_JOB_STALE_HOURS), 1)
    _JOB_STALE_HOURS = normalized
    return _JOB_STALE_HOURS


def get_job_stale_hours() -> int:
    return int(_JOB_STALE_HOURS)


def _build_job_market_analytics_cache_key(
    status: str,
    top_n: int,
    focus_source_code: str | None,
    refresh_stale: bool = True,
) -> str:
    normalized_focus_source_code = (focus_source_code or "").strip().lower() or "none"
    refresh_mode = "refresh" if refresh_stale else "no_refresh"
    return f"{status}|{int(top_n)}|{normalized_focus_source_code}|{refresh_mode}"


def _get_jobs_db_fingerprint() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {
            "exists": False,
            "mtime_ns": 0,
            "size": 0,
        }
    stat_result = DB_PATH.stat()
    return {
        "exists": True,
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        "size": int(stat_result.st_size),
    }


def _get_job_market_analytics_cache_path(cache_key: str) -> Path:
    JOB_MARKET_ANALYTICS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
    return JOB_MARKET_ANALYTICS_CACHE_DIR / f"job_market_analytics_{filename}.json"


def _is_job_market_analytics_cache_entry_fresh(
    entry: dict[str, Any] | None,
    *,
    db_fingerprint: dict[str, Any],
    current_time: datetime,
    ttl_seconds: int,
) -> bool:
    if not isinstance(entry, dict):
        return False
    if dict(entry.get("db_fingerprint") or {}) != db_fingerprint:
        return False
    generated_at_text = str(entry.get("generated_at") or "").strip()
    if not generated_at_text:
        return False
    try:
        generated_at = datetime.fromisoformat(generated_at_text)
    except ValueError:
        return False
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    return (current_time - generated_at).total_seconds() <= max(int(ttl_seconds or 0), 0)


def _load_job_market_analytics_cache_entry(
    cache_key: str,
    *,
    db_fingerprint: dict[str, Any],
    current_time: datetime,
    ttl_seconds: int,
) -> dict[str, Any] | None:
    memory_entry = _JOB_MARKET_ANALYTICS_MEMORY_CACHE.get(cache_key)
    if _is_job_market_analytics_cache_entry_fresh(
        memory_entry,
        db_fingerprint=db_fingerprint,
        current_time=current_time,
        ttl_seconds=ttl_seconds,
    ):
        payload = memory_entry.get("payload")
        if isinstance(payload, dict):
            return payload
    elif memory_entry is not None:
        _JOB_MARKET_ANALYTICS_MEMORY_CACHE.pop(cache_key, None)

    cache_path = _get_job_market_analytics_cache_path(cache_key)
    if not cache_path.exists():
        return None
    try:
        disk_entry = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not _is_job_market_analytics_cache_entry_fresh(
        disk_entry,
        db_fingerprint=db_fingerprint,
        current_time=current_time,
        ttl_seconds=ttl_seconds,
    ):
        return None
    payload = disk_entry.get("payload")
    if not isinstance(payload, dict):
        return None
    _JOB_MARKET_ANALYTICS_MEMORY_CACHE[cache_key] = disk_entry
    return payload


def _store_job_market_analytics_cache_entry(
    cache_key: str,
    *,
    db_fingerprint: dict[str, Any],
    payload: dict[str, Any],
    current_time: datetime,
) -> None:
    entry = {
        "generated_at": current_time.isoformat(),
        "db_fingerprint": db_fingerprint,
        "payload": payload,
    }
    _JOB_MARKET_ANALYTICS_MEMORY_CACHE[cache_key] = entry
    cache_path = _get_job_market_analytics_cache_path(cache_key)
    try:
        cache_path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def get_featured_board_name(board_code: str) -> str:
    normalized = (board_code or "").strip().lower()
    return FEATURED_BOARD_LABELS.get(normalized, normalized or "未分组")


def get_featured_company_type_name(company_type: str) -> str:
    normalized = (company_type or "").strip().lower()
    return FEATURED_COMPANY_TYPE_LABELS.get(normalized, normalized or "未分类")


def _normalize_saved_search_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    raw_filters = filters or {}
    for key, value in raw_filters.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        if value is None:
            continue
        normalized_value = str(value).strip()
        if not normalized_value:
            continue
        normalized[normalized_key] = normalized_value
    return normalized


def _build_saved_search_unique_hash(keyword: str, city_name: str, filters: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "keyword": str(keyword or "").strip().lower(),
            "city_name": str(city_name or "").strip().lower(),
            "filters": _normalize_saved_search_filters(filters),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def get_notification_action_source(notification_type: str) -> tuple[str, str]:
    normalized = (notification_type or "").strip().lower()
    return NOTIFICATION_ACTION_SOURCES.get(normalized, (normalized or "unknown", "未知来源"))


def get_notification_types_for_action_source(action_source: str) -> tuple[str, ...]:
    normalized = (action_source or "").strip().lower()
    return ACTION_SOURCE_NOTIFICATION_TYPES.get(normalized, tuple())


def _normalize_featured_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def resolve_featured_company_links(company_name: str) -> dict[str, str]:
    normalized_company_name = _normalize_featured_text(company_name)
    if not normalized_company_name:
        return {
            "official_site_url": "",
            "career_site_url": "",
        }

    matched_item = _find_manual_famous_company_entry(normalized_company_name)
    if matched_item is not None:
        return {
            "official_site_url": str(matched_item.get("official_site_url") or ""),
            "career_site_url": str(matched_item.get("career_site_url") or ""),
        }

    return {
        "official_site_url": "",
        "career_site_url": "",
    }


def _find_manual_famous_company_entry(company_name: str) -> dict[str, Any] | None:
    normalized_company_name = _normalize_featured_text(company_name)
    if not normalized_company_name:
        return None

    for item in MANUAL_FAMOUS_COMPANY_LINKS:
        aliases = tuple(_normalize_featured_text(alias) for alias in item.get("aliases") or (item["company_name"],))
        if any(
            alias and (normalized_company_name == alias or normalized_company_name in alias or alias in normalized_company_name)
            for alias in aliases
        ):
            return item
    return None


def get_featured_company_aliases(company_name: str) -> list[str]:
    matched_item = _find_manual_famous_company_entry(company_name)
    if matched_item is None:
        return []

    aliases: list[str] = []
    for alias in matched_item.get("aliases") or ():
        normalized_alias = _normalize_featured_text(alias)
        if not normalized_alias:
            continue
        if re.fullmatch(r"[A-Za-z]+", normalized_alias) and len(normalized_alias) < 4:
            continue
        if normalized_alias not in aliases:
            aliases.append(normalized_alias)
    return aliases


def _build_featured_company_crawl_suggestions(
    company_name: str,
    *,
    board_code: str = "featured_famous",
    city_text: str = "",
) -> dict[str, list[str]]:
    suggested_queries: list[str] = []
    for candidate in [str(company_name or "").strip(), *get_featured_company_aliases(company_name)]:
        normalized_candidate = _normalize_featured_text(candidate)
        if not normalized_candidate:
            continue
        if normalized_candidate not in suggested_queries:
            suggested_queries.append(normalized_candidate)

    raw_city_parts = [part.strip() for part in str(city_text or "").split("/") if part.strip()]
    suggested_cities: list[str] = []
    if raw_city_parts:
        primary_city = raw_city_parts[1] if len(raw_city_parts) >= 2 else raw_city_parts[0]
        if primary_city and primary_city != "全国":
            suggested_cities.append(primary_city)

    suggested_sources = ["zhilian", "shixiseng"]
    if str(board_code or "").strip().lower() == "featured_soe":
        suggested_sources = ["guopin", "shixiseng"]

    return {
        "queries": suggested_queries[:5],
        "cities": suggested_cities[:2],
        "sources": suggested_sources,
    }


def infer_featured_company_bucket(
    *,
    company_name: str,
    industry: str = "",
    description_text: str = "",
    module_name: str = "",
    group_name: str = "",
) -> dict[str, str]:
    normalized_company_name = _normalize_featured_text(company_name)
    normalized_industry = _normalize_featured_text(industry)
    normalized_description = _normalize_featured_text(description_text)
    normalized_module_name = _normalize_featured_text(module_name)
    normalized_group_name = _normalize_featured_text(group_name)
    combined_text = " ".join(
        part for part in [normalized_company_name, normalized_industry, normalized_description, normalized_module_name, normalized_group_name] if part
    )

    if any(keyword in combined_text for keyword in STATE_OWNED_KEYWORDS):
        company_type = "state_owned_enterprise"
        if any(keyword in combined_text for keyword in ("央企", "国家电网", "南方电网", "国家能源集团", "三峡集团", "中广核", "中石油", "中石化", "中海油", "中国移动", "中国联通", "中国电信", "中国建筑", "中国中铁", "中国铁建", "中国交建", "中国中车", "中国电子", "中国电科", "航天科技", "航天科工", "中航工业", "中船集团", "华润", "招商局", "中粮", "中远海运", "中国能建", "中国电建")):
            company_type = "central_soe"
        elif any(keyword in combined_text for keyword in ("地方国企", "城投", "交投", "地铁集团", "文旅集团", "国资委")):
            company_type = "local_soe"

        resolved_group_name = "央国企目录"
        for keywords, candidate_group_name in STATE_OWNED_GROUP_RULES:
            if any(keyword in combined_text for keyword in keywords):
                resolved_group_name = candidate_group_name
                break
        return {
            "board_code": "featured_soe",
            "company_type": company_type,
            "group_name": resolved_group_name,
        }

    return {
        "board_code": "featured_famous",
        "company_type": "famous_enterprise",
        "group_name": normalized_group_name or (normalized_module_name or "校招名企"),
    }


def _seed_manual_state_owned_featured_companies(conn: sqlite3.Connection) -> None:
    for item in MANUAL_STATE_OWNED_SEEDS:
        company_name = str(item["company_name"])
        unique_hash = hashlib.sha256(f"manual_seed|featured_soe|{company_name}".encode("utf-8")).hexdigest()[:32]
        company_uuid = hashlib.sha256(f"manual_seed|{company_name}".encode("utf-8")).hexdigest()[:24]
        existing = conn.execute("SELECT id FROM featured_companies WHERE unique_hash = ?", (unique_hash,)).fetchone()
        payload = {
            "seed_kind": "state_owned_directory",
            "company_name": company_name,
            "company_type": item["company_type"],
            "group_name": item["group_name"],
        }
        if existing is None:
            conn.execute(
                """
                INSERT INTO featured_companies (
                    board_code, company_type, group_name, source_code, company_uuid,
                    company_name, city_text, industry, scale_text, module_name,
                    description_text, official_site_url, career_site_url, extra_json, unique_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "featured_soe",
                    item["company_type"],
                    item["group_name"],
                    "manual_seed",
                    company_uuid,
                    company_name,
                    item["city_text"],
                    item["industry"],
                    item["scale_text"],
                    "manual_seed_state_owned",
                    item["description_text"],
                    str(item.get("official_site_url") or ""),
                    str(item.get("career_site_url") or ""),
                    json.dumps(payload, ensure_ascii=False),
                    unique_hash,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE featured_companies
                SET board_code='featured_soe', company_type=?, group_name=?, source_code='manual_seed',
                    company_uuid=?, company_name=?, city_text=?, industry=?, scale_text=?, module_name='manual_seed_state_owned',
                    description_text=?, official_site_url=?, career_site_url=?, extra_json=?, last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    item["company_type"],
                    item["group_name"],
                    company_uuid,
                    company_name,
                    item["city_text"],
                    item["industry"],
                    item["scale_text"],
                    item["description_text"],
                    str(item.get("official_site_url") or ""),
                    str(item.get("career_site_url") or ""),
                    json.dumps(payload, ensure_ascii=False),
                    int(existing["id"]),
                ),
            )


def import_niuke_campus_featured_companies() -> dict[str, Any]:
    inserted = 0
    updated = 0
    unchanged = 0
    module_name = "niuke_campus_topic"
    board_code = "featured_famous"
    company_type = "famous_enterprise"
    live_sync_errors: list[str] = []

    homepage_items: list[dict[str, Any]] = []
    schedule_items: list[dict[str, Any]] = []
    try:
        homepage_items = fetch_niuke_campus_featured_companies()
    except Exception as exc:
        live_sync_errors.append("homepage: " + str(exc).splitlines()[0].strip())
    try:
        schedule_items = fetch_niuke_campus_schedule_featured_companies()
    except Exception as exc:
        live_sync_errors.append("schedule: " + str(exc).splitlines()[0].strip())

    def normalize_company_key(name: str) -> str:
        normalized = re.sub(r"\s+", "", str(name or "").strip().lower())
        for suffix in ("集团", "股份有限公司", "有限责任公司", "有限公司", "公司"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        return normalized

    def resolve_existing_key(items: dict[str, dict[str, Any]], company_name: str) -> str:
        normalized = normalize_company_key(company_name)
        if normalized in items:
            return normalized
        for existing_key in items.keys():
            if existing_key and normalized and (existing_key in normalized or normalized in existing_key):
                return existing_key
        return normalized

    def merge_niuke_item(existing_item: dict[str, Any], incoming_item: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing_item)
        for key, value in incoming_item.items():
            text = str(value or "").strip()
            if not text:
                continue
            if key == "company_name" and str(existing_item.get("company_name") or "").strip():
                continue
            if key == "group_name":
                existing_group = str(existing_item.get("group_name") or "").strip()
                if existing_group and existing_group not in {"牛客招聘动态", "牛客校招日程"} and text in {"牛客招聘动态", "牛客校招日程"}:
                    continue
            merged[key] = value
        return merged

    merged_items: dict[str, dict[str, Any]] = {}
    for item in NIUKE_CAMPUS_SEEDS:
        company_name = str(item.get("company_name") or "").strip()
        if not company_name:
            continue
        merged_items[normalize_company_key(company_name)] = dict(item)

    for item in [*homepage_items, *schedule_items]:
        company_name = str(item.get("company_name") or "").strip()
        if not company_name:
            continue
        dedupe_key = resolve_existing_key(merged_items, company_name)
        existing_item = dict(merged_items.get(dedupe_key) or {})
        merged_item = merge_niuke_item(existing_item, item)
        if not str(existing_item.get("company_name") or "").strip():
            merged_item["company_name"] = company_name
        if not str(merged_item.get("group_name") or "").strip():
            merged_item["group_name"] = "牛客招聘动态"
        merged_items[dedupe_key] = merged_item

    source_items = list(merged_items.values())

    with get_connection() as conn:
        for item in source_items:
            company_name = str(item.get("company_name") or "").strip()
            if not company_name:
                continue

            unique_hash = hashlib.sha256(f"niuke_campus|featured_famous|{company_name}".encode("utf-8")).hexdigest()[:32]
            company_uuid = hashlib.sha256(f"niuke_campus|{company_name}".encode("utf-8")).hexdigest()[:24]
            payload = {
                "seed_kind": "niuke_campus_topic",
                "source_platform": "nowcoder",
                "sync_mode": "live_plus_seed" if (homepage_items or schedule_items) else "seed_only",
                "company_name": company_name,
                "group_name": str(item.get("group_name") or ""),
                "source_url": str(item.get("source_url") or NIUKE_CAMPUS_HOME_URL),
                "source_page_url": str(item.get("source_page_url") or item.get("source_url") or NIUKE_CAMPUS_SCHEDULE_URL),
                "company_id": str(item.get("company_id") or ""),
                "entity_id": str(item.get("entity_id") or ""),
                "topic_source_kind": str(item.get("topic_source_kind") or "seed"),
                "recruitment_batch": str(item.get("recruitment_batch") or ""),
                "recruitment_stage": str(item.get("recruitment_stage") or ""),
                "collected_at_text": str(item.get("collected_at_text") or ""),
                "application_period_text": str(item.get("application_period_text") or ""),
                "apply_label": str(item.get("apply_label") or ""),
            }
            existing = conn.execute(
                "SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json FROM featured_companies WHERE unique_hash = ?",
                (unique_hash,),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """
                    SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json
                    FROM featured_companies
                    WHERE source_code = 'niuke_campus' AND module_name = ? AND company_name LIKE ?
                    ORDER BY LENGTH(company_name) ASC, id ASC
                    LIMIT 1
                    """,
                    (module_name, f"%{company_name}%"),
                ).fetchone()

            payload_text = json.dumps(payload, ensure_ascii=False)

            record_values = {
                "city_text": str(item.get("city_text") or ""),
                "industry": str(item.get("industry") or ""),
                "scale_text": str(item.get("scale_text") or ""),
                "description_text": str(item.get("description_text") or ""),
                "official_site_url": str(item.get("official_site_url") or ""),
                "career_site_url": str(item.get("career_site_url") or ""),
                "group_name": str(item.get("group_name") or "校招名企"),
            }

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO featured_companies (
                        board_code, company_type, group_name, source_code, company_uuid,
                        company_name, city_text, industry, scale_text, module_name,
                        description_text, official_site_url, career_site_url, extra_json, unique_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        "niuke_campus",
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                    ),
                )
                inserted += 1
                continue

            has_changed = any(
                str(existing[field_name] or "") != value
                for field_name, value in record_values.items()
            ) or str(existing["extra_json"] or "") != payload_text
            if has_changed:
                conn.execute(
                    """
                    UPDATE featured_companies
                    SET board_code=?, company_type=?, group_name=?, source_code='niuke_campus',
                        company_uuid=?, company_name=?, city_text=?, industry=?, scale_text=?, module_name=?,
                        description_text=?, official_site_url=?, career_site_url=?, extra_json=?, unique_hash=?, last_seen_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                        int(existing["id"]),
                    ),
                )
                updated += 1
            else:
                unchanged += 1

        normalized_company_names = _normalize_niuke_featured_company_names(conn)
        duplicate_rows_deleted = _compact_niuke_featured_company_duplicates(conn)
        conn.commit()

    return {
        "source_code": "niuke_campus",
        "board_code": board_code,
        "module_name": module_name,
        "total_seeds": len(source_items),
        "seed_count": len(NIUKE_CAMPUS_SEEDS),
        "live_cards": len(homepage_items) + len(schedule_items),
        "homepage_cards": len(homepage_items),
        "schedule_cards": len(schedule_items),
        "fallback_to_seed_only": not bool(homepage_items or schedule_items),
        "live_sync_error": " | ".join(live_sync_errors),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "normalized_company_names": normalized_company_names,
        "duplicate_rows_deleted": duplicate_rows_deleted,
    }


def import_yingjiesheng_featured_companies() -> dict[str, Any]:
    inserted = 0
    updated = 0
    unchanged = 0
    live_sync_errors: list[str] = []
    module_name = "yingjiesheng_topic"
    board_code = "featured_famous"
    company_type = "famous_enterprise"

    homepage_items: list[dict[str, Any]] = []
    deadline_items: list[dict[str, Any]] = []
    try:
        homepage_items = fetch_yingjiesheng_homepage_featured_companies()
    except Exception as exc:
        live_sync_errors.append("homepage: " + str(exc).splitlines()[0].strip())

    try:
        deadline_items = fetch_yingjiesheng_deadline_featured_companies()
    except Exception as exc:
        live_sync_errors.append("deadline: " + str(exc).splitlines()[0].strip())

    def normalize_company_key(name: str) -> str:
        normalized = re.sub(r"\s+", "", str(name or "").strip().lower())
        normalized = re.sub(r"\d+名$", "", normalized)
        for suffix in ("集团", "股份有限公司", "有限责任公司", "有限公司", "公司", "分行"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        return normalized

    def merge_topic_item(existing_item: dict[str, Any], incoming_item: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing_item)
        for key, value in incoming_item.items():
            text = str(value or "").strip()
            if not text:
                continue
            if key == "company_name" and str(existing_item.get("company_name") or "").strip():
                continue
            if key == "group_name":
                existing_group = str(existing_item.get("group_name") or "").strip()
                if existing_group and existing_group != text and existing_group == "应届生首页专题" and text == "应届生截止专题":
                    continue
            merged[key] = value
        return merged

    merged_items: dict[str, dict[str, Any]] = {}
    for item in [*homepage_items, *deadline_items]:
        company_name = str(item.get("company_name") or "").strip()
        if not company_name:
            continue
        dedupe_key = normalize_company_key(company_name)
        existing_item = dict(merged_items.get(dedupe_key) or {})
        merged_item = merge_topic_item(existing_item, item)
        if not str(existing_item.get("company_name") or "").strip():
            merged_item["company_name"] = company_name
        merged_items[dedupe_key] = merged_item

    with get_connection() as conn:
        for item in merged_items.values():
            company_name = str(item.get("company_name") or "").strip()
            if not company_name:
                continue

            unique_hash = hashlib.sha256(f"yingjiesheng|featured_famous|{company_name}".encode("utf-8")).hexdigest()[:32]
            company_uuid = hashlib.sha256(f"yingjiesheng|{company_name}".encode("utf-8")).hexdigest()[:24]
            payload = {
                "seed_kind": "yingjiesheng_topic",
                "source_platform": "yingjiesheng",
                "sync_mode": "homepage_plus_deadline" if (homepage_items and deadline_items) else "homepage_only" if homepage_items else "deadline_only" if deadline_items else "empty",
                "company_name": company_name,
                "group_name": str(item.get("group_name") or ""),
                "source_url": str(item.get("source_url") or YINGJIESHENG_HOME_URL),
                "source_page_url": str(item.get("source_page_url") or item.get("source_url") or YINGJIESHENG_HOME_URL),
                "topic_source_kind": str(item.get("topic_source_kind") or "homepage_topic"),
                "recruitment_batch": str(item.get("recruitment_batch") or ""),
                "recruitment_stage": str(item.get("recruitment_stage") or ""),
                "collected_at_text": str(item.get("collected_at_text") or ""),
                "application_period_text": str(item.get("application_period_text") or ""),
                "apply_label": str(item.get("apply_label") or ""),
            }
            payload_text = json.dumps(payload, ensure_ascii=False)
            existing = conn.execute(
                "SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json FROM featured_companies WHERE unique_hash = ?",
                (unique_hash,),
            ).fetchone()
            if existing is None:
                source_page_url = str(item.get("source_page_url") or item.get("source_url") or "").strip()
                if source_page_url:
                    existing = conn.execute(
                        """
                        SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json
                        FROM featured_companies
                        WHERE source_code = 'yingjiesheng' AND module_name = ? AND extra_json LIKE ?
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                        (module_name, f'%"source_page_url": "{source_page_url}"%'),
                    ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """
                    SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json
                    FROM featured_companies
                    WHERE source_code = 'yingjiesheng' AND module_name = ? AND company_name = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (module_name, company_name),
                ).fetchone()

            record_values = {
                "city_text": str(item.get("city_text") or ""),
                "industry": str(item.get("industry") or ""),
                "scale_text": str(item.get("scale_text") or ""),
                "description_text": str(item.get("description_text") or ""),
                "official_site_url": str(item.get("official_site_url") or ""),
                "career_site_url": str(item.get("career_site_url") or ""),
                "group_name": str(item.get("group_name") or "应届生首页专题"),
            }

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO featured_companies (
                        board_code, company_type, group_name, source_code, company_uuid,
                        company_name, city_text, industry, scale_text, module_name,
                        description_text, official_site_url, career_site_url, extra_json, unique_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        "yingjiesheng",
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                    ),
                )
                inserted += 1
                continue

            has_changed = any(
                str(existing[field_name] or "") != value
                for field_name, value in record_values.items()
            ) or str(existing["extra_json"] or "") != payload_text
            if has_changed:
                conn.execute(
                    """
                    UPDATE featured_companies
                    SET board_code=?, company_type=?, group_name=?, source_code='yingjiesheng',
                        company_uuid=?, company_name=?, city_text=?, industry=?, scale_text=?, module_name=?,
                        description_text=?, official_site_url=?, career_site_url=?, extra_json=?, unique_hash=?, last_seen_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                        int(existing["id"]),
                    ),
                )
                updated += 1
            else:
                unchanged += 1

        conn.commit()

    return {
        "source_code": "yingjiesheng",
        "board_code": board_code,
        "module_name": module_name,
        "homepage_cards": len(homepage_items),
        "deadline_cards": len(deadline_items),
        "live_cards": len(homepage_items) + len(deadline_items),
        "fallback_to_seed_only": False,
        "live_sync_error": " | ".join(live_sync_errors),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def import_dxy_job_featured_companies() -> dict[str, Any]:
    inserted = 0
    updated = 0
    unchanged = 0
    live_sync_errors: list[str] = []
    module_name = "dxy_job_topic"
    board_code = "featured_famous"
    company_type = "famous_enterprise"

    homepage_items: list[dict[str, Any]] = []
    campus_items: list[dict[str, Any]] = []
    campus_notice_items: list[dict[str, Any]] = []
    fair_items: list[dict[str, Any]] = []
    fair_company_items: list[dict[str, Any]] = []
    career_news_items: list[dict[str, Any]] = []
    try:
        homepage_items = fetch_dxy_job_homepage_featured_companies()
    except Exception as exc:
        live_sync_errors.append("homepage: " + str(exc).splitlines()[0].strip())
    try:
        campus_items = fetch_dxy_job_campus_featured_companies()
    except Exception as exc:
        live_sync_errors.append("campus: " + str(exc).splitlines()[0].strip())
    try:
        campus_notice_items = fetch_dxy_job_campus_notice_featured_companies()
    except Exception as exc:
        live_sync_errors.append("campus_notice: " + str(exc).splitlines()[0].strip())
    try:
        fair_items = fetch_dxy_job_fair_featured_companies()
    except Exception as exc:
        live_sync_errors.append("fair: " + str(exc).splitlines()[0].strip())
    try:
        fair_company_items = fetch_dxy_job_fair_company_featured_companies()
    except Exception as exc:
        live_sync_errors.append("fair_company: " + str(exc).splitlines()[0].strip())
    try:
        career_news_items = fetch_dxy_job_career_news_featured_companies()
    except Exception as exc:
        live_sync_errors.append("career_news: " + str(exc).splitlines()[0].strip())

    detail_meta_cache: dict[str, dict[str, str]] = {}
    detail_meta_enriched = 0
    detail_meta_errors = 0
    for item in [*campus_notice_items, *career_news_items]:
        source_page_url = str(item.get("source_page_url") or item.get("source_url") or "").strip()
        if not is_dxy_job_notice_detail_url(source_page_url):
            continue
        try:
            detail_meta = detail_meta_cache.get(source_page_url)
            if detail_meta is None:
                detail_meta = fetch_dxy_job_notice_detail_meta(source_page_url)
                detail_meta_cache[source_page_url] = detail_meta
            if any(
                str(detail_meta.get(field_name) or "").strip()
                for field_name in (
                    "notice_publisher",
                    "notice_location",
                    "notice_region",
                    "notice_unit_type",
                    "notice_establishment",
                    "notice_publish_date",
                    "notice_deadline",
                    "notice_contact_person",
                    "notice_contact_phone",
                    "notice_apply_method",
                    "notice_position_summary",
                    "notice_degree_requirement",
                    "notice_major_requirement",
                    "application_period_text",
                )
            ):
                for key, value in detail_meta.items():
                    if not str(value or "").strip():
                        continue
                    if key == "application_period_text" or not str(item.get(key) or "").strip():
                        item[key] = value
                detail_meta_enriched += 1
        except Exception as exc:
            detail_meta_errors += 1
            if detail_meta_errors <= 3:
                live_sync_errors.append("detail_meta: " + str(exc).splitlines()[0].strip())

    def normalize_company_key(name: str) -> str:
        normalized = re.sub(r"\s+", "", str(name or "").strip().lower())
        for suffix in ("集团", "股份有限公司", "有限责任公司", "有限公司", "公司", "医院"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        return normalized

    merged_items: dict[str, dict[str, Any]] = {}
    for item in [*homepage_items, *campus_items, *campus_notice_items, *fair_items, *fair_company_items, *career_news_items]:
        company_name = str(item.get("company_name") or "").strip()
        if not company_name:
            continue
        dedupe_key = normalize_company_key(company_name)
        existing_item = dict(merged_items.get(dedupe_key) or {})
        merged_item = dict(existing_item)
        for key, value in item.items():
            if str(value or "").strip():
                merged_item[key] = value
        if not str(existing_item.get("company_name") or "").strip():
            merged_item["company_name"] = company_name
        merged_items[dedupe_key] = merged_item

    kind_counters = {
        "recommended_unit": 0,
        "hot_unit": 0,
        "urgent_unit": 0,
        "hospital_plan": 0,
        "banner_topic": 0,
        "campus_company": 0,
        "campus_jobnotice": 0,
        "campus_news": 0,
        "job_fair_article": 0,
        "job_fair_company": 0,
        "career_news": 0,
        "homepage_topic": 0,
    }
    for item in merged_items.values():
        kind = str(item.get("topic_source_kind") or "homepage_topic")
        kind_counters[kind] = int(kind_counters.get(kind, 0)) + 1

    with get_connection() as conn:
        for item in merged_items.values():
            company_name = str(item.get("company_name") or "").strip()
            if not company_name:
                continue

            source_page_url = str(item.get("source_page_url") or item.get("source_url") or DXY_JOB_HOME_URL).strip()
            unique_hash = hashlib.sha256(f"dxy_job|featured_famous|{source_page_url}".encode("utf-8")).hexdigest()[:32]
            company_uuid = hashlib.sha256(f"dxy_job|{company_name}".encode("utf-8")).hexdigest()[:24]
            payload = {
                "seed_kind": "dxy_job_topic",
                "source_platform": "jobmd",
                "sync_mode": "homepage_plus_topics" if (homepage_items or campus_items or campus_notice_items or fair_items or fair_company_items or career_news_items) else "empty",
                "company_name": company_name,
                "group_name": str(item.get("group_name") or ""),
                "source_url": str(item.get("source_url") or DXY_JOB_HOME_URL),
                "source_page_url": source_page_url,
                "topic_source_kind": str(item.get("topic_source_kind") or "homepage_topic"),
                "recruitment_batch": str(item.get("recruitment_batch") or ""),
                "recruitment_stage": str(item.get("recruitment_stage") or ""),
                "collected_at_text": str(item.get("collected_at_text") or ""),
                "application_period_text": str(item.get("application_period_text") or ""),
                "notice_publisher": str(item.get("notice_publisher") or ""),
                "notice_location": str(item.get("notice_location") or ""),
                "notice_region": str(item.get("notice_region") or ""),
                "notice_unit_type": str(item.get("notice_unit_type") or ""),
                "notice_establishment": str(item.get("notice_establishment") or ""),
                "notice_publish_date": str(item.get("notice_publish_date") or ""),
                "notice_deadline": str(item.get("notice_deadline") or ""),
                "notice_contact_person": str(item.get("notice_contact_person") or ""),
                "notice_contact_phone": str(item.get("notice_contact_phone") or ""),
                "notice_apply_method": str(item.get("notice_apply_method") or ""),
                "notice_position_summary": str(item.get("notice_position_summary") or ""),
                "notice_degree_requirement": str(item.get("notice_degree_requirement") or ""),
                "notice_major_requirement": str(item.get("notice_major_requirement") or ""),
                "notice_detail_url": str(item.get("notice_detail_url") or source_page_url),
                "notice_source_kind": str(item.get("notice_source_kind") or ""),
            }
            payload_text = json.dumps(payload, ensure_ascii=False)
            existing = conn.execute(
                "SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json FROM featured_companies WHERE unique_hash = ?",
                (unique_hash,),
            ).fetchone()
            if existing is None:
                if source_page_url:
                    existing = conn.execute(
                        """
                        SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json
                        FROM featured_companies
                        WHERE source_code = 'dxy_job' AND module_name = ? AND extra_json LIKE ?
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                        (module_name, f'%"source_page_url": "{source_page_url}"%'),
                    ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """
                    SELECT id, city_text, industry, scale_text, description_text, official_site_url, career_site_url, group_name, extra_json
                    FROM featured_companies
                    WHERE source_code = 'dxy_job' AND module_name = ? AND company_name = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (module_name, company_name),
                ).fetchone()

            record_values = {
                "city_text": str(item.get("city_text") or ""),
                "industry": str(item.get("industry") or "医疗医药"),
                "scale_text": str(item.get("scale_text") or ""),
                "description_text": str(item.get("description_text") or ""),
                "official_site_url": str(item.get("official_site_url") or ""),
                "career_site_url": str(item.get("career_site_url") or ""),
                "group_name": str(item.get("group_name") or "丁香人才首页专题"),
            }

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO featured_companies (
                        board_code, company_type, group_name, source_code, company_uuid,
                        company_name, city_text, industry, scale_text, module_name,
                        description_text, official_site_url, career_site_url, extra_json, unique_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        "dxy_job",
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                    ),
                )
                inserted += 1
                continue

            has_changed = any(
                str(existing[field_name] or "") != value
                for field_name, value in record_values.items()
            ) or str(existing["extra_json"] or "") != payload_text
            if has_changed:
                conn.execute(
                    """
                    UPDATE featured_companies
                    SET board_code=?, company_type=?, group_name=?, source_code='dxy_job',
                        company_uuid=?, company_name=?, city_text=?, industry=?, scale_text=?, module_name=?,
                        description_text=?, official_site_url=?, career_site_url=?, extra_json=?, unique_hash=?, last_seen_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        board_code,
                        company_type,
                        record_values["group_name"],
                        company_uuid,
                        company_name,
                        record_values["city_text"],
                        record_values["industry"],
                        record_values["scale_text"],
                        module_name,
                        record_values["description_text"],
                        record_values["official_site_url"],
                        record_values["career_site_url"],
                        payload_text,
                        unique_hash,
                        int(existing["id"]),
                    ),
                )
                updated += 1
            else:
                unchanged += 1

        conn.commit()

    return {
        "source_code": "dxy_job",
        "board_code": board_code,
        "module_name": module_name,
        "homepage_cards": len(homepage_items),
        "campus_cards": len(campus_items),
        "campus_notice_cards": len(campus_notice_items),
        "fair_cards": len(fair_items),
        "fair_company_cards": len(fair_company_items),
        "career_news_cards": len(career_news_items),
        "live_cards": len(homepage_items) + len(campus_items) + len(campus_notice_items) + len(fair_items) + len(fair_company_items) + len(career_news_items),
        "recommended_unit_cards": kind_counters.get("recommended_unit", 0),
        "hot_unit_cards": kind_counters.get("hot_unit", 0),
        "urgent_unit_cards": kind_counters.get("urgent_unit", 0),
        "hospital_plan_cards": kind_counters.get("hospital_plan", 0),
        "banner_topic_cards": kind_counters.get("banner_topic", 0),
        "campus_company_cards": kind_counters.get("campus_company", 0),
        "campus_jobnotice_cards": kind_counters.get("campus_jobnotice", 0),
        "campus_news_cards": kind_counters.get("campus_news", 0),
        "job_fair_article_cards": kind_counters.get("job_fair_article", 0),
        "job_fair_company_cards": kind_counters.get("job_fair_company", 0),
        "career_news_topic_cards": kind_counters.get("career_news", 0),
        "detail_meta_cards": detail_meta_enriched,
        "live_sync_error": " | ".join(live_sync_errors),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
    }


def _decode_featured_company_extra_json(raw_value: str) -> dict[str, Any]:
    text = str(raw_value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_featured_company_topic_meta(raw_value: str) -> dict[str, str]:
    payload = _decode_featured_company_extra_json(raw_value)
    return {
        "recruitment_batch": str(payload.get("recruitment_batch") or ""),
        "recruitment_stage": str(payload.get("recruitment_stage") or ""),
        "collected_at_text": str(payload.get("collected_at_text") or ""),
        "application_period_text": str(payload.get("application_period_text") or ""),
        "apply_label": str(payload.get("apply_label") or ""),
        "notice_publisher": str(payload.get("notice_publisher") or ""),
        "notice_location": str(payload.get("notice_location") or ""),
        "notice_region": str(payload.get("notice_region") or ""),
        "notice_unit_type": str(payload.get("notice_unit_type") or ""),
        "notice_establishment": str(payload.get("notice_establishment") or ""),
        "notice_publish_date": str(payload.get("notice_publish_date") or ""),
        "notice_deadline": str(payload.get("notice_deadline") or ""),
        "notice_contact_person": str(payload.get("notice_contact_person") or ""),
        "notice_contact_phone": str(payload.get("notice_contact_phone") or ""),
        "notice_apply_method": str(payload.get("notice_apply_method") or ""),
        "notice_position_summary": str(payload.get("notice_position_summary") or ""),
        "notice_degree_requirement": str(payload.get("notice_degree_requirement") or ""),
        "notice_major_requirement": str(payload.get("notice_major_requirement") or ""),
        "notice_detail_url": str(payload.get("notice_detail_url") or payload.get("source_page_url") or payload.get("source_url") or ""),
        "notice_source_kind": str(payload.get("notice_source_kind") or ""),
        "source_page_url": str(payload.get("source_page_url") or payload.get("source_url") or ""),
        "sync_mode": str(payload.get("sync_mode") or ""),
        "topic_source_kind": str(payload.get("topic_source_kind") or ""),
    }


def _score_niuke_company_name(company_name: str, payload: dict[str, Any]) -> tuple[int, int]:
    text = str(company_name or "").strip()
    score = 0
    if text:
        score += 5
    if not text.startswith("收藏"):
        score += 20
    if str(payload.get("application_period_text") or "").strip():
        score += 8
    if str(payload.get("topic_source_kind") or "").strip() == "schedule":
        score += 3
    noisy_keywords = ("全球领先", "龙头", "标杆", "平台", "专注", "提供", "连续", "百年", "总部", "稳健", "创新者")
    if not any(keyword in text for keyword in noisy_keywords):
        score += 6
    return (score, -len(text))


def _normalize_niuke_featured_company_names(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, company_name, extra_json
        FROM featured_companies
        WHERE source_code='niuke_campus' AND module_name='niuke_campus_topic'
        ORDER BY id ASC
        """
    ).fetchall()

    updated = 0
    for row in rows:
        payload = _decode_featured_company_extra_json(str(row["extra_json"] or ""))
        if str(payload.get("topic_source_kind") or "").strip() != "schedule":
            continue

        company_name = str(row["company_name"] or "").strip()
        if _is_non_company_schedule_name(company_name):
            conn.execute("DELETE FROM featured_companies WHERE id = ?", (int(row["id"]),))
            updated += 1
            continue

        normalized_name = _cleanup_schedule_company_name(company_name)
        if not normalized_name or normalized_name == company_name:
            continue

        payload["company_name"] = normalized_name
        target_unique_hash = hashlib.sha256(f"niuke_campus|featured_famous|{normalized_name}".encode("utf-8")).hexdigest()[:32]
        existing_row = conn.execute(
            "SELECT id FROM featured_companies WHERE unique_hash = ? AND id != ? LIMIT 1",
            (target_unique_hash, int(row["id"])),
        ).fetchone()
        if existing_row is not None:
            conn.execute("DELETE FROM featured_companies WHERE id = ?", (int(row["id"]),))
            updated += 1
            continue

        conn.execute(
            """
            UPDATE featured_companies
            SET company_name=?, company_uuid=?, unique_hash=?, extra_json=?, last_seen_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                normalized_name,
                hashlib.sha256(f"niuke_campus|{normalized_name}".encode("utf-8")).hexdigest()[:24],
                target_unique_hash,
                json.dumps(payload, ensure_ascii=False),
                int(row["id"]),
            ),
        )
        updated += 1

    return updated


def _compact_niuke_featured_company_duplicates(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, company_name, extra_json
        FROM featured_companies
        WHERE source_code='niuke_campus' AND module_name='niuke_campus_topic'
        ORDER BY id ASC
        """
    ).fetchall()

    grouped_rows: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        payload = _decode_featured_company_extra_json(str(row["extra_json"] or ""))
        topic_source_kind = str(payload.get("topic_source_kind") or "").strip()
        if topic_source_kind == "seed":
            continue
        source_page_url = str(payload.get("source_page_url") or payload.get("source_url") or "").strip()
        company_id = str(payload.get("company_id") or "").strip()
        entity_id = str(payload.get("entity_id") or "").strip()
        normalized_name = re.sub(r"\s+", "", str(row["company_name"] or "").strip().lower())
        identifier = company_id or entity_id
        if identifier and normalized_name:
            group_key = f"{identifier}::{normalized_name}"
        elif identifier:
            group_key = f"{source_page_url}::{identifier}"
        else:
            group_key = source_page_url
        if not group_key:
            continue
        grouped_rows.setdefault(group_key, []).append(row)

    deleted = 0
    for siblings in grouped_rows.values():
        if len(siblings) <= 1:
            continue

        canonical = max(
            siblings,
            key=lambda row: _score_niuke_company_name(
                str(row["company_name"] or ""),
                _decode_featured_company_extra_json(str(row["extra_json"] or "")),
            ),
        )
        duplicate_ids = [int(row["id"]) for row in siblings if int(row["id"]) != int(canonical["id"])]
        if not duplicate_ids:
            continue
        placeholders = ",".join("?" for _ in duplicate_ids)
        conn.execute(f"DELETE FROM featured_companies WHERE id IN ({placeholders})", duplicate_ids)
        deleted += len(duplicate_ids)

    return deleted


def _backfill_featured_company_buckets(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, company_name, industry, description_text, module_name, group_name, board_code, company_type
        FROM featured_companies
        """
    ).fetchall()
    for row in rows:
        inferred = infer_featured_company_bucket(
            company_name=str(row["company_name"] or ""),
            industry=str(row["industry"] or ""),
            description_text=str(row["description_text"] or ""),
            module_name=str(row["module_name"] or ""),
            group_name=str(row["group_name"] or ""),
        )
        current_board_code = str(row["board_code"] or "featured_famous")
        current_company_type = str(row["company_type"] or "famous_enterprise")
        current_group_name = str(row["group_name"] or "")
        if (
            current_board_code != inferred["board_code"]
            or current_company_type != inferred["company_type"]
            or current_group_name != inferred["group_name"]
        ):
            conn.execute(
                "UPDATE featured_companies SET board_code=?, company_type=?, group_name=? WHERE id=?",
                (inferred["board_code"], inferred["company_type"], inferred["group_name"], int(row["id"])),
            )


def _backfill_featured_company_links(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, company_name, official_site_url, career_site_url
        FROM featured_companies
        WHERE board_code = 'featured_famous'
        """
    ).fetchall()
    for row in rows:
        resolved_links = resolve_featured_company_links(str(row["company_name"] or ""))
        if not resolved_links["official_site_url"] and not resolved_links["career_site_url"]:
            continue

        next_official_site_url = resolved_links["official_site_url"] or str(row["official_site_url"] or "")
        next_career_site_url = resolved_links["career_site_url"] or str(row["career_site_url"] or "")
        if (
            next_official_site_url != str(row["official_site_url"] or "")
            or next_career_site_url != str(row["career_site_url"] or "")
        ):
            conn.execute(
                "UPDATE featured_companies SET official_site_url=?, career_site_url=? WHERE id=?",
                (next_official_site_url, next_career_site_url, int(row["id"])),
            )


def _ensure_table_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {str(row["name"]).lower() for row in rows}
    for column_name, column_sql in columns.items():
        if column_name.lower() in existing_columns:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def _migrate_featured_companies_schema(conn: sqlite3.Connection) -> None:
    _ensure_table_columns(
        conn,
        "featured_companies",
        {
            "board_code": "TEXT NOT NULL DEFAULT 'featured_famous'",
            "company_type": "TEXT NOT NULL DEFAULT 'famous_enterprise'",
            "group_name": "TEXT DEFAULT ''",
            "official_site_url": "TEXT DEFAULT ''",
            "career_site_url": "TEXT DEFAULT ''",
        },
    )
    conn.execute(
        """
        UPDATE featured_companies
        SET board_code = 'featured_famous'
        WHERE COALESCE(board_code, '') = ''
        """
    )
    conn.execute(
        """
        UPDATE featured_companies
        SET company_type = 'famous_enterprise'
        WHERE COALESCE(company_type, '') = ''
        """
    )
    conn.execute(
        """
        UPDATE featured_companies
        SET group_name = COALESCE(NULLIF(module_name, ''), '校招名企')
        WHERE COALESCE(group_name, '') = ''
        """
    )
    _backfill_featured_company_buckets(conn)
    _seed_manual_state_owned_featured_companies(conn)
    _backfill_featured_company_links(conn)


def init_database() -> None:
    with get_connection() as conn:
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
            CREATE TABLE IF NOT EXISTS favorite_companies (
                company_id INTEGER PRIMARY KEY,
                company_name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorite_jobs (
                job_id INTEGER PRIMARY KEY,
                source_job_id TEXT DEFAULT '',
                title_snapshot TEXT NOT NULL DEFAULT '',
                company_name_snapshot TEXT NOT NULL DEFAULT '',
                city_name_snapshot TEXT DEFAULT '',
                salary_text_snapshot TEXT DEFAULT '',
                source_code_snapshot TEXT DEFAULT '',
                status_snapshot TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT DEFAULT '',
                city_name TEXT DEFAULT '',
                filters_json TEXT DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                notify_frequency TEXT NOT NULL DEFAULT 'daily',
                last_triggered_at TEXT DEFAULT '',
                unique_hash TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                source_code TEXT DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'job_updated',
                before_payload_json TEXT DEFAULT '{}',
                after_payload_json TEXT DEFAULT '{}',
                change_summary TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL UNIQUE,
                tracking_status TEXT NOT NULL DEFAULT 'saved',
                source_url TEXT DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                applied_at TEXT DEFAULT '',
                interview_at TEXT DEFAULT '',
                offer_at TEXT DEFAULT '',
                result_at TEXT DEFAULT '',
                result_status TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        _migrate_featured_companies_schema(conn)
        _ensure_table_columns(
            conn,
            "jobs",
            {
                "offline_verification_status": "TEXT DEFAULT ''",
                "offline_verification_reason": "TEXT DEFAULT ''",
                "offline_verified_at": "TEXT DEFAULT ''",
            },
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_id ON jobs(status, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_source_code ON jobs(status, source_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_city_name ON jobs(status, city_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_last_seen_at ON jobs(status, last_seen_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_verification ON jobs(status, offline_verification_status)")
        conn.commit()

    seed_jobs_if_empty()
    seed_notifications_if_empty()


def get_app_state_value(state_key: str, default: str = "") -> str:
    normalized_key = str(state_key or "").strip()
    if not normalized_key:
        return default
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state_value FROM app_state WHERE state_key = ?",
            (normalized_key,),
        ).fetchone()
    if row is None:
        return default
    return str(row["state_value"] or default)


def set_app_state_value(state_key: str, state_value: str) -> None:
    normalized_key = str(state_key or "").strip()
    if not normalized_key:
        return
    normalized_value = str(state_value or "")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_state (state_key, state_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalized_key, normalized_value),
        )
        conn.commit()


def seed_jobs_if_empty() -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(1) AS count FROM jobs").fetchone()
        if row and row["count"] > 0:
            return

    if not SAMPLE_JSON_PATH.exists():
        return

    try:
        sample_jobs = json.loads(SAMPLE_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(sample_jobs, list):
        return

    with get_connection() as conn:
        for item in sample_jobs:
            if not isinstance(item, dict):
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    source_job_id,
                    title,
                    company_name,
                    city_name,
                    district_name,
                    salary_text,
                    degree_text,
                    experience_text,
                    brand_scale,
                    brand_stage,
                    job_type,
                    source_url,
                    official_apply_url,
                    description_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("encrypt_job_id", "")),
                    str(item.get("job_name", "")),
                    str(item.get("brand", "")),
                    str(item.get("city", "")),
                    str(item.get("area", "")),
                    str(item.get("salary", "")),
                    str(item.get("degree", "")),
                    str(item.get("experience", "")),
                    str(item.get("brand_scale", "")),
                    str(item.get("brand_stage", "")),
                    str(item.get("job_type", "")),
                    "",
                    "",
                    "",
                ),
            )
        conn.commit()


def list_jobs(
    keyword: str | None,
    city_name: str | None,
    internship_only: bool,
    source_code: str | None,
    status: str | None,
    salary_min_k: float | None,
    salary_max_k: float | None,
    degree_text: str | None,
    experience_text: str | None,
    sort_by: str | None,
    page: int,
    page_size: int,
    offline_verification_status: str | None = None,
    refresh_stale: bool = False,
) -> dict[str, Any]:
    if refresh_stale:
        mark_stale_jobs_inactive()

    normalized_status = (status or "active").strip().lower() or "active"
    if normalized_status not in {"active", "inactive", "all"}:
        normalized_status = "active"
    normalized_sort = (sort_by or "latest").strip().lower() or "latest"

    def build_where_sql(where_clauses: list[str]) -> str:
        if not where_clauses:
            return ""
        return " WHERE " + " AND ".join(where_clauses)

    def append_where_sql(where_sql: str, clause: str) -> str:
        if not where_sql:
            return f" WHERE {clause}"
        return f"{where_sql} AND {clause}"

    def salary_matches_filters(
        parsed_salary_min: float | None,
        parsed_salary_max: float | None,
    ) -> bool:
        if salary_min_k is not None:
            comparable_max = parsed_salary_max if parsed_salary_max is not None else parsed_salary_min
            if comparable_max is None or comparable_max < salary_min_k:
                return False
        if salary_max_k is not None:
            comparable_min = parsed_salary_min if parsed_salary_min is not None else parsed_salary_max
            if comparable_min is None or comparable_min > salary_max_k:
                return False
        return True

    def build_status_summary_from_rows(summary_rows: list[sqlite3.Row]) -> dict[str, Any]:
        summary = {
            "all_total": 0,
            "active_total": 0,
            "inactive_total": 0,
            "inactive_pending_total": 0,
            "inactive_confirmed_total": 0,
            "stale_after_hours": get_job_stale_hours(),
        }
        for row in summary_rows:
            parsed_salary_min, parsed_salary_max = _parse_salary_range_k(str(row["salary_text"] or ""))
            if not salary_matches_filters(parsed_salary_min, parsed_salary_max):
                continue
            summary["all_total"] += 1
            row_status = (str(row["status"] or "active").strip().lower() or "active")
            if row_status == "active":
                summary["active_total"] += 1
            elif row_status == "inactive":
                summary["inactive_total"] += 1
                verification_status = str(row["offline_verification_status"] or "").strip().lower()
                if verification_status == "confirmed_offline":
                    summary["inactive_confirmed_total"] += 1
                else:
                    summary["inactive_pending_total"] += 1
        return summary

    base_where_clauses: list[str] = []
    base_params: list[Any] = []

    normalized_verification_status = (offline_verification_status or "").strip().lower()
    if normalized_verification_status and normalized_verification_status != "all":
        base_where_clauses.append("COALESCE(offline_verification_status, '') = ?")
        base_params.append(normalized_verification_status)

    if keyword:
        keyword_like = f"%{keyword.lower()}%"
        base_where_clauses.append(
            "(" 
            "LOWER(title) LIKE ? OR LOWER(company_name) LIKE ? OR LOWER(description_text) LIKE ? OR LOWER(job_type) LIKE ?"
            ")"
        )
        base_params.extend([keyword_like, keyword_like, keyword_like, keyword_like])
    if city_name:
        base_where_clauses.append("city_name = ?")
        base_params.append(city_name)
    if source_code:
        base_where_clauses.append("source_code = ?")
        base_params.append(source_code)
    if degree_text:
        base_where_clauses.append("degree_text = ?")
        base_params.append(degree_text)
    if experience_text:
        base_where_clauses.append("experience_text = ?")
        base_params.append(experience_text)
    if internship_only:
        base_where_clauses.append(
            "(" 
            "title LIKE '%实习%' OR title LIKE '%兼职%' OR title LIKE '%应届%' OR "
            "experience_text LIKE '%在校%' OR experience_text LIKE '%应届%' OR job_type LIKE '%实习%' OR description_text LIKE '%实习%'"
            ")"
        )

    where_clauses = list(base_where_clauses)
    params = list(base_params)
    if normalized_status != "all":
        where_clauses.append("status = ?")
        params.append(normalized_status)

    base_where_sql = build_where_sql(base_where_clauses)
    where_sql = build_where_sql(where_clauses)

    select_sql = """
            SELECT id, title, company_name, city_name, salary_text, degree_text, official_apply_url, source_code,
                   job_type, experience_text, status, last_seen_at, offline_verification_status, offline_verified_at
            FROM jobs
        """

    # Common list views use "latest" sort without salary filters. Handle that path fully in SQL
    # so jobs/offline-jobs switching does not scan and paginate the whole table in Python.
    if normalized_sort == "latest" and salary_min_k is None and salary_max_k is None:
        offset = (page - 1) * page_size
        with get_connection() as conn:
            all_total_row = conn.execute(
                f"SELECT COUNT(1) AS count FROM jobs{base_where_sql}",
                base_params,
            ).fetchone()
            active_total_row = conn.execute(
                f"SELECT COUNT(1) AS count FROM jobs{append_where_sql(base_where_sql, 'status = ?')}",
                (*base_params, "active"),
            ).fetchone()
            inactive_total_row = conn.execute(
                f"SELECT COUNT(1) AS count FROM jobs{append_where_sql(base_where_sql, 'status = ?')}",
                (*base_params, "inactive"),
            ).fetchone()
            inactive_confirmed_where_sql = append_where_sql(
                base_where_sql,
                "status = ? AND COALESCE(offline_verification_status, '') = ?",
            )
            inactive_confirmed_total_row = conn.execute(
                f"SELECT COUNT(1) AS count FROM jobs{inactive_confirmed_where_sql}",
                (*base_params, "inactive", "confirmed_offline"),
            ).fetchone()
            total_row = conn.execute(
                f"SELECT COUNT(1) AS count FROM jobs{where_sql}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"""
                {select_sql}
                {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, page_size, offset),
            ).fetchall()
        inactive_total = int(inactive_total_row["count"]) if inactive_total_row else 0
        inactive_confirmed_total = int(inactive_confirmed_total_row["count"]) if inactive_confirmed_total_row else 0
        status_summary = {
            "all_total": int(all_total_row["count"]) if all_total_row else 0,
            "active_total": int(active_total_row["count"]) if active_total_row else 0,
            "inactive_total": inactive_total,
            "inactive_pending_total": max(inactive_total - inactive_confirmed_total, 0),
            "inactive_confirmed_total": inactive_confirmed_total,
            "stale_after_hours": get_job_stale_hours(),
        }

        return {
            "page": page,
            "page_size": page_size,
            "total": int(total_row["count"]) if total_row else 0,
            "items": [
                {
                    "job_id": int(row["id"]),
                    "title": str(row["title"]),
                    "company_name": str(row["company_name"]),
                    "city_name": str(row["city_name"]),
                    "salary_text": str(row["salary_text"] or ""),
                    "degree_text": str(row["degree_text"] or ""),
                    "official_apply_url": str(row["official_apply_url"] or ""),
                    "source_code": str(row["source_code"] or "unknown"),
                    "source_name": get_source_name(str(row["source_code"] or "unknown")),
                    "job_type": str(row["job_type"] or ""),
                    "experience_text": str(row["experience_text"] or ""),
                    "status": str(row["status"] or "active"),
                    "last_seen_at": str(row["last_seen_at"] or ""),
                    "offline_verification_status": str(row["offline_verification_status"] or ""),
                    "offline_verified_at": str(row["offline_verified_at"] or ""),
                }
                for row in rows
            ],
            "status_summary": status_summary,
        }

    with get_connection() as conn:
        summary_rows = conn.execute(
            f"""
            {select_sql}
            {base_where_sql}
            """,
            base_params,
        ).fetchall()
        rows = conn.execute(
            f"""
            {select_sql}
            {where_sql}
            """,
            params,
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        parsed_salary_min, parsed_salary_max = _parse_salary_range_k(str(row["salary_text"] or ""))
        if not salary_matches_filters(parsed_salary_min, parsed_salary_max):
                continue

        items.append(
            {
                "job_id": int(row["id"]),
                "title": str(row["title"]),
                "company_name": str(row["company_name"]),
                "city_name": str(row["city_name"]),
                "salary_text": str(row["salary_text"] or ""),
                "degree_text": str(row["degree_text"] or ""),
                "official_apply_url": str(row["official_apply_url"] or ""),
                "source_code": str(row["source_code"] or "unknown"),
                "source_name": get_source_name(str(row["source_code"] or "unknown")),
                "job_type": str(row["job_type"] or ""),
                "experience_text": str(row["experience_text"] or ""),
                "status": str(row["status"] or "active"),
                "last_seen_at": str(row["last_seen_at"] or ""),
                "offline_verification_status": str(row["offline_verification_status"] or ""),
                "offline_verified_at": str(row["offline_verified_at"] or ""),
                "_salary_min": parsed_salary_min,
                "_salary_max": parsed_salary_max,
            }
        )

    if normalized_sort == "salary_desc":
        items.sort(
            key=lambda item: (
                item["_salary_max"] is None,
                -(item["_salary_max"] or item["_salary_min"] or -1.0),
                -item["job_id"],
            )
        )
    elif normalized_sort == "salary_asc":
        items.sort(
            key=lambda item: (
                item["_salary_min"] is None,
                item["_salary_min"] or item["_salary_max"] or 9999.0,
                -item["job_id"],
            )
        )
    else:
        items.sort(key=lambda item: item["job_id"], reverse=True)

    total = len(items)
    offset = (page - 1) * page_size
    paged_items = items[offset : offset + page_size]
    for item in paged_items:
        item.pop("_salary_min", None)
        item.pop("_salary_max", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": paged_items,
        "status_summary": build_status_summary_from_rows(summary_rows),
    }


def list_job_filter_options(
    status: str | None = "active",
    offline_verification_status: str | None = None,
    refresh_stale: bool = False,
) -> dict[str, Any]:
    if refresh_stale:
        mark_stale_jobs_inactive()

    normalized_status = (status or "active").strip().lower() or "active"
    if normalized_status not in {"active", "inactive", "all"}:
        normalized_status = "active"
    status_clause = ""
    status_params: list[Any] = []
    if normalized_status != "all":
        status_clause = " AND status = ?"
        status_params.append(normalized_status)

    verification_clause = ""
    verification_params: list[Any] = []
    normalized_verification_status = (offline_verification_status or "").strip().lower()
    if normalized_verification_status and normalized_verification_status != "all":
        verification_clause = " AND COALESCE(offline_verification_status, '') = ?"
        verification_params.append(normalized_verification_status)

    shared_params = [*status_params, *verification_params]

    with get_connection() as conn:
        city_rows = conn.execute(
            (
            """
            SELECT city_name, COUNT(1) AS count
            FROM jobs
            WHERE city_name != ''
            """ + status_clause + verification_clause +
            """
            GROUP BY city_name
            ORDER BY count DESC, city_name ASC
            """
            ),
            shared_params,
        ).fetchall()
        source_rows = conn.execute(
            (
            """
            SELECT COALESCE(NULLIF(source_code, ''), 'unknown') AS source_code, COUNT(1) AS count
            FROM jobs
            WHERE 1 = 1
            """ + status_clause + verification_clause +
            """
            GROUP BY COALESCE(NULLIF(source_code, ''), 'unknown')
            ORDER BY count DESC, source_code ASC
            """
            ),
            shared_params,
        ).fetchall()
        degree_rows = conn.execute(
            (
            """
            SELECT degree_text, COUNT(1) AS count
            FROM jobs
            WHERE degree_text != ''
            """ + status_clause + verification_clause +
            """
            GROUP BY degree_text
            ORDER BY count DESC, degree_text ASC
            """
            ),
            shared_params,
        ).fetchall()
        experience_rows = conn.execute(
            (
            """
            SELECT experience_text, COUNT(1) AS count
            FROM jobs
            WHERE experience_text != ''
            """ + status_clause + verification_clause +
            """
            GROUP BY experience_text
            ORDER BY count DESC, experience_text ASC
            """
            ),
            shared_params,
        ).fetchall()
        verification_rows = conn.execute(
            (
            """
            SELECT offline_verification_status, COUNT(1) AS count
            FROM jobs
            WHERE COALESCE(offline_verification_status, '') != ''
            """ + status_clause +
            """
            GROUP BY offline_verification_status
            ORDER BY count DESC, offline_verification_status ASC
            """
            ),
            status_params,
        ).fetchall()

    return {
        "cities": [
            {"city_name": str(row["city_name"]), "count": int(row["count"])}
            for row in city_rows
        ],
        "sources": [
            {
                "source_code": str(row["source_code"]),
                "source_name": get_source_name(str(row["source_code"])),
                "count": int(row["count"]),
            }
            for row in source_rows
        ],
        "degrees": [
            {"degree_text": str(row["degree_text"]), "count": int(row["count"])}
            for row in degree_rows
        ],
        "experiences": [
            {"experience_text": str(row["experience_text"]), "count": int(row["count"])}
            for row in experience_rows
        ],
        "verification_statuses": [
            {
                "offline_verification_status": str(row["offline_verification_status"] or ""),
                "count": int(row["count"]),
            }
            for row in verification_rows
        ],
    }


def get_job_market_analytics(
    status: str | None = "active",
    top_n: int = 12,
    focus_source_code: str | None = None,
    refresh_stale: bool = True,
) -> dict[str, Any]:
    normalized_status = (status or "active").strip().lower() or "active"
    if normalized_status not in {"active", "inactive", "all"}:
        normalized_status = "active"
    normalized_top_n = max(int(top_n or 12), 1)
    normalized_focus_source_code = (focus_source_code or "").strip().lower() or None
    normalized_refresh_stale = bool(refresh_stale)
    cache_key = _build_job_market_analytics_cache_key(
        normalized_status,
        normalized_top_n,
        normalized_focus_source_code,
        normalized_refresh_stale,
    )
    cache_now = datetime.now(UTC)
    db_fingerprint = _get_jobs_db_fingerprint()
    cached_payload = _load_job_market_analytics_cache_entry(
        cache_key,
        db_fingerprint=db_fingerprint,
        current_time=cache_now,
        ttl_seconds=JOB_MARKET_ANALYTICS_CACHE_TTL_SECONDS,
    )
    if cached_payload is not None:
        return cached_payload

    if normalized_refresh_stale:
        mark_stale_jobs_inactive()

        cache_now = datetime.now(UTC)
        db_fingerprint = _get_jobs_db_fingerprint()
        cached_payload = _load_job_market_analytics_cache_entry(
            cache_key,
            db_fingerprint=db_fingerprint,
            current_time=cache_now,
            ttl_seconds=JOB_MARKET_ANALYTICS_CACHE_TTL_SECONDS,
        )
        if cached_payload is not None:
            return cached_payload

    status_clause = ""
    status_params: list[Any] = []
    if normalized_status != "all":
        status_clause = "WHERE status = ?"
        status_params.append(normalized_status)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT city_name, district_name, company_name, source_code, salary_text, job_type, last_seen_at
            FROM jobs
            {status_clause}
            """,
            status_params,
        ).fetchall()
        source_rows = conn.execute(
            """
            SELECT source_code, status, last_seen_at
            FROM jobs
            """
        ).fetchall()

    total_jobs = len(rows)
    companies: set[str] = set()
    cities: set[str] = set()
    salary_values: list[float] = []
    source_metrics: dict[str, dict[str, Any]] = {}
    city_metrics: dict[str, dict[str, Any]] = {}
    salary_band_counts = {
        "5K以下": 0,
        "5-10K": 0,
        "10-15K": 0,
        "15-20K": 0,
        "20-30K": 0,
        "30K以上": 0,
    }
    recent_24h_count = 0
    recent_7d_count = 0
    now = datetime.now()
    requested_focus_source_name = get_source_name(normalized_focus_source_code) if normalized_focus_source_code else ""

    def build_focus_bucket(source_code: str) -> dict[str, Any]:
        return {
            "source_code": source_code,
            "source_name": get_source_name(source_code),
            "total_jobs": 0,
            "companies": set(),
            "cities": set(),
            "districts": set(),
            "salary_values": [],
            "district_counts": {},
            "company_counts": {},
            "job_type_counts": {},
            "active_7d_job_count": 0,
        }

    def add_focus_row(bucket: dict[str, Any], *, company_name: str, city_name: str, district_name: str, job_type: str, comparable_salary: float | None, seen_at: datetime | None) -> None:
        bucket["total_jobs"] += 1
        if company_name:
            bucket["companies"].add(company_name)
            bucket["company_counts"][company_name] = bucket["company_counts"].get(company_name, 0) + 1
        if city_name:
            bucket["cities"].add(city_name)
        normalized_district = district_name or "未标注"
        bucket["districts"].add(normalized_district)
        bucket["district_counts"][normalized_district] = bucket["district_counts"].get(normalized_district, 0) + 1
        normalized_job_type = job_type or "未标注"
        bucket["job_type_counts"][normalized_job_type] = bucket["job_type_counts"].get(normalized_job_type, 0) + 1
        if comparable_salary is not None:
            bucket["salary_values"].append(float(comparable_salary))
        if seen_at is not None and now - seen_at <= timedelta(days=7):
            bucket["active_7d_job_count"] += 1

    def finalize_focus_profile(
        bucket: dict[str, Any] | None,
        *,
        requested_source_code: str,
        requested_source_name: str,
        profile_mode: str,
        profile_note: str,
    ) -> dict[str, Any] | None:
        if bucket is None or int(bucket.get("total_jobs") or 0) <= 0:
            return None
        focus_salary_values = list(bucket["salary_values"])
        total_jobs = int(bucket["total_jobs"])
        active_7d_job_count = int(bucket.get("active_7d_job_count") or 0)
        return {
            "source_code": bucket["source_code"],
            "source_name": bucket["source_name"],
            "requested_source_code": requested_source_code,
            "requested_source_name": requested_source_name,
            "profile_mode": profile_mode,
            "profile_note": profile_note,
            "total_jobs": total_jobs,
            "active_7d_job_count": active_7d_job_count,
            "historical_job_count": max(total_jobs - active_7d_job_count, 0),
            "total_companies": len(bucket["companies"]),
            "total_cities": len(bucket["cities"]),
            "total_districts": len(bucket["districts"]),
            "average_salary_k": round(sum(focus_salary_values) / len(focus_salary_values), 1) if focus_salary_values else None,
            "salary_sample_count": len(focus_salary_values),
            "district_distribution": _build_analytics_breakdown(bucket["district_counts"], normalized_top_n),
            "company_distribution": _build_analytics_breakdown(bucket["company_counts"], normalized_top_n),
            "job_type_distribution": _build_analytics_breakdown(bucket["job_type_counts"], normalized_top_n),
        }

    focus_profile: dict[str, Any] | None = build_focus_bucket(normalized_focus_source_code) if normalized_focus_source_code else None

    for row in rows:
        company_name = str(row["company_name"] or "").strip()
        city_name = str(row["city_name"] or "").strip()
        district_name = str(row["district_name"] or "").strip()
        source_code = str(row["source_code"] or "unknown").strip() or "unknown"
        salary_text = str(row["salary_text"] or "")
        job_type = str(row["job_type"] or "").strip()
        last_seen_at = str(row["last_seen_at"] or "").strip()
        seen_at = None

        if company_name:
            companies.add(company_name)
        if city_name:
            cities.add(city_name)
            city_bucket = city_metrics.setdefault(city_name, {"job_count": 0, "salary_values": []})
            city_bucket["job_count"] += 1

        salary_min, salary_max = _parse_salary_range_k(salary_text)
        comparable_salary = salary_max if salary_max is not None else salary_min
        if salary_min is not None and salary_max is not None:
            comparable_salary = (salary_min + salary_max) / 2
        if comparable_salary is not None:
            salary_values.append(float(comparable_salary))
            if city_name:
                city_metrics[city_name]["salary_values"].append(float(comparable_salary))
            if comparable_salary < 5:
                salary_band_counts["5K以下"] += 1
            elif comparable_salary < 10:
                salary_band_counts["5-10K"] += 1
            elif comparable_salary < 15:
                salary_band_counts["10-15K"] += 1
            elif comparable_salary < 20:
                salary_band_counts["15-20K"] += 1
            elif comparable_salary < 30:
                salary_band_counts["20-30K"] += 1
            else:
                salary_band_counts["30K以上"] += 1

        if last_seen_at:
            try:
                seen_at = datetime.fromisoformat(last_seen_at.replace("Z", ""))
            except ValueError:
                seen_at = None
            if seen_at is not None:
                if now - seen_at <= timedelta(hours=24):
                    recent_24h_count += 1
                if now - seen_at <= timedelta(days=7):
                    recent_7d_count += 1

        if focus_profile is not None and source_code.lower() == normalized_focus_source_code:
            add_focus_row(
                focus_profile,
                company_name=company_name,
                city_name=city_name,
                district_name=district_name,
                job_type=job_type,
                comparable_salary=comparable_salary,
                seen_at=seen_at,
            )

    for source_row in source_rows:
        source_code = str(source_row["source_code"] or "unknown").strip() or "unknown"
        row_status = str(source_row["status"] or "").strip().lower()
        last_seen_at = str(source_row["last_seen_at"] or "").strip()
        source_bucket = source_metrics.setdefault(
            source_code,
            {
                "job_count": 0,
                "active_7d_job_count": 0,
                "latest_seen_at": "",
                "latest_seen_at_dt": None,
            },
        )
        source_bucket["job_count"] += 1
        if not last_seen_at:
            continue
        try:
            seen_at = datetime.fromisoformat(last_seen_at.replace("Z", ""))
        except ValueError:
            continue
        if normalized_status == "all" or row_status == normalized_status:
            if now - seen_at <= timedelta(days=7):
                source_bucket["active_7d_job_count"] += 1
        latest_seen_at_dt = source_bucket.get("latest_seen_at_dt")
        if latest_seen_at_dt is None or seen_at > latest_seen_at_dt:
            source_bucket["latest_seen_at_dt"] = seen_at
            source_bucket["latest_seen_at"] = last_seen_at

    city_distribution = []
    for city_name, metric in city_metrics.items():
        city_salary_values = list(metric.get("salary_values") or [])
        avg_salary_k = round(sum(city_salary_values) / len(city_salary_values), 1) if city_salary_values else None
        city_distribution.append(
            {
                "city_name": city_name,
                "job_count": int(metric.get("job_count") or 0),
                "avg_salary_k": avg_salary_k,
                "salary_sample_count": len(city_salary_values),
            }
        )
    city_distribution.sort(
        key=lambda item: (
            -int(item["job_count"]),
            -(item["avg_salary_k"] or -1),
            str(item["city_name"]),
        )
    )

    source_distribution = [
        {
            "source_code": source_code,
            "source_name": get_source_name(source_code),
            "job_count": int(metric.get("job_count") or 0),
            "active_7d_job_count": int(metric.get("active_7d_job_count") or 0),
            "historical_job_count": max(
                int(metric.get("job_count") or 0) - int(metric.get("active_7d_job_count") or 0),
                0,
            ),
            "last_seen_at": str(metric.get("latest_seen_at") or ""),
            "is_active_7d": int(metric.get("active_7d_job_count") or 0) > 0,
        }
        for source_code, metric in source_metrics.items()
    ]
    source_distribution.sort(
        key=lambda item: (
            -int(item["active_7d_job_count"]),
            -int(item["job_count"]),
            str(item["source_name"]),
        )
    )

    active_source_count_7d = sum(1 for item in source_distribution if int(item["active_7d_job_count"]) > 0)
    historical_source_count = sum(1 for item in source_distribution if int(item["historical_job_count"]) > 0)

    salary_distribution = [
        {"label": label, "job_count": count}
        for label, count in salary_band_counts.items()
    ]

    average_salary_k = round(sum(salary_values) / len(salary_values), 1) if salary_values else None
    focus_source_profile = None
    if normalized_focus_source_code:
        focus_source_profile = finalize_focus_profile(
            focus_profile,
            requested_source_code=normalized_focus_source_code,
            requested_source_name=requested_focus_source_name,
            profile_mode="requested_active",
            profile_note="",
        )
        if focus_source_profile is None:
            with get_connection() as conn:
                focus_rows = conn.execute(
                    """
                    SELECT company_name, city_name, district_name, salary_text, job_type, last_seen_at
                    FROM jobs
                    WHERE lower(source_code) = ?
                    """,
                    [normalized_focus_source_code],
                ).fetchall()

            if focus_rows:
                requested_all_scope_bucket = build_focus_bucket(normalized_focus_source_code)
                for focus_row in focus_rows:
                    focus_company_name = str(focus_row["company_name"] or "").strip()
                    focus_city_name = str(focus_row["city_name"] or "").strip()
                    focus_district_name = str(focus_row["district_name"] or "").strip()
                    focus_salary_text = str(focus_row["salary_text"] or "")
                    focus_job_type = str(focus_row["job_type"] or "").strip()
                    focus_last_seen_at = str(focus_row["last_seen_at"] or "").strip()
                    focus_seen_at = None
                    if focus_last_seen_at:
                        try:
                            focus_seen_at = datetime.fromisoformat(focus_last_seen_at.replace("Z", ""))
                        except ValueError:
                            focus_seen_at = None
                    focus_salary_min, focus_salary_max = _parse_salary_range_k(focus_salary_text)
                    focus_comparable_salary = focus_salary_max if focus_salary_max is not None else focus_salary_min
                    if focus_salary_min is not None and focus_salary_max is not None:
                        focus_comparable_salary = (focus_salary_min + focus_salary_max) / 2
                    add_focus_row(
                        requested_all_scope_bucket,
                        company_name=focus_company_name,
                        city_name=focus_city_name,
                        district_name=focus_district_name,
                        job_type=focus_job_type,
                        comparable_salary=focus_comparable_salary,
                        seen_at=focus_seen_at,
                    )

                focus_source_profile = finalize_focus_profile(
                    requested_all_scope_bucket,
                    requested_source_code=normalized_focus_source_code,
                    requested_source_name=requested_focus_source_name,
                    profile_mode="requested_all",
                    profile_note=f"{requested_focus_source_name or normalized_focus_source_code} 当前 active 口径样本为 0，以下按该来源全量在库样本展示，便于判断后续应回刷哪些词池。",
                )
            elif source_distribution:
                fallback_source_item = source_distribution[0]
                fallback_source_code = str(fallback_source_item.get("source_code") or "").strip().lower()
                fallback_source_name = str(fallback_source_item.get("source_name") or get_source_name(fallback_source_code) or fallback_source_code)
                fallback_bucket = build_focus_bucket(fallback_source_code)
                for row in rows:
                    row_source_code = str(row["source_code"] or "unknown").strip().lower() or "unknown"
                    if row_source_code != fallback_source_code:
                        continue
                    company_name = str(row["company_name"] or "").strip()
                    city_name = str(row["city_name"] or "").strip()
                    district_name = str(row["district_name"] or "").strip()
                    salary_text = str(row["salary_text"] or "")
                    job_type = str(row["job_type"] or "").strip()
                    last_seen_at = str(row["last_seen_at"] or "").strip()
                    seen_at = None
                    if last_seen_at:
                        try:
                            seen_at = datetime.fromisoformat(last_seen_at.replace("Z", ""))
                        except ValueError:
                            seen_at = None
                    salary_min, salary_max = _parse_salary_range_k(salary_text)
                    comparable_salary = salary_max if salary_max is not None else salary_min
                    if salary_min is not None and salary_max is not None:
                        comparable_salary = (salary_min + salary_max) / 2
                    add_focus_row(
                        fallback_bucket,
                        company_name=company_name,
                        city_name=city_name,
                        district_name=district_name,
                        job_type=job_type,
                        comparable_salary=comparable_salary,
                        seen_at=seen_at,
                    )

                focus_source_profile = finalize_focus_profile(
                    fallback_bucket,
                    requested_source_code=normalized_focus_source_code,
                    requested_source_name=requested_focus_source_name,
                    profile_mode="fallback_active",
                    profile_note=f"{requested_focus_source_name or normalized_focus_source_code} 当前在库中暂无样本，以下临时展示 {fallback_source_name} 的活跃剖面，避免重点来源区域完全空白。",
                )

    result = {
        "overview": {
            "total_jobs": total_jobs,
            "total_companies": len(companies),
            "total_cities": len(cities),
            "average_salary_k": average_salary_k,
            "salary_sample_count": len(salary_values),
            "recent_24h_count": recent_24h_count,
            "recent_7d_count": recent_7d_count,
            "active_source_count_7d": active_source_count_7d,
            "historical_source_count": historical_source_count,
            "status_scope": normalized_status,
        },
        "city_distribution": city_distribution[:normalized_top_n],
        "source_distribution": source_distribution,
        "salary_distribution": salary_distribution,
        "focus_source_profile": focus_source_profile,
    }
    _store_job_market_analytics_cache_entry(
        cache_key,
        db_fingerprint=db_fingerprint,
        payload=result,
        current_time=datetime.now(UTC),
    )
    return result


def _build_analytics_breakdown(counts: dict[str, int], top_n: int) -> list[dict[str, Any]]:
    items = [
        {"label": label, "job_count": int(count)}
        for label, count in counts.items()
        if str(label or "").strip() and int(count or 0) > 0
    ]
    items.sort(key=lambda item: (-int(item["job_count"]), str(item["label"])))
    return items[: max(int(top_n or 12), 1)]


def _parse_salary_range_k(salary_text: str) -> tuple[float | None, float | None]:
    normalized = salary_text.strip().lower().replace(" ", "").replace(",", "")
    if not normalized or "面议" in normalized:
        return None, None

    def convert_to_monthly_k(value: float, unit: str) -> float:
        normalized_unit = unit.strip().lower()
        monthly_k = value
        if normalized_unit in {"元", "yuan"}:
            monthly_k = value / 1000
        elif normalized_unit in {"万"}:
            monthly_k = value * 10
        elif normalized_unit in {"千", "k"}:
            monthly_k = value

        if "/年" in normalized or "年" in normalized:
            monthly_k = monthly_k / 12
        elif "/天" in normalized or "天" in normalized:
            monthly_k = monthly_k * 22
        return monthly_k

    range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(k|千|万|元)", normalized)
    if range_match:
        unit = range_match.group(3)
        return convert_to_monthly_k(float(range_match.group(1)), unit), convert_to_monthly_k(float(range_match.group(2)), unit)

    range_match = re.search(r"(\d+(?:\.\d+)?)\s*(k|千|万|元)\s*-\s*(\d+(?:\.\d+)?)(k|千|万|元)", normalized)
    if range_match:
        return (
            convert_to_monthly_k(float(range_match.group(1)), range_match.group(2)),
            convert_to_monthly_k(float(range_match.group(3)), range_match.group(4)),
        )

    single_match = re.search(r"(\d+(?:\.\d+)?)(k|千|万|元)", normalized)
    if single_match:
        salary_value = convert_to_monthly_k(float(single_match.group(1)), single_match.group(2))
        return salary_value, salary_value

    return None, None


def get_job_detail(job_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                title,
                company_name,
                city_name,
                district_name,
                salary_text,
                degree_text,
                experience_text,
                description_text,
                source_url,
                official_apply_url,
                job_type,
                brand_scale,
                brand_stage,
                source_code,
                status,
                last_seen_at,
                offline_verification_status,
                offline_verification_reason,
                offline_verified_at
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "job_id": int(row["id"]),
        "company_id": compute_company_id(str(row["company_name"])),
        "title": str(row["title"]),
        "company_name": str(row["company_name"]),
        "city_name": str(row["city_name"] or ""),
        "district_name": str(row["district_name"] or ""),
        "salary_text": str(row["salary_text"] or ""),
        "degree_text": str(row["degree_text"] or ""),
        "experience_text": str(row["experience_text"] or ""),
        "description_text": str(row["description_text"] or ""),
        "source_url": str(row["source_url"] or ""),
        "official_apply_url": str(row["official_apply_url"] or ""),
        "job_type": str(row["job_type"] or ""),
        "brand_scale": str(row["brand_scale"] or ""),
        "brand_stage": str(row["brand_stage"] or ""),
        "source_code": str(row["source_code"] or "unknown"),
        "source_name": get_source_name(str(row["source_code"] or "unknown")),
        "status": str(row["status"] or "active"),
        "last_seen_at": str(row["last_seen_at"] or ""),
        "offline_verification_status": str(row["offline_verification_status"] or ""),
        "offline_verification_reason": str(row["offline_verification_reason"] or ""),
        "offline_verified_at": str(row["offline_verified_at"] or ""),
    }


def _strong_verify_job_url(url: str, timeout_seconds: float) -> dict[str, str]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return {
            "verification_status": "missing_url",
            "verification_reason": "缺少可校验链接",
        }

    request = urllib_request.Request(
        normalized_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            final_url = str(response.geturl() or normalized_url)
            status_code = int(getattr(response, "status", 200) or 200)
            body_preview = response.read(4096).decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        if exc.code in {404, 410}:
            return {
                "verification_status": "confirmed_offline",
                "verification_reason": f"HTTP {exc.code}",
            }
        return {
            "verification_status": "needs_review",
            "verification_reason": f"HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "verification_status": "needs_review",
            "verification_reason": f"请求异常: {exc}",
        }

    lowered_preview = body_preview.lower()
    if any(keyword in body_preview for keyword in OFFLINE_INVALID_PAGE_KEYWORDS):
        return {
            "verification_status": "confirmed_offline",
            "verification_reason": f"页面命中下架特征词 / HTTP {status_code}",
        }
    if status_code == 200 and any(token in lowered_preview for token in ("job", "职位", "招聘", "apply", "投递")):
        return {
            "verification_status": "rechecked_online",
            "verification_reason": f"链接可访问: {final_url}",
        }
    return {
        "verification_status": "needs_review",
        "verification_reason": f"响应可达但未识别为有效职位页: {final_url}",
    }


def mark_stale_jobs_inactive(
    stale_after_hours: int | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_hours = max(int(stale_after_hours or get_job_stale_hours()), 1)
    current_time = now or datetime.now()
    cutoff_time = current_time - timedelta(hours=normalized_hours)
    cutoff_text = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        stale_rows = conn.execute(
            """
            SELECT id, source_job_id, title, company_name, city_name, district_name, salary_text,
                   degree_text, experience_text, brand_scale, brand_stage, job_type, source_code, status
            FROM jobs
            WHERE status = 'active' AND COALESCE(last_seen_at, '') != '' AND last_seen_at < ?
            """,
            (cutoff_text,),
        ).fetchall()
        stale_ids = [int(row["id"]) for row in stale_rows]
        if stale_ids:
            placeholders = ", ".join(["?"] * len(stale_ids))
            conn.execute(
                f"""
                UPDATE jobs
                SET status = 'inactive',
                    offline_verification_status = 'pending',
                    offline_verification_reason = '',
                    offline_verified_at = ''
                WHERE id IN ({placeholders})
                """,
                stale_ids,
            )
            for row in stale_rows:
                before_payload = _build_job_snapshot_from_row(row)
                after_payload = {**before_payload, "status": "inactive"}
                summary = f"超过 {normalized_hours} 小时未再次抓到，已标记为下线"
                _create_job_change_event(
                    conn,
                    job_id=int(before_payload.get("job_id") or 0),
                    source_code=str(before_payload.get("source_code") or ""),
                    event_type="job_closed",
                    before_payload=before_payload,
                    after_payload=after_payload,
                    change_summary=summary,
                )
                _dispatch_notifications_for_job_event(
                    conn,
                    event_type="job_closed",
                    before_payload=before_payload,
                    after_payload=after_payload,
                    change_summary=summary,
                )
            conn.commit()

    return {
        "inactive_marked": len(stale_ids),
        "stale_after_hours": normalized_hours,
        "cutoff_time": cutoff_text,
    }


def _normalize_source_code_filters(source_codes: list[str] | None) -> list[str]:
    normalized_codes: list[str] = []
    for item in list(source_codes or []):
        normalized_code = str(item or "").strip().lower()
        if normalized_code and normalized_code not in normalized_codes:
            normalized_codes.append(normalized_code)
    return normalized_codes


def summarize_pending_inactive_sources(
    limit: int = 10,
    source_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_limit = max(int(limit or 0), 0)
    normalized_source_codes = _normalize_source_code_filters(source_codes)
    if normalized_limit == 0:
        return []
    if source_codes is not None and not normalized_source_codes:
        return []

    where_clauses = [
        "status = 'inactive'",
        "COALESCE(offline_verification_status, '') = 'pending'",
    ]
    params: list[Any] = []
    if normalized_source_codes:
        placeholders = ", ".join(["?"] * len(normalized_source_codes))
        where_clauses.append(f"COALESCE(LOWER(source_code), '') IN ({placeholders})")
        params.extend(normalized_source_codes)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(source_code, '') AS source_code,
                   COUNT(1) AS pending_count,
                   MIN(COALESCE(last_seen_at, '')) AS oldest_last_seen_at,
                   MAX(COALESCE(last_seen_at, '')) AS latest_last_seen_at
            FROM jobs
            WHERE {' AND '.join(where_clauses)}
            GROUP BY COALESCE(source_code, '')
            ORDER BY pending_count DESC, oldest_last_seen_at ASC, source_code ASC
            LIMIT ?
            """,
            (*params, normalized_limit),
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        source_code = str(row["source_code"] or "").strip().lower()
        if not source_code:
            continue
        items.append(
            {
                "source_code": source_code,
                "source_name": get_source_name(source_code),
                "pending_count": int(row["pending_count"] or 0),
                "oldest_last_seen_at": str(row["oldest_last_seen_at"] or ""),
                "latest_last_seen_at": str(row["latest_last_seen_at"] or ""),
            }
        )
    return items


def verify_pending_inactive_jobs(
    limit: int = DEFAULT_OFFLINE_STRONG_CHECK_LIMIT,
    timeout_seconds: float = DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS,
    source_codes: list[str] | None = None,
) -> dict[str, Any]:
    normalized_limit = max(int(limit or DEFAULT_OFFLINE_STRONG_CHECK_LIMIT), 0)
    normalized_timeout = max(float(timeout_seconds or DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS), 1.0)
    normalized_source_codes = _normalize_source_code_filters(source_codes)
    stats = {
        "verified_count": 0,
        "restored_count": 0,
        "confirmed_count": 0,
        "review_count": 0,
        "missing_url_count": 0,
        "limit": normalized_limit,
        "timeout_seconds": normalized_timeout,
    }
    if source_codes is not None:
        stats["selected_sources"] = list(normalized_source_codes)
    if normalized_limit == 0:
        return stats
    if source_codes is not None and not normalized_source_codes:
        return stats

    with get_connection() as conn:
        where_clauses = [
            "status = 'inactive'",
            "COALESCE(offline_verification_status, '') = 'pending'",
        ]
        params: list[Any] = []
        if normalized_source_codes:
            placeholders = ", ".join(["?"] * len(normalized_source_codes))
            where_clauses.append(f"COALESCE(LOWER(source_code), '') IN ({placeholders})")
            params.extend(normalized_source_codes)

        pending_rows = conn.execute(
            f"""
            SELECT id, source_url, official_apply_url
            FROM jobs
            WHERE {' AND '.join(where_clauses)}
            ORDER BY last_seen_at ASC, id ASC
            LIMIT ?
            """,
            (*params, normalized_limit),
        ).fetchall()
        if not pending_rows:
            return stats

        verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in pending_rows:
            candidate_url = str(row["official_apply_url"] or row["source_url"] or "")
            verification = _strong_verify_job_url(candidate_url, normalized_timeout)
            verification_status = str(verification.get("verification_status") or "needs_review")
            verification_reason = str(verification.get("verification_reason") or "")
            stats["verified_count"] += 1

            if verification_status == "rechecked_online":
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'active',
                        last_seen_at = CURRENT_TIMESTAMP,
                        offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                stats["restored_count"] += 1
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                if verification_status == "confirmed_offline":
                    stats["confirmed_count"] += 1
                elif verification_status == "missing_url":
                    stats["missing_url_count"] += 1
                else:
                    stats["review_count"] += 1

        conn.commit()
        return stats


def verify_recent_active_jobs_safely(
    limit: int = DEFAULT_SAFE_VERIFY_LIMIT,
    timeout_seconds: float = DEFAULT_SAFE_VERIFY_TIMEOUT_SECONDS,
    recent_active_hours: int = DEFAULT_SAFE_VERIFY_RECENT_ACTIVE_HOURS,
) -> dict[str, Any]:
    normalized_limit = max(int(limit or DEFAULT_SAFE_VERIFY_LIMIT), 0)
    normalized_timeout = max(float(timeout_seconds or DEFAULT_SAFE_VERIFY_TIMEOUT_SECONDS), 1.0)
    normalized_recent_hours = max(int(recent_active_hours or DEFAULT_SAFE_VERIFY_RECENT_ACTIVE_HOURS), 1)
    if normalized_limit == 0:
        return {
            "checked_count": 0,
            "confirmed_offline_count": 0,
            "still_online_count": 0,
            "review_count": 0,
            "missing_url_count": 0,
            "candidate_count": 0,
            "limit": normalized_limit,
            "timeout_seconds": normalized_timeout,
            "recent_active_hours": normalized_recent_hours,
        }

    cutoff_time = (datetime.now() - timedelta(hours=normalized_recent_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        candidate_rows = conn.execute(
            """
                        SELECT id, source_url, official_apply_url, last_seen_at, offline_verified_at, job_type, source_code
            FROM jobs
            WHERE status = 'active'
              AND COALESCE(last_seen_at, '') != ''
              AND last_seen_at >= ?
              AND COALESCE(NULLIF(official_apply_url, ''), NULLIF(source_url, '')) IS NOT NULL
            ORDER BY
              CASE WHEN COALESCE(offline_verified_at, '') = '' THEN 0 ELSE 1 END ASC,
              COALESCE(NULLIF(offline_verified_at, ''), '1970-01-01 00:00:00') ASC,
              last_seen_at DESC,
              id DESC
            LIMIT ?
            """,
            (cutoff_time, normalized_limit),
        ).fetchall()

        stats = {
            "checked_count": 0,
            "confirmed_offline_count": 0,
            "still_online_count": 0,
            "review_count": 0,
            "missing_url_count": 0,
            "candidate_count": len(candidate_rows),
            "limit": normalized_limit,
            "timeout_seconds": normalized_timeout,
            "recent_active_hours": normalized_recent_hours,
            "checked_job_types": [],
            "checked_sources": [],
        }
        if not candidate_rows:
            return stats

        verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job_type_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for row in candidate_rows:
            candidate_url = str(row["official_apply_url"] or row["source_url"] or "")
            job_type_label = str(row["job_type"] or "").strip() or "未标注类型"
            source_code = str(row["source_code"] or "unknown").strip().lower() or "unknown"
            job_type_counts[job_type_label] = job_type_counts.get(job_type_label, 0) + 1
            source_counts[source_code] = source_counts.get(source_code, 0) + 1
            verification = _strong_verify_job_url(candidate_url, normalized_timeout)
            verification_status = str(verification.get("verification_status") or "needs_review")
            verification_reason = str(verification.get("verification_reason") or "")
            stats["checked_count"] += 1

            if verification_status == "confirmed_offline":
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'inactive',
                        offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                stats["confirmed_offline_count"] += 1
            elif verification_status == "rechecked_online":
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'active',
                        offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                stats["still_online_count"] += 1
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET offline_verification_status = ?,
                        offline_verification_reason = ?,
                        offline_verified_at = ?
                    WHERE id = ?
                    """,
                    (verification_status, verification_reason, verified_at, row["id"]),
                )
                if verification_status == "missing_url":
                    stats["missing_url_count"] += 1
                else:
                    stats["review_count"] += 1

        stats["checked_job_types"] = [
            {"job_type": label, "count": count}
            for label, count in sorted(job_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        stats["checked_sources"] = [
            {"source_code": source_code, "source_name": get_source_name(source_code), "count": count}
            for source_code, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        conn.commit()
        return stats


def verify_job_offline_status(
    job_id: int,
    timeout_seconds: float = DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    normalized_timeout = max(float(timeout_seconds or DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS), 1.0)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, source_url, official_apply_url
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None

        candidate_url = str(row["official_apply_url"] or row["source_url"] or "")
        verification = _strong_verify_job_url(candidate_url, normalized_timeout)
        verification_status = str(verification.get("verification_status") or "needs_review")
        verification_reason = str(verification.get("verification_reason") or "")
        verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if verification_status == "rechecked_online":
            conn.execute(
                """
                UPDATE jobs
                SET status = 'active',
                    last_seen_at = CURRENT_TIMESTAMP,
                    offline_verification_status = ?,
                    offline_verification_reason = ?,
                    offline_verified_at = ?
                WHERE id = ?
                """,
                (verification_status, verification_reason, verified_at, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN status = 'inactive' THEN 'inactive' ELSE status END,
                    offline_verification_status = ?,
                    offline_verification_reason = ?,
                    offline_verified_at = ?
                WHERE id = ?
                """,
                (verification_status, verification_reason, verified_at, job_id),
            )
        conn.commit()

    return get_job_detail(job_id)


def restore_job_to_active(job_id: int) -> dict[str, Any] | None:
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'active',
                last_seen_at = CURRENT_TIMESTAMP,
                offline_verification_status = 'manual_restored',
                offline_verification_reason = '人工恢复为在库岗位',
                offline_verified_at = ?
            WHERE id = ?
            """,
            (verified_at, job_id),
        )
        conn.commit()
        if cursor.rowcount <= 0:
            return None

    return get_job_detail(job_id)


def compute_company_id(company_name: str) -> int:
    normalized = company_name.strip()
    if not normalized:
                return 0
    return sum((index + 1) * ord(char) for index, char in enumerate(normalized)) % 1000000007


def normalize_company_identity(company_name: str) -> str:
    normalized = re.sub(r"[\s()（）\-_/·,.，。]+", "", str(company_name or "").strip().lower())
    removable_suffixes = (
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "控股集团",
        "集团公司",
        "集团有限",
        "集团",
        "股份",
        "公司",
    )
    changed = True
    while changed and normalized:
        changed = False
        for suffix in removable_suffixes:
            suffix_text = suffix.lower()
            if normalized.endswith(suffix_text) and len(normalized) > len(suffix_text):
                normalized = normalized[: -len(suffix_text)]
                changed = True
                break
    return normalized


def _build_company_match_keys(company_name: str, aliases: list[str] | None = None) -> list[str]:
    raw_name = str(company_name or "").strip()
    normalized_values = []
    candidates = [raw_name, normalize_company_identity(raw_name)]
    for alias in aliases or []:
        candidates.extend([str(alias or "").strip(), normalize_company_identity(str(alias or "").strip())])

    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if value and value not in normalized_values:
            normalized_values.append(value)
    return normalized_values


def list_related_jobs_for_company(company_name: str, limit: int = 20, aliases: list[str] | None = None) -> dict[str, Any]:
    match_keys = _build_company_match_keys(company_name, aliases=aliases)
    if not match_keys:
        return {"count": 0, "items": [], "sources": [], "matched_company_names": []}

    like_terms = []
    for key in match_keys:
        if len(key) >= 2:
            like_terms.append(f"%{key}%")

    where_sql = "status = 'active'"
    params: list[Any] = []
    if like_terms:
        where_sql += " AND (" + " OR ".join(["LOWER(company_name) LIKE ?" for _ in like_terms]) + ")"
        params.extend(like_terms)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, company_name, city_name, salary_text, degree_text, experience_text,
                   source_code, source_url, official_apply_url, last_seen_at
            FROM jobs
            WHERE {where_sql}
            ORDER BY CASE WHEN source_code='guopin' THEN 0 ELSE 1 END, last_seen_at DESC, id DESC
            """,
            params,
        ).fetchall()

    matched_items: list[dict[str, Any]] = []
    matched_company_names: list[str] = []
    source_counts: dict[str, int] = {}
    for row in rows:
        row_company_name = str(row["company_name"] or "")
        row_keys = _build_company_match_keys(row_company_name)
        is_match = False
        for left in match_keys:
            for right in row_keys:
                if not left or not right:
                    continue
                if left == right or left in right or right in left:
                    is_match = True
                    break
            if is_match:
                break
        if not is_match:
            continue

        if row_company_name and row_company_name not in matched_company_names:
            matched_company_names.append(row_company_name)
        source_code = str(row["source_code"] or "unknown")
        source_counts[source_code] = source_counts.get(source_code, 0) + 1
        matched_items.append(
            {
                "job_id": int(row["id"]),
                "title": str(row["title"] or ""),
                "company_name": row_company_name,
                "city_name": str(row["city_name"] or ""),
                "salary_text": str(row["salary_text"] or ""),
                "degree_text": str(row["degree_text"] or ""),
                "experience_text": str(row["experience_text"] or ""),
                "source_code": source_code,
                "source_name": get_source_name(source_code),
                "source_url": str(row["source_url"] or ""),
                "official_apply_url": str(row["official_apply_url"] or ""),
                "last_seen_at": str(row["last_seen_at"] or ""),
            }
        )

    return {
        "count": len(matched_items),
        "items": matched_items[: max(int(limit or 20), 1)],
        "sources": [
            {"source_code": source_code, "source_name": get_source_name(source_code), "count": count}
            for source_code, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "matched_company_names": matched_company_names[:10],
    }


def get_featured_company_detail(featured_company_id: int, jobs_limit: int = 20) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, board_code, company_type, group_name, source_code, company_uuid, company_name,
                   city_text, industry, scale_text, module_name, description_text,
                   official_site_url, career_site_url, last_seen_at, extra_json
            FROM featured_companies
            WHERE id = ?
            """,
            (featured_company_id,),
        ).fetchone()

    if row is None:
        return None

    crawl_suggestions = _build_featured_company_crawl_suggestions(
        str(row["company_name"] or ""),
        board_code=str(row["board_code"] or "featured_famous"),
        city_text=str(row["city_text"] or ""),
    )
    related = list_related_jobs_for_company(
        str(row["company_name"] or ""),
        limit=jobs_limit,
        aliases=get_featured_company_aliases(str(row["company_name"] or "")),
    )
    collect_mode = "manual_seed" if str(row["source_code"] or "") == "manual_seed" else "platform_module"
    topic_meta = _build_featured_company_topic_meta(str(row["extra_json"] or ""))
    return {
        "company_id": compute_company_id(str(row["company_name"] or "")),
        "featured_company_id": int(row["id"]),
        "board_code": str(row["board_code"] or "featured_famous"),
        "board_name": get_featured_board_name(str(row["board_code"] or "featured_famous")),
        "company_type": str(row["company_type"] or "famous_enterprise"),
        "company_type_name": get_featured_company_type_name(str(row["company_type"] or "famous_enterprise")),
        "group_name": str(row["group_name"] or ""),
        "source_code": str(row["source_code"] or "unknown"),
        "source_name": get_source_name(str(row["source_code"] or "unknown")),
        "company_uuid": str(row["company_uuid"] or ""),
        "company_name": str(row["company_name"] or ""),
        "city_text": str(row["city_text"] or ""),
        "industry": str(row["industry"] or ""),
        "scale_text": str(row["scale_text"] or ""),
        "module_name": str(row["module_name"] or ""),
        "description_text": str(row["description_text"] or ""),
        "official_site_url": str(row["official_site_url"] or ""),
        "career_site_url": str(row["career_site_url"] or ""),
        "last_seen_at": str(row["last_seen_at"] or ""),
        **topic_meta,
        "collect_mode": collect_mode,
        "crawl_suggested_queries": list(crawl_suggestions["queries"]),
        "crawl_suggested_cities": list(crawl_suggestions["cities"]),
        "crawl_suggested_sources": list(crawl_suggestions["sources"]),
        "related_job_count": int(related["count"]),
        "related_jobs": list(related["items"]),
        "related_sources": list(related["sources"]),
        "matched_company_names": list(related["matched_company_names"]),
    }


def save_favorite_company(company_id: int, company_name: str) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO favorite_companies (company_id, company_name)
            VALUES (?, ?)
            """,
            (company_id, company_name),
        )
        conn.commit()

    return {"company_id": company_id, "company_name": company_name}


def save_favorite_job(job_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, source_job_id, title, company_name, city_name, salary_text, source_code, status
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None

        conn.execute(
            """
            INSERT INTO favorite_jobs (
                job_id, source_job_id, title_snapshot, company_name_snapshot,
                city_name_snapshot, salary_text_snapshot, source_code_snapshot, status_snapshot,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                source_job_id = excluded.source_job_id,
                title_snapshot = excluded.title_snapshot,
                company_name_snapshot = excluded.company_name_snapshot,
                city_name_snapshot = excluded.city_name_snapshot,
                salary_text_snapshot = excluded.salary_text_snapshot,
                source_code_snapshot = excluded.source_code_snapshot,
                status_snapshot = excluded.status_snapshot,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(row["id"]),
                str(row["source_job_id"] or ""),
                str(row["title"] or ""),
                str(row["company_name"] or ""),
                str(row["city_name"] or ""),
                str(row["salary_text"] or ""),
                str(row["source_code"] or ""),
                str(row["status"] or "active"),
            ),
        )
        conn.commit()

    return {
        "job_id": int(row["id"]),
        "title": str(row["title"] or ""),
        "company_name": str(row["company_name"] or ""),
        "city_name": str(row["city_name"] or ""),
        "salary_text": str(row["salary_text"] or ""),
        "source_code": str(row["source_code"] or "unknown"),
        "source_name": get_source_name(str(row["source_code"] or "unknown")),
        "status": str(row["status"] or "active"),
        "created_at": "",
        "updated_at": "",
        "is_favorited": True,
    }


def create_saved_search(
    keyword: str = "",
    city_name: str = "",
    filters: dict[str, Any] | None = None,
    enabled: bool = True,
    notify_frequency: str = "daily",
) -> dict[str, Any]:
    normalized_keyword = str(keyword or "").strip()
    normalized_city_name = str(city_name or "").strip()
    normalized_filters = _normalize_saved_search_filters(filters)
    normalized_notify_frequency = str(notify_frequency or "daily").strip().lower() or "daily"
    unique_hash = _build_saved_search_unique_hash(normalized_keyword, normalized_city_name, normalized_filters)
    filters_json = json.dumps(normalized_filters, ensure_ascii=False, sort_keys=True)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO saved_searches (
                keyword, city_name, filters_json, enabled, notify_frequency, unique_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(unique_hash) DO UPDATE SET
                filters_json = excluded.filters_json,
                enabled = excluded.enabled,
                notify_frequency = excluded.notify_frequency,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                normalized_keyword,
                normalized_city_name,
                filters_json,
                1 if enabled else 0,
                normalized_notify_frequency,
                unique_hash,
            ),
        )
        row = conn.execute(
            """
            SELECT id, keyword, city_name, filters_json, enabled, notify_frequency,
                   last_triggered_at, created_at, updated_at
            FROM saved_searches
            WHERE unique_hash = ?
            """,
            (unique_hash,),
        ).fetchone()
        conn.commit()

    return {
        "search_id": int(row["id"]),
        "keyword": str(row["keyword"] or ""),
        "city_name": str(row["city_name"] or ""),
        "filters": json.loads(str(row["filters_json"] or "{}")),
        "enabled": bool(row["enabled"]),
        "notify_frequency": str(row["notify_frequency"] or "daily"),
        "last_triggered_at": str(row["last_triggered_at"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def list_saved_searches(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where_sql = ""
    params: list[Any] = []
    if keyword:
        where_sql = " WHERE LOWER(keyword) LIKE ? OR LOWER(city_name) LIKE ?"
        keyword_like = f"%{keyword.lower()}%"
        params.extend([keyword_like, keyword_like])

    with get_connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS count FROM saved_searches{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT id, keyword, city_name, filters_json, enabled, notify_frequency,
                   last_triggered_at, created_at, updated_at
            FROM saved_searches
            {where_sql}
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total_row["count"]) if total_row else 0,
        "items": [
            {
                "search_id": int(row["id"]),
                "keyword": str(row["keyword"] or ""),
                "city_name": str(row["city_name"] or ""),
                "filters": json.loads(str(row["filters_json"] or "{}")),
                "enabled": bool(row["enabled"]),
                "notify_frequency": str(row["notify_frequency"] or "daily"),
                "last_triggered_at": str(row["last_triggered_at"] or ""),
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ],
    }


def update_saved_search(
    search_id: int,
    *,
    enabled: bool | None = None,
    notify_frequency: str | None = None,
    keyword: str | None = None,
    city_name: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, keyword, city_name, filters_json, enabled, notify_frequency,
                   last_triggered_at, created_at, updated_at
            FROM saved_searches
            WHERE id = ?
            """,
            (search_id,),
        ).fetchone()
        if existing is None:
            return None

        next_keyword = str(keyword if keyword is not None else existing["keyword"] or "").strip()
        next_city_name = str(city_name if city_name is not None else existing["city_name"] or "").strip()
        next_filters = _normalize_saved_search_filters(
            filters if filters is not None else json.loads(str(existing["filters_json"] or "{}"))
        )
        next_enabled = bool(existing["enabled"]) if enabled is None else bool(enabled)
        next_notify_frequency = str(notify_frequency if notify_frequency is not None else existing["notify_frequency"] or "daily").strip().lower() or "daily"
        next_unique_hash = _build_saved_search_unique_hash(next_keyword, next_city_name, next_filters)

        conn.execute(
            """
            UPDATE saved_searches
            SET keyword = ?,
                city_name = ?,
                filters_json = ?,
                enabled = ?,
                notify_frequency = ?,
                unique_hash = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                next_keyword,
                next_city_name,
                json.dumps(next_filters, ensure_ascii=False, sort_keys=True),
                1 if next_enabled else 0,
                next_notify_frequency,
                next_unique_hash,
                search_id,
            ),
        )
        row = conn.execute(
            """
            SELECT id, keyword, city_name, filters_json, enabled, notify_frequency,
                   last_triggered_at, created_at, updated_at
            FROM saved_searches
            WHERE id = ?
            """,
            (search_id,),
        ).fetchone()
        conn.commit()

    return {
        "search_id": int(row["id"]),
        "keyword": str(row["keyword"] or ""),
        "city_name": str(row["city_name"] or ""),
        "filters": json.loads(str(row["filters_json"] or "{}")),
        "enabled": bool(row["enabled"]),
        "notify_frequency": str(row["notify_frequency"] or "daily"),
        "last_triggered_at": str(row["last_triggered_at"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def delete_saved_search(search_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        conn.commit()
    return cursor.rowcount > 0


def remove_favorite_job(job_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM favorite_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
    return cursor.rowcount > 0


def list_favorite_jobs(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where_sql = ""
    params: list[Any] = []
    if keyword:
        where_sql = " WHERE LOWER(title_snapshot) LIKE ? OR LOWER(company_name_snapshot) LIKE ?"
        keyword_like = f"%{keyword.lower()}%"
        params.extend([keyword_like, keyword_like])

    with get_connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS count FROM favorite_jobs{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT job_id, title_snapshot, company_name_snapshot, city_name_snapshot,
                   salary_text_snapshot, source_code_snapshot, status_snapshot,
                   created_at, updated_at
            FROM favorite_jobs
            {where_sql}
            ORDER BY updated_at DESC, job_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total_row["count"]) if total_row else 0,
        "items": [
            {
                "job_id": int(row["job_id"]),
                "title": str(row["title_snapshot"] or ""),
                "company_name": str(row["company_name_snapshot"] or ""),
                "city_name": str(row["city_name_snapshot"] or ""),
                "salary_text": str(row["salary_text_snapshot"] or ""),
                "source_code": str(row["source_code_snapshot"] or "unknown"),
                "source_name": get_source_name(str(row["source_code_snapshot"] or "unknown")),
                "status": str(row["status_snapshot"] or "active"),
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "is_favorited": True,
            }
            for row in rows
        ],
    }


def list_favorite_companies(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where_sql = ""
    params: list[Any] = []
    if keyword:
        where_sql = " WHERE LOWER(company_name) LIKE ?"
        params.append(f"%{keyword.lower()}%")

    with get_connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS count FROM favorite_companies{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT company_id, company_name
            FROM favorite_companies
            {where_sql}
            ORDER BY created_at DESC, company_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total_row["count"]) if total_row else 0,
        "items": [
            {
                "company_id": int(row["company_id"]),
                "company_name": str(row["company_name"]),
            }
            for row in rows
        ],
    }


def list_featured_companies(
    keyword: str | None = None,
    board_code: str | None = None,
    company_type: str | None = None,
    group_name: str | None = None,
    city_name: str | None = None,
    industry: str | None = None,
    module_name: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where_clauses: list[str] = []
    params: list[Any] = []

    if keyword:
        keyword_like = f"%{keyword.lower()}%"
        where_clauses.append(
            "(LOWER(company_name) LIKE ? OR LOWER(description_text) LIKE ? OR LOWER(industry) LIKE ? OR LOWER(city_text) LIKE ?)"
        )
        params.extend([keyword_like, keyword_like, keyword_like, keyword_like])
    if board_code:
        where_clauses.append("board_code = ?")
        params.append(board_code)
    if company_type:
        where_clauses.append("company_type = ?")
        params.append(company_type)
    if group_name:
        where_clauses.append("group_name = ?")
        params.append(group_name)
    if city_name:
        where_clauses.append("city_text LIKE ?")
        params.append(f"%{city_name}%")
    if industry:
        where_clauses.append("industry = ?")
        params.append(industry)
    if module_name:
        where_clauses.append("module_name = ?")
        params.append(module_name)

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    with get_connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS count FROM featured_companies{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
             SELECT id, board_code, company_type, group_name, source_code, company_uuid,
                 company_name, city_text, industry, scale_text, module_name,
                 description_text, official_site_url, career_site_url, last_seen_at, extra_json
            FROM featured_companies
            {where_sql}
            ORDER BY last_seen_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total_row["count"]) if total_row else 0,
        "items": [
            {
                **_build_featured_company_topic_meta(str(row["extra_json"] or "")),
                "company_id": compute_company_id(str(row["company_name"] or "")),
                "featured_company_id": int(row["id"]),
                "board_code": str(row["board_code"] or "featured_famous"),
                "board_name": get_featured_board_name(str(row["board_code"] or "featured_famous")),
                "company_type": str(row["company_type"] or "famous_enterprise"),
                "company_type_name": get_featured_company_type_name(str(row["company_type"] or "famous_enterprise")),
                "group_name": str(row["group_name"] or ""),
                "source_code": str(row["source_code"] or "unknown"),
                "source_name": get_source_name(str(row["source_code"] or "unknown")),
                "company_uuid": str(row["company_uuid"] or ""),
                "company_name": str(row["company_name"] or ""),
                "city_text": str(row["city_text"] or ""),
                "industry": str(row["industry"] or ""),
                "scale_text": str(row["scale_text"] or ""),
                "module_name": str(row["module_name"] or ""),
                "description_text": str(row["description_text"] or ""),
                "official_site_url": str(row["official_site_url"] or ""),
                "career_site_url": str(row["career_site_url"] or ""),
                "last_seen_at": str(row["last_seen_at"] or ""),
            }
            for row in rows
        ],
    }


def list_featured_company_filter_options() -> dict[str, Any]:
    with get_connection() as conn:
        board_rows = conn.execute(
            """
            SELECT board_code, COUNT(1) AS count
            FROM featured_companies
            WHERE board_code != ''
            GROUP BY board_code
            ORDER BY count DESC, board_code ASC
            """
        ).fetchall()
        company_type_rows = conn.execute(
            """
            SELECT company_type, COUNT(1) AS count
            FROM featured_companies
            WHERE company_type != ''
            GROUP BY company_type
            ORDER BY count DESC, company_type ASC
            """
        ).fetchall()
        group_rows = conn.execute(
            """
            SELECT group_name, COUNT(1) AS count
            FROM featured_companies
            WHERE group_name != ''
            GROUP BY group_name
            ORDER BY count DESC, group_name ASC
            """
        ).fetchall()
        city_rows = conn.execute(
            """
            SELECT city_text, COUNT(1) AS count
            FROM featured_companies
            WHERE city_text != ''
            GROUP BY city_text
            ORDER BY count DESC, city_text ASC
            """
        ).fetchall()
        industry_rows = conn.execute(
            """
            SELECT industry, COUNT(1) AS count
            FROM featured_companies
            WHERE industry != ''
            GROUP BY industry
            ORDER BY count DESC, industry ASC
            """
        ).fetchall()
        module_rows = conn.execute(
            """
            SELECT module_name, COUNT(1) AS count
            FROM featured_companies
            WHERE module_name != ''
            GROUP BY module_name
            ORDER BY count DESC, module_name ASC
            """
        ).fetchall()

    return {
        "boards": [
            {
                "board_code": str(row["board_code"]),
                "board_name": get_featured_board_name(str(row["board_code"])),
                "count": int(row["count"]),
            }
            for row in board_rows
        ],
        "company_types": [
            {
                "company_type": str(row["company_type"]),
                "company_type_name": get_featured_company_type_name(str(row["company_type"])),
                "count": int(row["count"]),
            }
            for row in company_type_rows
        ],
        "groups": [
            {"group_name": str(row["group_name"]), "count": int(row["count"])}
            for row in group_rows
        ],
        "cities": [
            {"city_name": str(row["city_text"]), "count": int(row["count"])}
            for row in city_rows
        ],
        "industries": [
            {"industry": str(row["industry"]), "count": int(row["count"])}
            for row in industry_rows
        ],
        "modules": [
            {"module_name": str(row["module_name"]), "count": int(row["count"])}
            for row in module_rows
        ],
    }


def seed_notifications_if_empty() -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(1) AS count FROM notifications").fetchone()
        if row and row["count"] > 0:
            return

        sample_notifications = [
            ("company_new_job", "你收藏的企业有新岗位", "易诚互动新增了 2 个 Java 岗位", None, 2001),
            ("new_job", "新职位匹配你的订阅", "发现 3 个新的 Java 开发职位（青岛）", None, None),
            ("job_updated", "职位信息更新", "Java开发工程师 薪资已更新为 12-18K", 1001, None),
        ]
        for ntype, title, content, job_id, company_id in sample_notifications:
            conn.execute(
                """
                INSERT INTO notifications (notification_type, title, content, related_job_id, related_company_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ntype, title, content, job_id, company_id),
            )
        conn.commit()


def list_notifications(
    page: int,
    page_size: int,
    notification_type: str | None = None,
    action_source: str | None = None,
    unread_only: bool = False,
    related_job_id: int | None = None,
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    where_clauses: list[str] = []
    params: list[Any] = []

    if notification_type:
        where_clauses.append("notification_type = ?")
        params.append(notification_type)
    if action_source:
        matched_types = get_notification_types_for_action_source(action_source)
        if not matched_types:
            where_clauses.append("1 = 0")
        else:
            placeholders = ", ".join("?" for _ in matched_types)
            where_clauses.append(f"notification_type IN ({placeholders})")
            params.extend(matched_types)
    if unread_only:
        where_clauses.append("is_read = 0")
    if related_job_id is not None:
        where_clauses.append("related_job_id = ?")
        params.append(int(related_job_id))

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    with get_connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(1) AS count FROM notifications{where_sql}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT id, notification_type, title, content, related_job_id,
                   related_company_id, is_read, created_at
            FROM notifications
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": page_size,
        "total": int(total_row["count"]) if total_row else 0,
        "items": [
            {
                "notification_id": int(row["id"]),
                "notification_type": str(row["notification_type"]),
                "action_source": get_notification_action_source(str(row["notification_type"]))[0],
                "action_source_name": get_notification_action_source(str(row["notification_type"]))[1],
                "title": str(row["title"]),
                "content": str(row["content"] or ""),
                "is_read": bool(row["is_read"]),
                "created_at": str(row["created_at"] or ""),
                "related_job_id": row["related_job_id"],
                "related_company_id": row["related_company_id"],
            }
            for row in rows
        ],
    }


def list_job_change_events(job_id: int, limit: int = 20) -> list[dict[str, Any]]:
    normalized_limit = max(int(limit or 20), 1)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, event_type, source_code, before_payload_json, after_payload_json, change_summary, created_at
            FROM job_change_events
            WHERE job_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(job_id), normalized_limit),
        ).fetchall()

    return [
        {
            "event_id": int(row["id"]),
            "event_type": str(row["event_type"] or "job_updated"),
            "source_code": str(row["source_code"] or ""),
            "source_name": get_source_name(str(row["source_code"] or "unknown")),
            "change_summary": str(row["change_summary"] or ""),
            "created_at": str(row["created_at"] or ""),
            "before_payload": json.loads(str(row["before_payload_json"] or "{}")),
            "after_payload": json.loads(str(row["after_payload_json"] or "{}")),
        }
        for row in rows
    ]


def mark_notification_read(notification_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,),
        )
        conn.commit()
    return cursor.rowcount > 0


def mark_all_notifications_read() -> int:
    with get_connection() as conn:
        cursor = conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        conn.commit()
    return int(cursor.rowcount or 0)


def get_notification_stats() -> dict[str, int]:
    with get_connection() as conn:
        total_row = conn.execute("SELECT COUNT(1) AS count FROM notifications").fetchone()
        unread_row = conn.execute("SELECT COUNT(1) AS count FROM notifications WHERE is_read = 0").fetchone()
    return {
        "total": int(total_row["count"] or 0) if total_row else 0,
        "unread": int(unread_row["count"] or 0) if unread_row else 0,
    }


def create_notification(
    notification_type: str,
    title: str,
    content: str,
    related_job_id: int | None = None,
    related_company_id: int | None = None,
) -> dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO notifications (notification_type, title, content, related_job_id, related_company_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (notification_type, title, content, related_job_id, related_company_id),
        )
        conn.commit()
        new_id = cursor.lastrowid

    return {
        "notification_id": new_id,
        "notification_type": notification_type,
        "action_source": get_notification_action_source(notification_type)[0],
        "action_source_name": get_notification_action_source(notification_type)[1],
        "title": title,
        "content": content,
        "is_read": False,
        "related_job_id": related_job_id,
        "related_company_id": related_company_id,
    }


def _build_job_snapshot_from_row(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    row_data = dict(row)
    company_name = str(row_data.get("company_name") or "")
    source_code = str(row_data.get("source_code") or "")
    return {
        "job_id": int(row_data.get("id") or row_data.get("job_id") or 0),
        "source_job_id": str(row_data.get("source_job_id") or ""),
        "title": str(row_data.get("title") or ""),
        "company_name": company_name,
        "company_id": compute_company_id(company_name),
        "city_name": str(row_data.get("city_name") or ""),
        "district_name": str(row_data.get("district_name") or ""),
        "salary_text": str(row_data.get("salary_text") or ""),
        "degree_text": str(row_data.get("degree_text") or ""),
        "experience_text": str(row_data.get("experience_text") or ""),
        "brand_scale": str(row_data.get("brand_scale") or ""),
        "brand_stage": str(row_data.get("brand_stage") or ""),
        "job_type": str(row_data.get("job_type") or ""),
        "source_code": source_code,
        "source_name": get_source_name(source_code or "unknown"),
        "status": str(row_data.get("status") or "active"),
    }


def _build_job_snapshot_from_crawled_item(item: dict[str, Any], source_code: str) -> dict[str, Any]:
    company_name = str(item.get("brand") or "")
    return {
        "job_id": 0,
        "source_job_id": str(item.get("encrypt_job_id") or ""),
        "title": str(item.get("job_name") or ""),
        "company_name": company_name,
        "company_id": compute_company_id(company_name),
        "city_name": str(item.get("city") or ""),
        "district_name": str(item.get("area") or ""),
        "salary_text": str(item.get("salary") or ""),
        "degree_text": str(item.get("degree") or ""),
        "experience_text": str(item.get("experience") or ""),
        "brand_scale": str(item.get("brand_scale") or ""),
        "brand_stage": str(item.get("brand_stage") or ""),
        "job_type": str(item.get("job_type") or ""),
        "source_code": str(source_code or ""),
        "source_name": get_source_name(str(source_code or "unknown")),
        "status": "active",
    }


def _insert_notification_record(
    conn: sqlite3.Connection,
    *,
    notification_type: str,
    title: str,
    content: str,
    related_job_id: int | None = None,
    related_company_id: int | None = None,
    dedupe_window_hours: int | None = None,
) -> bool:
    if dedupe_window_hours and dedupe_window_hours > 0:
        existing_row = conn.execute(
            """
            SELECT id, created_at
            FROM notifications
            WHERE notification_type = ?
              AND COALESCE(title, '') = ?
              AND COALESCE(content, '') = ?
              AND COALESCE(related_job_id, 0) = COALESCE(?, 0)
              AND COALESCE(related_company_id, 0) = COALESCE(?, 0)
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                notification_type,
                title,
                content,
                related_job_id,
                related_company_id,
            ),
        ).fetchone()
        if existing_row is not None:
            created_at_text = str(existing_row["created_at"] or "").strip()
            if created_at_text:
                try:
                    created_at = datetime.strptime(created_at_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                    if datetime.now(UTC) - created_at <= timedelta(hours=int(dedupe_window_hours)):
                        return False
                except ValueError:
                    return False
    conn.execute(
        """
        INSERT INTO notifications (notification_type, title, content, related_job_id, related_company_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (notification_type, title, content, related_job_id, related_company_id),
    )
    return True


def _create_job_change_event(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    source_code: str,
    event_type: str,
    before_payload: dict[str, Any] | None,
    after_payload: dict[str, Any] | None,
    change_summary: str,
) -> None:
    conn.execute(
        """
        INSERT INTO job_change_events (
            job_id, source_code, event_type, before_payload_json, after_payload_json, change_summary
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            str(source_code or ""),
            str(event_type or "job_updated"),
            json.dumps(before_payload or {}, ensure_ascii=False, sort_keys=True),
            json.dumps(after_payload or {}, ensure_ascii=False, sort_keys=True),
            str(change_summary or ""),
        ),
    )


def _is_internship_like_job(snapshot: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(snapshot.get("title") or ""),
            str(snapshot.get("job_type") or ""),
            str(snapshot.get("experience_text") or ""),
        ]
    ).lower()
    return any(token in haystack for token in ("实习", "校招", "应届", "管培"))


def _saved_search_matches_job(saved_search: sqlite3.Row, snapshot: dict[str, Any]) -> bool:
    keyword = str(saved_search["keyword"] or "").strip().lower()
    city_name = str(saved_search["city_name"] or "").strip().lower()
    filters = _normalize_saved_search_filters(json.loads(str(saved_search["filters_json"] or "{}")))
    title = str(snapshot.get("title") or "").strip().lower()
    company_name = str(snapshot.get("company_name") or "").strip().lower()
    snapshot_city = str(snapshot.get("city_name") or "").strip().lower()
    if keyword and keyword not in title and keyword not in company_name:
        return False
    if city_name and city_name != snapshot_city:
        return False
    if filters.get("source_code") and str(filters.get("source_code") or "").strip().lower() != str(snapshot.get("source_code") or "").strip().lower():
        return False
    if filters.get("degree_text") and str(filters.get("degree_text") or "").strip().lower() != str(snapshot.get("degree_text") or "").strip().lower():
        return False
    if filters.get("experience_text") and str(filters.get("experience_text") or "").strip().lower() != str(snapshot.get("experience_text") or "").strip().lower():
        return False
    if filters.get("internship_only") and not _is_internship_like_job(snapshot):
        return False
    salary_min, salary_max = _parse_salary_range_k(str(snapshot.get("salary_text") or ""))
    if filters.get("salary_min_k"):
        try:
            expected_min = float(filters.get("salary_min_k"))
            if salary_max is None or salary_max < expected_min:
                return False
        except (TypeError, ValueError):
            pass
    if filters.get("salary_max_k"):
        try:
            expected_max = float(filters.get("salary_max_k"))
            if salary_min is not None and salary_min > expected_max:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _dispatch_notifications_for_job_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    before_payload: dict[str, Any] | None,
    after_payload: dict[str, Any] | None,
    change_summary: str,
) -> None:
    snapshot = after_payload or before_payload or {}
    job_id = int(snapshot.get("job_id") or 0)
    if job_id <= 0:
        return
    company_name = str(snapshot.get("company_name") or "")
    title = str(snapshot.get("title") or "")
    city_name = str(snapshot.get("city_name") or "")
    company_id = int(snapshot.get("company_id") or compute_company_id(company_name) or 0) or None

    if event_type == "new_job":
        if company_id is not None:
            favorite_company = conn.execute(
                "SELECT company_id FROM favorite_companies WHERE company_id = ?",
                (company_id,),
            ).fetchone()
            if favorite_company is not None:
                _insert_notification_record(
                    conn,
                    notification_type="company_new_job",
                    title="你收藏的企业有新岗位",
                    content=f"{company_name} 新增岗位：{title}{'（' + city_name + '）' if city_name else ''}",
                    related_job_id=job_id,
                    related_company_id=company_id,
                    dedupe_window_hours=EVENT_NOTIFICATION_DEDUPE_WINDOW_HOURS,
                )

        saved_search_rows = conn.execute(
            """
            SELECT id, keyword, city_name, filters_json
            FROM saved_searches
            WHERE enabled = 1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        for row in saved_search_rows:
            if not _saved_search_matches_job(row, snapshot):
                continue
            label_parts = [str(row["keyword"] or "").strip(), str(row["city_name"] or "").strip()]
            label = " / ".join(part for part in label_parts if part) or "当前筛选"
            _insert_notification_record(
                conn,
                notification_type="new_job",
                title="新职位匹配你的订阅",
                content=f"发现新的 {title} · {company_name}{'（' + city_name + '）' if city_name else ''}，命中订阅“{label}”。",
                related_job_id=job_id,
                related_company_id=company_id,
                dedupe_window_hours=EVENT_NOTIFICATION_DEDUPE_WINDOW_HOURS,
            )
        return

    favorite_job = conn.execute("SELECT job_id FROM favorite_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if favorite_job is None:
        return

    if event_type == "job_closed":
        _insert_notification_record(
            conn,
            notification_type="job_closed",
            title="你收藏的职位已下线",
            content=f"{company_name} / {title} 已被标记为下线。{change_summary}",
            related_job_id=job_id,
            related_company_id=company_id,
            dedupe_window_hours=EVENT_NOTIFICATION_DEDUPE_WINDOW_HOURS,
        )
        return

    _insert_notification_record(
        conn,
        notification_type="job_updated",
        title="你收藏的职位有更新",
        content=f"{company_name} / {title} 有新变化。{change_summary}",
        related_job_id=job_id,
        related_company_id=company_id,
        dedupe_window_hours=EVENT_NOTIFICATION_DEDUPE_WINDOW_HOURS,
    )


def _compute_unique_hash(source_code: str, company_name: str, title: str, city_name: str) -> str:
    raw = f"{source_code}|{company_name}|{title}|{city_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compute_content_hash(title: str, salary_text: str, description_text: str) -> str:
    raw = f"{title}|{salary_text}|{description_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def sync_crawled_jobs(
    jobs: list[dict[str, str]],
    source_code: str = "boss",
) -> dict[str, int]:
    """将爬虫抓取的职位列表同步到数据库，返回 {new, updated, unchanged} 计数。"""
    stats = {"new": 0, "updated": 0, "unchanged": 0}

    with get_connection() as conn:
        for item in jobs:
            title = item.get("job_name", "")
            company = item.get("brand", "")
            city = item.get("city", "")

            if not title or not company:
                continue

            u_hash = _compute_unique_hash(source_code, company, title, city)
            c_hash = _compute_content_hash(title, item.get("salary", ""), "")

            existing = conn.execute(
                """
                SELECT id, source_job_id, title, company_name, city_name, district_name,
                       salary_text, degree_text, experience_text, brand_scale, brand_stage,
                       job_type, content_hash, source_code, status
                FROM jobs
                WHERE unique_hash = ?
                """,
                (u_hash,),
            ).fetchone()

            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (
                        source_job_id, title, company_name, city_name, district_name,
                        salary_text, degree_text, experience_text, brand_scale, brand_stage,
                        job_type, unique_hash, content_hash, source_code, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
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
                        u_hash,
                        c_hash,
                        source_code,
                    ),
                )
                stats["new"] += 1
                new_job_id = cursor.lastrowid

                after_payload = _build_job_snapshot_from_crawled_item(item, source_code)
                after_payload["job_id"] = int(new_job_id)
                summary = f"新增职位：{company} / {title}{'（' + city + '）' if city else ''}"
                _create_job_change_event(
                    conn,
                    job_id=int(new_job_id),
                    source_code=source_code,
                    event_type="new_job",
                    before_payload=None,
                    after_payload=after_payload,
                    change_summary=summary,
                )
                _dispatch_notifications_for_job_event(
                    conn,
                    event_type="new_job",
                    before_payload=None,
                    after_payload=after_payload,
                    change_summary=summary,
                )

            elif existing["content_hash"] != c_hash:
                before_payload = _build_job_snapshot_from_row(existing)
                conn.execute(
                    """
                    UPDATE jobs SET
                        salary_text = ?, degree_text = ?, experience_text = ?,
                        brand_scale = ?, brand_stage = ?, job_type = ?,
                        content_hash = ?, last_seen_at = CURRENT_TIMESTAMP,
                        status = 'active',
                        offline_verification_status = '',
                        offline_verification_reason = '',
                        offline_verified_at = ''
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

                after_payload = {
                    **before_payload,
                    "salary_text": str(item.get("salary") or ""),
                    "degree_text": str(item.get("degree") or ""),
                    "experience_text": str(item.get("experience") or ""),
                    "brand_scale": str(item.get("brand_scale") or ""),
                    "brand_stage": str(item.get("brand_stage") or ""),
                    "job_type": str(item.get("job_type") or ""),
                    "status": "active",
                }
                if before_payload.get("salary_text") != after_payload.get("salary_text"):
                    event_type = "salary_changed"
                    summary = f"薪资由 {before_payload.get('salary_text') or '未知'} 变为 {after_payload.get('salary_text') or '未知'}"
                else:
                    event_type = "job_updated"
                    summary = f"职位信息已更新：{company} / {title}"
                _create_job_change_event(
                    conn,
                    job_id=int(existing["id"]),
                    source_code=source_code,
                    event_type=event_type,
                    before_payload=before_payload,
                    after_payload=after_payload,
                    change_summary=summary,
                )
                _dispatch_notifications_for_job_event(
                    conn,
                    event_type=event_type,
                    before_payload=before_payload,
                    after_payload=after_payload,
                    change_summary=summary,
                )

            else:
                previous_status = str(existing["status"] or "active")
                conn.execute(
                    """
                    UPDATE jobs
                    SET last_seen_at = CURRENT_TIMESTAMP,
                        status = 'active',
                        offline_verification_status = '',
                        offline_verification_reason = '',
                        offline_verified_at = ''
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
                stats["unchanged"] += 1
                if previous_status != "active":
                    before_payload = _build_job_snapshot_from_row(existing)
                    after_payload = {**before_payload, "status": "active"}
                    summary = "职位重新出现在抓取结果中，状态已恢复为在库"
                    _create_job_change_event(
                        conn,
                        job_id=int(existing["id"]),
                        source_code=source_code,
                        event_type="status_changed",
                        before_payload=before_payload,
                        after_payload=after_payload,
                        change_summary=summary,
                    )
                    _dispatch_notifications_for_job_event(
                        conn,
                        event_type="status_changed",
                        before_payload=before_payload,
                        after_payload=after_payload,
                        change_summary=summary,
                    )

        conn.commit()

    return stats


# ── job_tracking (投递跟踪) ────────────────────────────────────────────

def import_job_with_tracking(
    *,
    title: str,
    company_name: str,
    city_name: str = "",
    salary_text: str = "",
    source_url: str = "",
    source_code: str = "imported",
    notes: str = "",
    tracking_status: str = "saved",
) -> dict:
    from app.core.job_sources import get_source_name

    with get_connection() as conn:
        u_hash = _compute_unique_hash(source_code, company_name, title, city_name)
        existing = conn.execute(
            "SELECT id, status FROM jobs WHERE unique_hash = ?", (u_hash,)
        ).fetchone()

        if existing is not None:
            job_id = int(existing["id"])
            if existing["status"] != "active":
                conn.execute(
                    "UPDATE jobs SET status = 'active', last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (job_id,),
                )
        else:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    source_job_id, title, company_name, city_name,
                    salary_text, source_url, source_code, unique_hash, content_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    extract_source_job_id_from_url(source_url, source_code),
                    title,
                    company_name,
                    city_name,
                    salary_text,
                    source_url,
                    source_code,
                    u_hash,
                    _compute_content_hash(title, salary_text, ""),
                ),
            )
            job_id = int(cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO job_tracking (job_id, tracking_status, source_url, notes, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                tracking_status = excluded.tracking_status,
                source_url = CASE WHEN excluded.source_url != '' THEN excluded.source_url ELSE job_tracking.source_url END,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE job_tracking.notes END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (job_id, tracking_status, source_url, notes),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT j.id, j.title, j.company_name, j.city_name, j.salary_text,
                   j.source_url, j.source_code, j.status,
                   t.tracking_status, t.notes, t.applied_at, t.interview_at,
                   t.offer_at, t.result_at, t.result_status,
                   t.created_at, t.updated_at
            FROM jobs j
            JOIN job_tracking t ON t.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()

    return _build_tracking_item(row)


def extract_source_job_id_from_url(url: str, source_code: str) -> str:
    try:
        from app.services.url_platform_detector import extract_source_job_id
        return extract_source_job_id(url, source_code)
    except Exception:
        return ""


def _build_tracking_item(row: Any) -> dict:
    if row is None:
        return {}
    source_code = str(row["source_code"] or "imported")
    return {
        "job_id": int(row["id"]),
        "title": str(row["title"] or ""),
        "company_name": str(row["company_name"] or ""),
        "city_name": str(row["city_name"] or ""),
        "salary_text": str(row["salary_text"] or ""),
        "source_url": str(row["source_url"] or ""),
        "source_code": source_code,
        "source_name": get_source_name(source_code),
        "status": str(row["status"] or "active"),
        "tracking_status": str(row["tracking_status"] or "saved"),
        "notes": str(row["notes"] or ""),
        "applied_at": str(row["applied_at"] or ""),
        "interview_at": str(row["interview_at"] or ""),
        "offer_at": str(row["offer_at"] or ""),
        "result_at": str(row["result_at"] or ""),
        "result_status": str(row["result_status"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def list_tracked_jobs(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    with get_connection() as conn:
        where_sql = ""
        params: list[Any] = []
        if status and status.strip():
            where_sql = " WHERE t.tracking_status = ?"
            params.append(status.strip())

        total = conn.execute(
            f"SELECT COUNT(1) AS count FROM job_tracking t{where_sql}", params
        ).fetchone()["count"]

        offset = max(0, (page - 1)) * page_size
        rows = conn.execute(
            f"""
            SELECT j.id, j.title, j.company_name, j.city_name, j.salary_text,
                   j.source_url, j.source_code, j.status,
                   t.tracking_status, t.notes, t.applied_at, t.interview_at,
                   t.offer_at, t.result_at, t.result_status,
                   t.created_at, t.updated_at
            FROM jobs j
            JOIN job_tracking t ON t.job_id = j.id
            {where_sql}
            ORDER BY t.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        items = [_build_tracking_item(row) for row in rows]
        summary = get_tracking_summary()

    return {
        "items": items,
        "total": int(total),
        "page": int(page),
        "page_size": int(page_size),
        "summary": summary,
    }


def get_tracking_summary() -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT tracking_status, COUNT(1) AS count
            FROM job_tracking
            GROUP BY tracking_status
            """
        ).fetchall()

    summary: dict[str, int] = {
        "saved": 0,
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "accepted": 0,
        "rejected": 0,
    }
    for row in rows:
        status = str(row["tracking_status"] or "")
        count = int(row["count"])
        if status in summary:
            summary[status] = count
    return summary


def update_job_tracking(
    job_id: int,
    *,
    tracking_status: str | None = None,
    notes: str | None = None,
) -> dict | None:
    now_sql = "datetime('now','localtime')"
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT tracking_status FROM job_tracking WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing is None:
            return None

        new_status = tracking_status.strip() if tracking_status else None
        if new_status and new_status == existing["tracking_status"]:
            new_status = None

        set_clauses: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = []

        if new_status:
            set_clauses.append("tracking_status = ?")
            params.append(new_status)

            if new_status == "applied" and not existing["tracking_status"] == "applied":
                set_clauses.append(f"applied_at = COALESCE(NULLIF(applied_at, ''), {now_sql})")
            elif new_status == "interview":
                set_clauses.append(f"interview_at = COALESCE(NULLIF(interview_at, ''), {now_sql})")
            elif new_status == "offer":
                set_clauses.append(f"offer_at = COALESCE(NULLIF(offer_at, ''), {now_sql})")
            elif new_status in ("accepted", "rejected"):
                set_clauses.append(f"result_at = {now_sql}")
                set_clauses.append("result_status = ?")
                params.append(new_status)

        if notes is not None:
            set_clauses.append("notes = ?")
            params.append(notes.strip())

        if len(set_clauses) == 1:
            conn.execute(
                "UPDATE job_tracking SET updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
                (job_id,),
            )
        else:
            params.append(job_id)
            conn.execute(
                f"UPDATE job_tracking SET {', '.join(set_clauses)} WHERE job_id = ?",
                params,
            )
        conn.commit()

        row = conn.execute(
            """
            SELECT j.id, j.title, j.company_name, j.city_name, j.salary_text,
                   j.source_url, j.source_code, j.status,
                   t.tracking_status, t.notes, t.applied_at, t.interview_at,
                   t.offer_at, t.result_at, t.result_status,
                   t.created_at, t.updated_at
            FROM jobs j
            JOIN job_tracking t ON t.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()

    return _build_tracking_item(row) if row else None


def delete_job_tracking(job_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM job_tracking WHERE job_id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0
