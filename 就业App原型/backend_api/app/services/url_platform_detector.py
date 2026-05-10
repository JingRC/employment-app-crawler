from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_PLATFORM_RULES: list[dict[str, Any]] = [
    {
        "source_code": "boss",
        "source_name": "Boss直聘",
        "patterns": [r"zhipin\.com/job_detail/", r"zhipin\.com/web/geek/job"],
    },
    {
        "source_code": "zhilian",
        "source_name": "智联招聘",
        "patterns": [r"zhaopin\.com/jobdetail/", r"jobs\.zhaopin\.com/"],
    },
    {
        "source_code": "job51",
        "source_name": "前程无忧",
        "patterns": [r"51job\.com", r"jobs\.51job\.com"],
    },
    {
        "source_code": "liepin",
        "source_name": "猎聘",
        "patterns": [r"liepin\.com/job/", r"liepin\.com/zhaopin/"],
    },
    {
        "source_code": "shixiseng",
        "source_name": "实习僧",
        "patterns": [r"shixiseng\.com/intern/"],
    },
    {
        "source_code": "guopin",
        "source_name": "国聘",
        "patterns": [r"iguopin\.com/job/"],
    },
    {
        "source_code": "lagou",
        "source_name": "拉勾",
        "patterns": [r"lagou\.com/jobs/", r"lagou\.com/wn/jobs"],
    },
    {
        "source_code": "ncss24365",
        "source_name": "24365大学生就业",
        "patterns": [r"ncss\.cn/student/jobs/"],
    },
    {
        "source_code": "yingjiesheng",
        "source_name": "应届生求职网",
        "patterns": [r"yingjiesheng\.com"],
    },
    {
        "source_code": "niuke_campus",
        "source_name": "牛客校招",
        "patterns": [r"nowcoder\.com"],
    },
    {
        "source_code": "wuba",
        "source_name": "58同城招聘",
        "patterns": [r"58\.com.*job", r"58\.com.*zhaopin"],
    },
    {
        "source_code": "gaoxiaojob",
        "source_name": "高校人才网",
        "patterns": [r"gaoxiaojob\.com"],
    },
]


def detect_platform(url: str) -> dict[str, Any]:
    if not url or not url.strip():
        return {"source_code": "imported", "source_name": "手动导入", "confidence": 0}

    normalized = url.strip()
    try:
        parsed = urlparse(normalized)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        hostname = normalized.lower()

    for rule in _PLATFORM_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, normalized, re.IGNORECASE):
                return {
                    "source_code": rule["source_code"],
                    "source_name": rule["source_name"],
                    "confidence": 1.0,
                }

    for rule in _PLATFORM_RULES:
        source_domain = rule["patterns"][0].split(r"/")[0].replace(r"\.com", ".com")
        if source_domain in hostname:
            return {
                "source_code": rule["source_code"],
                "source_name": rule["source_name"],
                "confidence": 0.5,
            }

    return {"source_code": "imported", "source_name": "手动导入", "confidence": 0}


def extract_source_job_id(url: str, source_code: str) -> str:
    normalized = url.strip()
    extractors: dict[str, Any] = {
        "boss": lambda u: _regex_extract(u, r"/job_detail/([^.?]+)"),
        "zhilian": lambda u: _regex_extract(u, r"/jobdetail/([^.?]+)"),
        "liepin": lambda u: _regex_extract(u, r"/job/([^.?/]+)"),
        "shixiseng": lambda u: _regex_extract(u, r"/intern/([^.?]+)"),
        "guopin": lambda u: _query_param_extract(u, "id"),
        "lagou": lambda u: _regex_extract(u, r"/jobs/([^.?]+)"),
        "ncss24365": lambda u: _regex_extract(u, r"/student/jobs/([^.?]+)"),
        "gaoxiaojob": lambda u: _regex_extract(u, r"/job/([^.?]+)"),
    }
    extractor = extractors.get(source_code)
    if extractor is None:
        return ""
    try:
        return str(extractor(normalized) or "")
    except Exception:
        return ""


def _regex_extract(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def _query_param_extract(text: str, param: str) -> str:
    try:
        parsed = urlparse(text)
        from urllib.parse import parse_qs
        values = parse_qs(parsed.query).get(param, [])
        return values[0] if values else ""
    except Exception:
        return ""
