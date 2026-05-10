from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_API_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_API_DIR.parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_DIR = BACKEND_API_DIR / "data"
SUMMARY_PATH = DATA_DIR / "cloud_sync_last_result.json"

for candidate in (str(BACKEND_API_DIR), str(WORKSPACE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.core.database import init_database  # noqa: E402


DEFAULT_SOURCE_CODES = ["qdhr", "qlrc", "sdgxbys", "sdgxbys_campus", "ncss24365", "jobmohrss", "healthr", "healthr_doctor", "buildhr", "chenhr", "jxhg_chenhr", "mhg_chenhr", "sysh_chenhr", "newenergy_chenhr", "sales_chenhr", "doctor_healthr", "pha_healthr", "env_buildhr", "construct_buildhr", "qingdao_rc", "rcsd_talents", "niuke_campus", "yingjiesheng", "dxy_job", "gaoxiaojob", "wuba"]
DISABLED_SOURCE_MARKERS = {"", "none", "off", "skip", "disabled", "disable", "false", "0"}

REQUESTS_ONLY_REGION_GROUPS: list[dict[str, Any]] = [
    {"label": "north-core", "cities": ["北京", "天津", "石家庄", "太原", "呼和浩特"]},
    {"label": "northeast-core", "cities": ["沈阳", "长春", "哈尔滨"]},
    {"label": "east-core", "cities": ["上海", "南京", "杭州", "合肥", "福州", "南昌", "济南"]},
    {"label": "central-core", "cities": ["郑州", "武汉", "长沙"]},
    {"label": "south-core", "cities": ["广州", "深圳", "南宁", "海口"]},
    {"label": "southwest-core", "cities": ["成都", "重庆", "贵阳", "昆明", "拉萨"]},
    {"label": "northwest-core", "cities": ["西安", "兰州", "西宁", "银川", "乌鲁木齐"]},
]

JOBMOHRSS_OFFICIAL_QUERIES = ["Java", "Python", "前端", "测试", "运营", "销售", "工程师", "会计", "行政", "人力资源", "市场"]

ALL_REGION_CITIES: list[str] = []
for region_group in REQUESTS_ONLY_REGION_GROUPS:
    for city in region_group["cities"]:
        if city not in ALL_REGION_CITIES:
            ALL_REGION_CITIES.append(city)

WUBA_ALL_CITIES: list[str] = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆",
    "天津", "苏州", "郑州", "长沙", "东莞", "青岛", "济南", "合肥", "福州", "厦门",
    "大连", "沈阳", "宁波", "昆明", "石家庄", "哈尔滨", "长春", "无锡", "佛山",
]


REQUESTS_ONLY_PRESETS: dict[str, dict[str, Any]] = {
    "qdhr": {
        "module_name": "qdhr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 8,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 45,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "shandong-tech",
                "queries": ["工程师", "研发", "技术", "Java", "Python", "前端"],
                "cities": ["青岛", "济南", "烟台", "潍坊", "威海"],
            },
            {
                "label": "shandong-business",
                "queries": ["销售", "运营", "市场", "实施", "招聘", "管理"],
                "cities": ["青岛", "济南", "烟台", "潍坊", "威海"],
            },
            {
                "label": "shandong-support",
                "queries": ["人力资源", "行政", "财务", "质量", "采购", "法务"],
                "cities": ["青岛", "济南", "烟台", "潍坊", "威海"],
            },
        ],
    },
    "qlrc": {
        "module_name": "qlrc_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "shandong-tech",
                "queries": ["工程师", "Java", "前端", "测试", "技术员", "研发"],
                "cities": ["山东"],
            },
            {
                "label": "shandong-business",
                "queries": ["销售", "运营", "市场", "人力资源", "财务"],
                "cities": ["山东"],
            },
            {
                "label": "major-cities-tech",
                "queries": ["工程师", "技术员", "研发", "Java"],
                "cities": ["青岛", "济南", "烟台", "潍坊", "淄博", "临沂"],
            },
            {
                "label": "major-cities-business",
                "queries": ["销售", "运营", "市场", "人事"],
                "cities": ["青岛", "济南", "烟台", "潍坊", "淄博", "临沂"],
            },
        ],
    },
    "sdgxbys": {
        "module_name": "sdgxbys_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "shandong-tech",
                "queries": ["工程师", "技术", "Java", "前端", "研发", "测试"],
                "cities": ["山东"],
            },
            {
                "label": "shandong-business",
                "queries": ["销售", "运营", "市场", "招聘", "财务", "管理"],
                "cities": ["山东"],
            },
            {
                "label": "shandong-education-medical",
                "queries": ["教师", "医生", "护士", "会计", "设计"],
                "cities": ["山东"],
            },
            {
                "label": "major-cities-universal",
                "queries": ["工程师", "技术", "销售", "运营", "管理", "财务"],
                "cities": ["青岛", "济南", "烟台", "潍坊"],
            },
        ],
    },
    "ncss24365": {
        "module_name": "ncss24365_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 10,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
            "allow_empty_query": True,
        },
        "task_groups": [
            {
                "label": f"{group['label']}-all-jobs",
                "queries": [""],
                "cities": list(group["cities"]),
            }
            for group in REQUESTS_ONLY_REGION_GROUPS
        ],
    },
    "jobmohrss": {
        "module_name": "jobmohrss_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 2,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
            "search_type": "2",
        },
        "task_groups": [
            {
                "label": f"{group['label']}-public",
                "queries": list(JOBMOHRSS_OFFICIAL_QUERIES),
                "cities": list(group["cities"]),
            }
            for group in REQUESTS_ONLY_REGION_GROUPS
        ],
    },
    "healthr": {
        "module_name": "healthr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "all-cities-sales",
                "queries": ["销售", "推广", "招商"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "all-cities-rd-qa",
                "queries": ["研发", "注册", "临床", "QA", "QC"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "national-rd-sales",
                "queries": ["研发", "注册", "临床", "QA", "QC", "医生", "药剂师", "销售", "推广", "招商", "渠道"],
                "cities": ["全国"],
            },
        ],
    },
    "healthr_doctor": {
        "module_name": "healthr_doctor_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "all-cities-clinical",
                "queries": ["医生", "护士", "医师", "内科", "药师", "中医", "外科"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "national-doctor-full",
                "queries": ["医生", "护士", "医师", "内科", "药师", "检验", "影像", "中医", "外科"],
                "cities": ["全国"],
            },
        ],
    },
    "buildhr": {
        "module_name": "buildhr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "all-cities-design",
                "queries": ["建筑师", "预算员", "造价工程师", "BIM工程师"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "all-cities-construction",
                "queries": ["施工员", "安全员", "监理工程师", "结构工程师", "项目经理"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "national-build-full",
                "queries": ["建筑师", "项目经理", "造价工程师", "施工员", "安全员", "监理工程师", "结构工程师", "BIM工程师"],
                "cities": ["全国"],
            },
        ],
    },
    "chenhr": {
        "module_name": "chenhr_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "all-cities-chem-rd",
                "queries": ["研发工程师", "工艺工程师", "设备工程师", "生产经理"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "all-cities-chem-support",
                "queries": ["安全工程师", "质检", "电气工程师", "自动化", "仪表"],
                "cities": list(ALL_REGION_CITIES),
            },
            {
                "label": "national-chem-full",
                "queries": ["研发工程师", "工艺工程师", "设备工程师", "安全工程师", "生产经理", "化工", "质检", "电气工程师", "自动化", "仪表"],
                "cities": ["全国"],
            },
        ],
    },
    "jxhg_chenhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-fine-chem",
                "queries": ["工程师", "技术员", "操作工", "研发"],
                "cities": ["全国"],
            },
        ],
    },
    "mhg_chenhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-coal-chem",
                "queries": ["工程师", "技术员", "操作工"],
                "cities": ["全国"],
            },
        ],
    },
    "sysh_chenhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-petrochem",
                "queries": ["工程师", "技术员", "安全工程师"],
                "cities": ["全国"],
            },
        ],
    },
    "newenergy_chenhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-newenergy",
                "queries": ["工程师", "技术员", "研发", "项目经理"],
                "cities": ["全国"],
            },
        ],
    },
    "sales_chenhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-chem-sales",
                "queries": ["销售经理", "销售工程师", "客户经理"],
                "cities": ["全国"],
            },
        ],
    },
    "doctor_healthr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-doctor-sub",
                "queries": ["医生", "医师", "主任医师", "主治医师"],
                "cities": ["全国"],
            },
        ],
    },
    "pha_healthr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-pharmacy",
                "queries": ["药师", "营业员", "店长", "药剂师"],
                "cities": ["全国"],
            },
        ],
    },
    "env_buildhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-env",
                "queries": ["环评工程师", "环保工程师", "环境检测", "环境工程"],
                "cities": ["全国"],
            },
        ],
    },
    "construct_buildhr": {
        "module_name": "yingcai_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 25,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "national-construct-sub",
                "queries": ["施工员", "项目经理", "安全员", "技术员"],
                "cities": ["全国"],
            },
        ],
    },
    "qingdao_rc": {
        "module_name": "qingdao_rc_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "qingdao-tech",
                "queries": ["Java", "Python", "前端", "测试", "工程师", "研发"],
                "cities": ["青岛"],
            },
            {
                "label": "qingdao-business",
                "queries": ["销售", "运营", "市场", "行政", "财务"],
                "cities": ["青岛"],
            },
            {
                "label": "qingdao-general",
                "queries": ["会计", "人力资源", "管理", "设计", "实施"],
                "cities": ["青岛"],
            },
        ],
    },
    "rcsd_talents": {
        "module_name": "rcsd_talents_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 15,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "shandong-talents",
                "queries": ["招聘", "引才", "项目经理", "技术支持", "工程师", "研究员"],
                "cities": ["山东", "济南", "青岛"],
            },
        ],
    },
    "sdgxbys_campus": {
        "module_name": "sdgxbys_campus_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 4,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
        "task_groups": [
            {
                "label": "shandong-campus",
                "queries": ["招聘", "校园", "公告", "医院", "国企", "教师"],
                "cities": ["山东", "济南", "青岛", "烟台"],
            },
        ],
    },
    "niuke_campus": {
        "module_name": "niuke_campus_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": [],
        "cities": [],
        "max_pages": 1,
        "source_options": {
            "detail_mode": "list_only",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
    },
    "yingjiesheng": {
        "module_name": "yingjiesheng_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": [],
        "cities": [],
        "max_pages": 1,
        "source_options": {
            "detail_mode": "list_only",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
    },
    "dxy_job": {
        "module_name": "dxy_job_joblist_crawl",
        "runner_name": "run_incremental_update",
        "queries": [],
        "cities": [],
        "max_pages": 1,
        "source_options": {
            "detail_mode": "list_only",
            "request_timeout_seconds": 30,
            "sleep_seconds": 0.0,
        },
    },
    "gaoxiaojob": {
        "module_name": "gaoxiaojob_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 5,
        "source_options": {
            "detail_mode": "list_only",
            "request_timeout_seconds": 25.0,
            "sleep_seconds": 0.5,
            "page_size": 12,
        },
        "task_groups": [
            {
                "label": "education-gov-enterprise",
                "queries": ["1", "2", "4", "6"],
                "cities": ["0"],
            },
            {
                "label": "sci-med-highlevel",
                "queries": ["3", "5", "9"],
                "cities": ["0"],
            },
            {
                "label": "postdoc-edu-admin",
                "queries": ["11", "12", "13", "14", "23", "24", "38"],
                "cities": ["0"],
            },
        ],
    },
    "wuba": {
        "module_name": "wuba_joblist_crawl",
        "runner_name": "run_incremental_update",
        "max_pages": 3,
        "source_options": {
            "detail_mode": "detail_html",
            "request_timeout_seconds": 30,
            "sleep_seconds": 1.5,
        },
        "task_groups": [
            {
                "label": "general-labor",
                "queries": ["普工", "操作工", "学徒工", "包装工"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "driver-logistics",
                "queries": ["司机", "快递", "物流", "分拣", "装卸", "配送"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "service-retail",
                "queries": ["服务员", "收银", "店员", "理货", "客服", "促销"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "security-cleaning",
                "queries": ["保安", "保洁", "环卫", "绿化"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "skilled-trade",
                "queries": ["焊工", "电工", "钳工", "木工", "油漆工", "泥瓦工", "管道工", "暖通"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "catering",
                "queries": ["厨师", "帮厨", "切配", "面点师", "配菜"],
                "cities": list(WUBA_ALL_CITIES),
            },
            {
                "label": "warehouse-equipment",
                "queries": ["叉车工", "铲车工", "搬运工", "仓库管理员"],
                "cities": list(WUBA_ALL_CITIES),
            },
        ],
    },
    "boss": {
        "module_name": "zhipin_dp_crawl_v2",
        "runner_name": "run_incremental_update",
        "max_pages": 1,
        "source_options": {
            "browser_preference": "chrome",
            "browser_profile": "Default",
            "use_system_profile": False,
            "conservative_first_round": True,
            "first_round_page_cap": 1,
            "auto_expand_after_stable": False,
            "homepage_warmup_seconds": 8,
            "result_page_warmup_seconds": 6,
            "defer_high_risk_pairs": True,
            "high_risk_pairs": [],
        },
        "task_groups": [
            {
                "label": "metro-tech",
                "queries": ["Java", "Python", "前端", "测试"],
                "cities": ["北京", "上海", "深圳", "杭州"],
            },
            {
                "label": "metro-business",
                "queries": ["运营", "销售", "产品"],
                "cities": ["北京", "上海", "深圳", "杭州"],
            },
        ],
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run requests-only cloud sync presets.")
    parser.add_argument("--sources", help="Comma-separated source codes, or 'none' to skip all sources.")
    parser.add_argument(
        "--validate-startup",
        action="store_true",
        help="Only validate startup, database initialization, and summary writing without running any source.",
    )
    return parser.parse_args(argv)


def resolve_sources(raw: str | None = None) -> list[str]:
    if raw is None:
        return list(DEFAULT_SOURCE_CODES)

    normalized_raw = str(raw).replace("\n", ",")
    items = [item.strip().lower() for item in normalized_raw.split(",")]
    filtered_items = [item for item in items if item]
    if not filtered_items:
        return []
    if any(item in DISABLED_SOURCE_MARKERS for item in filtered_items):
        return []

    unknown_items = [item for item in filtered_items if item not in REQUESTS_ONLY_PRESETS]
    if unknown_items:
        raise ValueError(f"未知的 CLOUD_SYNC_SOURCES 来源: {', '.join(unknown_items)}")

    deduped_items: list[str] = []
    for item in filtered_items:
        if item not in deduped_items:
            deduped_items.append(item)
    return deduped_items


def resolve_sources_from_env() -> list[str]:
    env_value = os.getenv("CLOUD_SYNC_SOURCES")
    return resolve_sources(env_value)


def load_runner(source_code: str):
    preset = REQUESTS_ONLY_PRESETS[source_code]
    module = importlib.import_module(str(preset["module_name"]))
    return getattr(module, str(preset["runner_name"]))


def build_preset_runs(source_code: str, preset: dict[str, Any]) -> list[dict[str, Any]]:
    task_groups = list(preset.get("task_groups") or [])
    if not task_groups:
        return [
            {
                "label": source_code,
                "queries": list(preset["queries"]),
                "cities": list(preset["cities"]),
                "max_pages": int(preset["max_pages"]),
                "source_options": dict(preset["source_options"]),
            }
        ]

    runs: list[dict[str, Any]] = []
    for index, group in enumerate(task_groups, start=1):
        runs.append(
            {
                "label": str(group.get("label") or f"{source_code}-{index}"),
                "queries": list(group.get("queries") or []),
                "cities": list(group.get("cities") or []),
                "max_pages": int(group.get("max_pages") or preset["max_pages"]),
                "source_options": dict(preset["source_options"]),
            }
        )
    return runs


def merge_source_results(source_code: str, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "source_code": source_code,
        "total_fetched": 0,
        "new_to_db": 0,
        "updated": 0,
        "sub_runs": [],
    }
    resolved_city_codes: dict[str, str] = {}
    fallback_locations: list[str] = []
    empty_locations: list[str] = []
    request_trace: list[dict[str, Any]] = []
    request_summary = {
        "total_targets": 0,
        "resolved_targets": 0,
        "fallback_targets": 0,
        "empty_targets": 0,
    }

    for run_result in run_results:
        merged["total_fetched"] += int(run_result.get("total_fetched") or 0)
        merged["new_to_db"] += int(run_result.get("new_to_db") or 0)
        merged["updated"] += int(run_result.get("updated") or run_result.get("updated_in_db") or 0)
        merged["sub_runs"].append(run_result)
        resolved_city_codes.update(dict(run_result.get("resolved_city_codes") or {}))
        for city in list(run_result.get("fallback_to_national_locations") or []):
            if city not in fallback_locations:
                fallback_locations.append(city)
        for city in list(run_result.get("empty_result_locations") or []):
            if city not in empty_locations:
                empty_locations.append(city)
        request_trace.extend(list(run_result.get("request_trace") or []))
        summary = dict(run_result.get("request_summary") or {})
        for key in request_summary:
            request_summary[key] += int(summary.get(key) or 0)

    if resolved_city_codes:
        merged["resolved_city_codes"] = resolved_city_codes
    if fallback_locations:
        merged["fallback_to_national_locations"] = fallback_locations
    if empty_locations:
        merged["empty_result_locations"] = empty_locations
    if request_trace:
        merged["request_trace"] = request_trace
        merged["request_summary"] = request_summary
    return merged


def emit_console(message: str) -> None:
    print(message, flush=True)


def run_cloud_sync(selected_sources: list[str] | None = None, validate_startup: bool = False) -> dict[str, Any]:
    emit_console("[cloud-sync] 初始化数据库")
    init_database()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    resolved_sources = list(selected_sources) if selected_sources is not None else resolve_sources_from_env()
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    total_fetched = 0
    total_new = 0
    total_updated = 0

    if validate_startup:
        emit_console("[cloud-sync] 启动验证模式，不执行真实抓取")
        resolved_sources = []
    elif not resolved_sources:
        emit_console("[cloud-sync] 未选择任何来源，跳过抓取")

    for source_code in resolved_sources:
        preset = REQUESTS_ONLY_PRESETS[source_code]
        emit_console(f"[cloud-sync] 开始执行来源: {source_code}")
        try:
            runner = load_runner(source_code)
            run_results: list[dict[str, Any]] = []
            for run_config in build_preset_runs(source_code, preset):
                emit_console(
                    f"[cloud-sync] 执行分组: {source_code}/{run_config['label']} queries={','.join(run_config['queries'])} cities={','.join(run_config['cities'])}"
                )
                run_result = runner(
                    queries=list(run_config["queries"]),
                    cities=list(run_config["cities"]),
                    max_pages=int(run_config["max_pages"]),
                    source_options=dict(run_config["source_options"]),
                    **({"source_code": source_code} if "source_code" in inspect.signature(runner).parameters else {}),
                )
                run_results.append(
                    {
                        **dict(run_result),
                        "run_label": run_config["label"],
                        "run_queries": list(run_config["queries"]),
                        "run_cities": list(run_config["cities"]),
                        "run_max_pages": int(run_config["max_pages"]),
                    }
                )
            result = merge_source_results(source_code, run_results)
            source_result = {
                "source_code": source_code,
                "status": "success",
                "total_fetched": int(result.get("total_fetched", 0) or 0),
                "new_to_db": int(result.get("new_to_db", 0) or 0),
                "updated_in_db": int(result.get("updated_in_db", result.get("updated", 0)) or 0),
                "details": result,
            }
            emit_console(
                f"[cloud-sync] 来源完成: {source_code} fetched={source_result['total_fetched']} new={source_result['new_to_db']} updated={source_result['updated_in_db']}"
            )
        except Exception as exc:
            source_result = {
                "source_code": source_code,
                "status": "failed",
                "error": str(exc),
                "total_fetched": 0,
                "new_to_db": 0,
                "updated_in_db": 0,
            }
            emit_console(f"[cloud-sync] 来源失败: {source_code} error={exc}")
        results.append(source_result)
        total_fetched += int(source_result.get("total_fetched", 0) or 0)
        total_new += int(source_result.get("new_to_db", 0) or 0)
        total_updated += int(source_result.get("updated_in_db", 0) or 0)

    finished_at = datetime.now(timezone.utc)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "selected_sources": resolved_sources,
        "validate_startup": bool(validate_startup),
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_updated": total_updated,
        "results": results,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_console(f"[cloud-sync] 摘要已写入: {SUMMARY_PATH}")
    return summary


if __name__ == "__main__":
    args = parse_args()
    selected_sources = resolve_sources(args.sources) if args.sources is not None else None
    result = run_cloud_sync(selected_sources=selected_sources, validate_startup=bool(args.validate_startup))
    print(json.dumps(result, ensure_ascii=False, indent=2))