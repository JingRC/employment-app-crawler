from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

YINGJIESHENG_HOME_URL = "https://www.yingjiesheng.com/"
YINGJIESHENG_DEADLINE_URL = "https://www.yingjiesheng.com/deadline/"

YINGJIESHENG_TOPIC_HOST_KEYWORDS = (
    "q.yingjiesheng.com/thirdlink",
    "campus.51job.com/",
    "xyzp.51job.com/",
    "xyz.51job.com/",
    "jobs.51job.com/all/co",
)

YINGJIESHENG_NON_COMPANY_TITLE_PATTERN = re.compile(
    r"Deadline|更多名企大厂职位|倒计时|看过来|专场|精选|招人了|职位|搜索|首页|登录",
    re.IGNORECASE,
)

YINGJIESHENG_COMPANY_SUFFIX_PATTERN = re.compile(
    r"集团|银行|证券|保险|基金|科技|纸业|半导体|有限公司|股份有限公司|股份|电力|化学工业|中国平安|中国太平|中国中煤|中粮|李宁|华住|鄂尔多斯|倍耐力|丝芙兰|宝能|招商银行|光大|哈尔滨银行|金光纸业|厦门银行|顺芯|朗致|心连心|渤海银行|东吴证券|江苏省农村商业银行系统|中国核能电力",
)


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _build_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _decode_deadline_response_text(response: requests.Response) -> str:
    return response.content.decode("gb18030", errors="ignore")


def _extract_redirect_target(href: str) -> tuple[str, str]:
    full_url = urljoin(YINGJIESHENG_HOME_URL, str(href or "").strip())
    parsed = urlparse(full_url)
    query = parse_qs(parsed.query)
    raw_target = str((query.get("url") or [""])[0] or "").strip()
    return full_url, unquote(raw_target) if raw_target else full_url


def _looks_like_topic_anchor(title: str, href: str) -> bool:
    normalized_title = _normalize_whitespace(title)
    normalized_href = str(href or "").strip().lower()
    if not normalized_title or normalized_href.startswith("javascript:"):
        return False
    if any(keyword in normalized_href for keyword in YINGJIESHENG_TOPIC_HOST_KEYWORDS):
        return True
    return False


def _cleanup_company_name(title: str) -> str:
    text = _normalize_whitespace(title)
    text = re.sub(r"^【[^】]+】", " ", text)
    text = re.sub(r"20\d{2}(?:届)?", " ", text)
    text = re.sub(r"\b\d{2}(?:届)?\b", " ", text)
    text = re.sub(r"春季校园招聘|春季校招|校园招聘|校园 招聘|春招|秋招|校招|招聘|实习生|工作人员", " ", text)
    text = re.sub(r"\b\d+名\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_/|，。；;：:")
    return _normalize_whitespace(text)


def _is_company_like(title: str, company_name: str) -> bool:
    normalized_title = _normalize_whitespace(title)
    normalized_name = _normalize_whitespace(company_name)
    if not normalized_name:
        return False
    if YINGJIESHENG_NON_COMPANY_TITLE_PATTERN.search(normalized_title):
        return False
    if normalized_name in {"无忧", "企业", "银行投资公司", "Deadline", "更多名企大厂"}:
        return False
    if YINGJIESHENG_COMPANY_SUFFIX_PATTERN.search(normalized_name):
        return True
    if re.search(r"[A-Za-z]{2,}", normalized_name):
        return True
    return len(normalized_name) >= 3 and not re.search(r"专场|精选|看过来|倒计时", normalized_name)


def parse_yingjiesheng_homepage_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_company_names: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_title = _normalize_whitespace(anchor.get_text(" ", strip=True))
        raw_href = str(anchor.get("href") or "").strip()
        if not _looks_like_topic_anchor(raw_title, raw_href):
            continue

        company_name = _cleanup_company_name(raw_title)
        if not _is_company_like(raw_title, company_name):
            continue

        dedupe_key = company_name.lower()
        if dedupe_key in seen_company_names:
            continue

        source_page_url, career_site_url = _extract_redirect_target(raw_href)
        items.append(
            {
                "company_name": company_name,
                "group_name": "应届生首页专题",
                "industry": "",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": career_site_url,
                "description_text": f"从应届生首页企业专题同步，优先补齐校招专题与投递入口。原始标题：{raw_title}",
                "source_url": YINGJIESHENG_HOME_URL,
                "source_page_url": source_page_url,
                "topic_source_kind": "homepage_topic",
            }
        )
        seen_company_names.add(dedupe_key)

    return items


def parse_yingjiesheng_deadline_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_company_names: set[str] = set()
    current_deadline_text = ""

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        cell_texts = [_normalize_whitespace(cell.get_text(" ", strip=True)) for cell in cells]
        joined_text = " ".join(text for text in cell_texts if text)
        if not joined_text:
            continue

        if re.search(r"20\d{2}\.\d{2}\.\d{2}.*倒计时", joined_text):
            current_deadline_text = joined_text
            continue

        first_anchor = row.find("a", href=True)
        if first_anchor is None:
            continue

        raw_title = _normalize_whitespace(first_anchor.get_text(" ", strip=True))
        if not raw_title or "校园招聘" not in raw_title:
            continue

        company_name = _cleanup_company_name(raw_title)
        if not _is_company_like(raw_title, company_name):
            continue

        dedupe_key = company_name.lower()
        if dedupe_key in seen_company_names:
            continue

        source_page_url = urljoin(YINGJIESHENG_HOME_URL, str(first_anchor.get("href") or "").strip())
        deadline_date_match = re.search(r"(20\d{2}\.\d{2}\.\d{2})", current_deadline_text)
        countdown_match = re.search(r"倒计时[:：]?(\d+天)", current_deadline_text)
        deadline_date_text = deadline_date_match.group(1) if deadline_date_match else ""
        countdown_text = countdown_match.group(1) if countdown_match else ""
        application_period_text = " ".join(part for part in [deadline_date_text, countdown_text] if part).strip()

        items.append(
            {
                "company_name": company_name,
                "group_name": "应届生截止专题",
                "industry": "",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": source_page_url,
                "description_text": f"从应届生 deadline 首页同步，优先补齐截止日期专题与投递入口。原始标题：{raw_title}",
                "source_url": YINGJIESHENG_DEADLINE_URL,
                "source_page_url": source_page_url,
                "topic_source_kind": "deadline_active",
                "recruitment_stage": "进行中",
                "application_period_text": application_period_text,
                "collected_at_text": deadline_date_text,
            }
        )
        seen_company_names.add(dedupe_key)

    return items


def fetch_yingjiesheng_homepage_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(YINGJIESHENG_HOME_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_yingjiesheng_homepage_featured_companies(response.text)


def fetch_yingjiesheng_deadline_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(YINGJIESHENG_DEADLINE_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_yingjiesheng_deadline_featured_companies(_decode_deadline_response_text(response))