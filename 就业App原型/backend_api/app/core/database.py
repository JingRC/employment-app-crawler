import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.core.job_sources import get_source_name

CODE_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "jobs.db"
SAMPLE_JSON_PATH = CODE_ROOT / "提交" / "joblist_Java_101120200.json"

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def set_job_stale_hours(stale_after_hours: int | None) -> int:
    global _JOB_STALE_HOURS
    normalized = max(int(stale_after_hours or DEFAULT_JOB_STALE_HOURS), 1)
    _JOB_STALE_HOURS = normalized
    return _JOB_STALE_HOURS


def get_job_stale_hours() -> int:
    return int(_JOB_STALE_HOURS)


def get_featured_board_name(board_code: str) -> str:
    normalized = (board_code or "").strip().lower()
    return FEATURED_BOARD_LABELS.get(normalized, normalized or "未分组")


def get_featured_company_type_name(company_type: str) -> str:
    normalized = (company_type or "").strip().lower()
    return FEATURED_COMPANY_TYPE_LABELS.get(normalized, normalized or "未分类")


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

    where_clauses: list[str] = []
    params: list[Any] = []
    if normalized_status != "all":
        where_clauses.append("status = ?")
        params.append(normalized_status)

    normalized_verification_status = (offline_verification_status or "").strip().lower()
    if normalized_verification_status and normalized_verification_status != "all":
        where_clauses.append("COALESCE(offline_verification_status, '') = ?")
        params.append(normalized_verification_status)

    if keyword:
        keyword_like = f"%{keyword.lower()}%"
        where_clauses.append(
            "(" 
            "LOWER(title) LIKE ? OR LOWER(company_name) LIKE ? OR LOWER(description_text) LIKE ? OR LOWER(job_type) LIKE ?"
            ")"
        )
        params.extend([keyword_like, keyword_like, keyword_like, keyword_like])
    if city_name:
        where_clauses.append("city_name = ?")
        params.append(city_name)
    if source_code:
        where_clauses.append("source_code = ?")
        params.append(source_code)
    if degree_text:
        where_clauses.append("degree_text = ?")
        params.append(degree_text)
    if experience_text:
        where_clauses.append("experience_text = ?")
        params.append(experience_text)
    if internship_only:
        where_clauses.append(
            "(" 
            "title LIKE '%实习%' OR title LIKE '%兼职%' OR title LIKE '%应届%' OR "
            "experience_text LIKE '%在校%' OR experience_text LIKE '%应届%' OR job_type LIKE '%实习%' OR description_text LIKE '%实习%'"
            ")"
        )

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, company_name, city_name, salary_text, degree_text, official_apply_url, source_code, job_type, experience_text, status, last_seen_at, offline_verification_status, offline_verified_at
            FROM jobs
            {where_sql}
            """,
            params,
        ).fetchall()

    normalized_sort = (sort_by or "latest").strip().lower() or "latest"
    items: list[dict[str, Any]] = []
    for row in rows:
        parsed_salary_min, parsed_salary_max = _parse_salary_range_k(str(row["salary_text"] or ""))
        if salary_min_k is not None:
            comparable_max = parsed_salary_max if parsed_salary_max is not None else parsed_salary_min
            if comparable_max is None or comparable_max < salary_min_k:
                continue
        if salary_max_k is not None:
            comparable_min = parsed_salary_min if parsed_salary_min is not None else parsed_salary_max
            if comparable_min is None or comparable_min > salary_max_k:
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
) -> dict[str, Any]:
    mark_stale_jobs_inactive()

    normalized_status = (status or "active").strip().lower() or "active"
    if normalized_status not in {"active", "inactive", "all"}:
        normalized_status = "active"
    normalized_focus_source_code = (focus_source_code or "").strip().lower() or None

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

    total_jobs = len(rows)
    companies: set[str] = set()
    cities: set[str] = set()
    salary_values: list[float] = []
    source_counts: dict[str, int] = {}
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
    focus_profile: dict[str, Any] | None = None
    if normalized_focus_source_code:
        focus_profile = {
            "source_code": normalized_focus_source_code,
            "source_name": get_source_name(normalized_focus_source_code),
            "total_jobs": 0,
            "companies": set(),
            "cities": set(),
            "districts": set(),
            "salary_values": [],
            "district_counts": {},
            "company_counts": {},
            "job_type_counts": {},
        }

    for row in rows:
        company_name = str(row["company_name"] or "").strip()
        city_name = str(row["city_name"] or "").strip()
        district_name = str(row["district_name"] or "").strip()
        source_code = str(row["source_code"] or "unknown").strip() or "unknown"
        salary_text = str(row["salary_text"] or "")
        job_type = str(row["job_type"] or "").strip()
        last_seen_at = str(row["last_seen_at"] or "").strip()

        if company_name:
            companies.add(company_name)
        if city_name:
            cities.add(city_name)
            city_bucket = city_metrics.setdefault(city_name, {"job_count": 0, "salary_values": []})
            city_bucket["job_count"] += 1

        source_counts[source_code] = source_counts.get(source_code, 0) + 1

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

        if focus_profile is not None and source_code.lower() == normalized_focus_source_code:
            focus_profile["total_jobs"] += 1
            if company_name:
                focus_profile["companies"].add(company_name)
                focus_profile["company_counts"][company_name] = focus_profile["company_counts"].get(company_name, 0) + 1
            if city_name:
                focus_profile["cities"].add(city_name)
            normalized_district = district_name or "未标注"
            focus_profile["districts"].add(normalized_district)
            focus_profile["district_counts"][normalized_district] = focus_profile["district_counts"].get(normalized_district, 0) + 1
            normalized_job_type = job_type or "未标注"
            focus_profile["job_type_counts"][normalized_job_type] = focus_profile["job_type_counts"].get(normalized_job_type, 0) + 1
            if comparable_salary is not None:
                focus_profile["salary_values"].append(float(comparable_salary))

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
            "job_count": count,
        }
        for source_code, count in source_counts.items()
    ]
    source_distribution.sort(key=lambda item: (-int(item["job_count"]), str(item["source_name"])))

    salary_distribution = [
        {"label": label, "job_count": count}
        for label, count in salary_band_counts.items()
    ]

    average_salary_k = round(sum(salary_values) / len(salary_values), 1) if salary_values else None
    focus_source_profile = None
    if focus_profile is not None and int(focus_profile["total_jobs"] or 0) > 0:
        focus_salary_values = list(focus_profile["salary_values"])
        focus_source_profile = {
            "source_code": focus_profile["source_code"],
            "source_name": focus_profile["source_name"],
            "total_jobs": int(focus_profile["total_jobs"]),
            "total_companies": len(focus_profile["companies"]),
            "total_cities": len(focus_profile["cities"]),
            "total_districts": len(focus_profile["districts"]),
            "average_salary_k": round(sum(focus_salary_values) / len(focus_salary_values), 1) if focus_salary_values else None,
            "salary_sample_count": len(focus_salary_values),
            "district_distribution": _build_analytics_breakdown(focus_profile["district_counts"], top_n),
            "company_distribution": _build_analytics_breakdown(focus_profile["company_counts"], top_n),
            "job_type_distribution": _build_analytics_breakdown(focus_profile["job_type_counts"], top_n),
        }

    return {
        "overview": {
            "total_jobs": total_jobs,
            "total_companies": len(companies),
            "total_cities": len(cities),
            "average_salary_k": average_salary_k,
            "salary_sample_count": len(salary_values),
            "recent_24h_count": recent_24h_count,
            "recent_7d_count": recent_7d_count,
            "status_scope": normalized_status,
        },
        "city_distribution": city_distribution[: max(int(top_n or 12), 1)],
        "source_distribution": source_distribution,
        "salary_distribution": salary_distribution,
        "focus_source_profile": focus_source_profile,
    }


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
            SELECT id
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
            conn.commit()

    return {
        "inactive_marked": len(stale_ids),
        "stale_after_hours": normalized_hours,
        "cutoff_time": cutoff_text,
    }


def verify_pending_inactive_jobs(
    limit: int = DEFAULT_OFFLINE_STRONG_CHECK_LIMIT,
    timeout_seconds: float = DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    normalized_limit = max(int(limit or DEFAULT_OFFLINE_STRONG_CHECK_LIMIT), 0)
    normalized_timeout = max(float(timeout_seconds or DEFAULT_OFFLINE_STRONG_CHECK_TIMEOUT_SECONDS), 1.0)
    if normalized_limit == 0:
        return {
            "verified_count": 0,
            "restored_count": 0,
            "confirmed_count": 0,
            "review_count": 0,
            "missing_url_count": 0,
            "limit": normalized_limit,
            "timeout_seconds": normalized_timeout,
        }

    with get_connection() as conn:
        pending_rows = conn.execute(
            """
            SELECT id, source_url, official_apply_url
            FROM jobs
            WHERE status = 'inactive' AND COALESCE(offline_verification_status, '') = 'pending'
            ORDER BY last_seen_at ASC, id ASC
            LIMIT ?
            """,
            (normalized_limit,),
        ).fetchall()

        stats = {
            "verified_count": 0,
            "restored_count": 0,
            "confirmed_count": 0,
            "review_count": 0,
            "missing_url_count": 0,
            "limit": normalized_limit,
            "timeout_seconds": normalized_timeout,
        }
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
                   official_site_url, career_site_url, last_seen_at
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
                 description_text, official_site_url, career_site_url, last_seen_at
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


def mark_notification_read(notification_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,),
        )
        conn.commit()
    return cursor.rowcount > 0


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
                "SELECT id, content_hash FROM jobs WHERE unique_hash = ?",
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

                # 为新职位生成通知
                conn.execute(
                    """
                    INSERT INTO notifications (notification_type, title, content, related_job_id)
                    VALUES ('new_job', ?, ?, ?)
                    """,
                    (
                        "新职位发现",
                        f"{company} 发布了 {title}（{city}）",
                        new_job_id,
                    ),
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

                # 为更新的职位生成通知
                conn.execute(
                    """
                    INSERT INTO notifications (notification_type, title, content, related_job_id)
                    VALUES ('job_updated', ?, ?, ?)
                    """,
                    (
                        "职位信息更新",
                        f"{title}（{company}）信息已更新",
                        existing["id"],
                    ),
                )

            else:
                conn.execute(
                    "UPDATE jobs SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (existing["id"],),
                )
                stats["unchanged"] += 1

        conn.commit()

    return stats
