from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

DXY_JOB_HOME_URL = "https://www.jobmd.cn/"
DXY_JOB_CAMPUS_URL = "https://www.jobmd.cn/campus"
DXY_JOB_FAIR_URL = "https://www.jobmd.cn/article/zph"
DXY_JOB_ARTICLE_URL = "https://www.jobmd.cn/article"

_COMPANY_LINK_PATTERN = re.compile(r"/company/(?:job/|subject/)?\d+\.htm", re.IGNORECASE)
_FAIR_LINK_PATTERN = re.compile(r"/article/zph/\d+|/medical-job-fair/detail/\d+/company", re.IGNORECASE)
_FAIR_DETAIL_LINK_PATTERN = re.compile(r"/medical-job-fair/detail/\d+/company", re.IGNORECASE)
_FAIR_COMPANY_LINK_PATTERN = re.compile(r"/medical-job-fair/company/\d+/\d+", re.IGNORECASE)
_CAREER_NEWS_LINK_PATTERN = re.compile(r"/article/(?:jobs_campus|qtyzzx)/\d+|/company/\d+/\d+\.htm", re.IGNORECASE)
_JOBNOTICE_LINK_PATTERN = re.compile(r"/jobnotice/\d+", re.IGNORECASE)
_COMPANY_NOTICE_LINK_PATTERN = re.compile(r"/company/\d+/\d+\.htm", re.IGNORECASE)
_ARTICLE_NOTICE_LINK_PATTERN = re.compile(r"/article/(?:jobs_campus|qtyzzx|jobs_hospital)/\d+", re.IGNORECASE)
_COMPANY_META_PATTERN = re.compile(
    r"\s+(?:公立医院|民营医院|外资医院|科研院校|其他|医疗器械|医药企业|医药公司|医药研发|医药销售|"
    r"生物化工|医药研发/制药生产|医院/临床医疗|护理院|门诊部|规模不详|\d+~\d+人|\d+人以上|"
    r"三甲|三乙|三级|二甲|二乙|一级|本科起招).*$"
)
_GENERIC_TEXTS = {
    "查看更多职位",
    "查看更多",
    "查看详情",
    "更多",
    "热招单位",
}
_NOTICE_REGION_PATTERN = re.compile(
    r"(新疆维吾尔自治区|广西壮族自治区|宁夏回族自治区|西藏自治区|内蒙古自治区|香港特别行政区|澳门特别行政区|"
    r"[\u4e00-\u9fff]{2,8}省[\u4e00-\u9fff]{0,8}(?:市|州|区|县)?|[\u4e00-\u9fff]{2,8}市[\u4e00-\u9fff]{0,8}(?:区|县)?)"
)
_NOTICE_PUBLISHER_PATTERN = re.compile(
    r"^(.{2,40}?(?:人民医院|医院|卫生院|医学院|学院|大学|中心|委员会|管理局|集团|研究院|公司))"
)
_NOTICE_UNIT_TYPE_KEYWORDS = (
    ("公立医院", "公立医院"),
    ("民营医院", "民营医院"),
    ("外资医院", "外资医院"),
    ("科研院校", "科研院校"),
    ("医药企业", "医药企业"),
    ("医疗器械", "医疗器械"),
    ("事业单位", "事业单位"),
    ("国企", "国企"),
    ("央企", "央企"),
)
_NOTICE_ESTABLISHMENT_KEYWORDS = (
    ("事业单位编制", "事业单位编制"),
    ("事业编制", "事业编制"),
    ("编制", "编制"),
)


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _primary_text(anchor: Tag) -> str:
    title_text = _normalize_whitespace(anchor.get("title") or "")
    if title_text:
        return title_text
    for text in anchor.stripped_strings:
        normalized = _normalize_whitespace(text)
        if normalized:
            return normalized
    return _normalize_whitespace(anchor.get_text(" ", strip=True))


def _cleanup_topic_title(title: str) -> str:
    text = _normalize_whitespace(title)
    text = re.sub(r"^(?:报名中|进行中|最新)\s*[·|｜]\s*", "", text)
    text = re.sub(r"\s+\d{1,2}\s*(?:小时|天)前$", "", text)
    text = re.sub(r"\s+\d{2}-\d{2}$", "", text)
    text = re.sub(r"\s+20\d{2}-\d{2}-\d{2}$", "", text)
    return text.strip(" -_/|，。；;：:")


def _extract_date_text(text: str) -> str:
    normalized = _normalize_whitespace(text)
    match = re.search(r"(20\d{2}-\d{2}-\d{2}|20\d{2}\.\d{2}\.\d{2}|\d{2}-\d{2}|\d+\s*(?:小时|天)前)", normalized)
    return _normalize_whitespace(match.group(1)) if match else ""


def _extract_batch_text(text: str) -> str:
    normalized = _normalize_whitespace(text)
    match = re.search(r"(20\d{2}(?:届|年))", normalized)
    return _normalize_whitespace(match.group(1)) if match else ""


def _extract_text_lines(soup: BeautifulSoup) -> list[str]:
    lines: list[str] = []
    for raw_line in soup.get_text("\n", strip=True).splitlines():
        normalized = _normalize_whitespace(raw_line)
        if normalized:
            lines.append(normalized)
    return lines


def _extract_labeled_value(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if line == label:
            if index + 1 < len(lines):
                return _cleanup_notice_value(lines[index + 1])
            continue
        if line.startswith(label):
            value = re.sub(rf"^{re.escape(label)}\s*[:：]?\s*", "", line)
            value = _cleanup_notice_value(value)
            if value and value != label:
                return value
    return ""


def _cleanup_notice_value(value: str) -> str:
    normalized = _normalize_whitespace(value)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=\d)", "", normalized)
    normalized = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"\s+([，。；：])", r"\1", normalized)
    normalized = re.sub(r"^(?:\d+[、.．]\s*|[（(][一二三四五六七八九十]+[）)]\s*|[一二三四五六七八九十]+[、.．]\s*)", "", normalized)
    return normalized.strip(" -_/|，。,；;：:")


def _extract_notice_region(*texts: str) -> str:
    for text in texts:
        normalized = _normalize_whitespace(text)
        if not normalized:
            continue
        for municipality in ("北京", "上海", "天津", "重庆"):
            if municipality in normalized:
                return municipality + "市"
        match = _NOTICE_REGION_PATTERN.search(normalized)
        if match:
            region = _normalize_whitespace(match.group(1))
            region = re.sub(r"(人民医院|医院|卫生院|医学院|学院|大学|中心|委员会|管理局|集团|研究院|公司).*$", "", region)
            return _normalize_whitespace(region)
    return ""


def _extract_notice_publisher(title: str, page_text: str) -> str:
    for text in (title, page_text):
        normalized = _normalize_whitespace(text)
        if not normalized:
            continue
        match = _NOTICE_PUBLISHER_PATTERN.search(normalized)
        if match:
            return _normalize_whitespace(match.group(1))
    return ""


def _extract_notice_keyword(text: str, keyword_map: tuple[tuple[str, str], ...]) -> str:
    normalized = _normalize_whitespace(text)
    for keyword, label in keyword_map:
        if keyword in normalized:
            return label
    return ""


def _extract_notice_person(page_text: str) -> str:
    match = re.search(r"联系人\s*[:：]?\s*([^。；;\s]{1,24})", page_text)
    return _cleanup_notice_value(match.group(1)) if match else ""


def _extract_notice_phone(page_text: str) -> str:
    match = re.search(r"(?:联系电话|咨询电话|监督电话)\s*[:：]?\s*([^。；;]{2,80})", page_text)
    return _cleanup_notice_value(match.group(1)) if match else ""


def _extract_notice_position_summary(page_text: str) -> str:
    matches = re.findall(r"([\u4e00-\u9fffA-Za-z0-9]+岗位，?职数\d+名)", page_text)
    if matches:
        unique_matches: list[str] = []
        for match in matches:
            cleaned = _cleanup_notice_value(match)
            if cleaned and cleaned not in unique_matches:
                unique_matches.append(cleaned)
        return "；".join(unique_matches[:5])
    summary_match = re.search(r"(?:招聘岗位和人数|岗位和人数)\s*[:：]?\s*([^。]{8,180})", page_text)
    return _cleanup_notice_value(summary_match.group(1)) if summary_match else ""


def _extract_notice_requirement_summary(page_text: str, keyword: str) -> str:
    normalized = _normalize_whitespace(page_text)
    keyword_index = normalized.find(keyword)
    if keyword_index < 0:
        return ""

    start = 0
    for separator in ("。", "；", ";", "！", "？"):
        separator_index = normalized.rfind(separator, 0, keyword_index)
        if separator_index >= 0:
            start = max(start, separator_index + 1)

    end = len(normalized)
    for separator in ("；", ";"):
        separator_index = normalized.find(separator, keyword_index)
        if separator_index >= 0:
            end = min(end, separator_index)

    snippet = _cleanup_notice_value(normalized[start:end])
    if keyword not in snippet:
        return ""
    if any(noise in snippet for noise in ("首页职位", "丁香人才网_", "职场论坛", "热招地区")):
        return ""
    if keyword == "专业要求" and "。" in snippet:
        snippet = _cleanup_notice_value(snippet.split("。", 1)[0])
    return snippet


def _build_topic_item(
    *,
    title: str,
    group_name: str,
    topic_source_kind: str,
    source_url: str,
    source_page_url: str,
    industry: str = "医疗医药",
    recruitment_stage: str = "",
    collected_at_text: str = "",
    application_period_text: str = "",
) -> dict[str, str]:
    cleaned_title = _cleanup_topic_title(title)
    return {
        "company_name": cleaned_title,
        "group_name": group_name,
        "industry": industry,
        "scale_text": "",
        "city_text": "",
        "official_site_url": "",
        "career_site_url": source_page_url,
        "description_text": f"从丁香人才公开专题同步，补充医疗行业专题与公告入口。原始标题：{cleaned_title}",
        "source_url": source_url,
        "source_page_url": source_page_url,
        "topic_source_kind": topic_source_kind,
        "recruitment_batch": _extract_batch_text(cleaned_title),
        "recruitment_stage": recruitment_stage,
        "collected_at_text": collected_at_text,
        "application_period_text": application_period_text,
    }


def _build_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _match_group(anchor: Tag) -> tuple[str, str]:
    href = str(anchor.get("href") or "")
    anchor_class = " ".join(anchor.get("class", []))
    parent_class = " ".join(anchor.parent.get("class", [])) if isinstance(anchor.parent, Tag) else ""
    joined_class = f"{anchor_class} {parent_class}"
    if "/company/job/" in href:
        return "丁香人才医院招聘计划", "hospital_plan"
    if "BannerArea_" in joined_class:
        return "丁香人才横幅专题", "banner_topic"
    if "PureRow_root__" in joined_class:
        return "丁香人才推荐单位", "recommended_unit"
    if "EntSingleJob_root__" in joined_class:
        return "丁香人才紧急招聘", "urgent_unit"
    if "EntDoubleJob_" in joined_class:
        return "丁香人才热招单位", "hot_unit"
    return "丁香人才首页专题", "homepage_topic"


def _cleanup_company_name(anchor: Tag) -> str:
    title_text = _primary_text(anchor)
    raw_text = title_text or _normalize_whitespace(anchor.get_text(" ", strip=True))
    text = raw_text.replace("最新人才招聘计划", " ")
    text = re.sub(r"\s+诚聘.*$", " ", text)
    text = re.sub(r"\s+招聘.*$", " ", text)
    text = _COMPANY_META_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -_/|，。；;：:")
    if not text:
        return ""
    if text in _GENERIC_TEXTS:
        return ""
    return _normalize_whitespace(text)


def _cleanup_company_name_text(text: str) -> str:
    normalized = _normalize_whitespace(text)
    normalized = re.sub(r"\s+\d+\s*个?参展职位$", "", normalized)
    normalized = normalized.replace("查看单位详情", " ")
    normalized = re.sub(
        r"\s+[^\s]+\s+(?:公立医院|民营医院|外资医院|社区卫生服务中心|医疗诊所|政府机构|国企|央企|股份制医院|科研院校|健康管理|规模不详|\d+~\d+人|\d+人以上).*$",
        "",
        normalized,
    )
    normalized = _COMPANY_META_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" -_/|，。；;：:")
    return normalized


def _is_company_like(name: str) -> bool:
    text = _normalize_whitespace(name)
    if not text or text in _GENERIC_TEXTS:
        return False
    if len(text) < 3:
        return False
    if any(keyword in text for keyword in ("职位", "登录", "注册", "搜索", "首页")):
        return False
    return True


def _is_topic_like(title: str) -> bool:
    text = _cleanup_topic_title(title)
    if not text:
        return False
    if len(text) < 4:
        return False
    if any(keyword in text for keyword in ("登录", "注册", "搜索", "首页", "去购买", "去使用")):
        return False
    return True


def parse_dxy_job_homepage_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _COMPANY_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(DXY_JOB_HOME_URL, raw_href)
        if source_page_url in seen_page_urls:
            continue

        company_name = _cleanup_company_name(anchor)
        if not _is_company_like(company_name):
            continue

        group_name, topic_source_kind = _match_group(anchor)
        raw_title = _normalize_whitespace(anchor.get_text(" ", strip=True))
        items.append(
            {
                "company_name": company_name,
                "group_name": group_name,
                "industry": "医疗医药",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": source_page_url,
                "description_text": f"从丁香人才首页公开专题同步，补充医疗行业单位目录与招聘计划入口。原始标题：{raw_title}",
                "source_url": DXY_JOB_HOME_URL,
                "source_page_url": source_page_url,
                "topic_source_kind": topic_source_kind,
            }
        )
        seen_page_urls.add(source_page_url)

    return items


def parse_dxy_job_campus_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _COMPANY_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(DXY_JOB_CAMPUS_URL, raw_href)
        if source_page_url in seen_page_urls:
            continue

        company_name = _cleanup_company_name(anchor)
        if not _is_company_like(company_name):
            continue

        items.append(
            {
                "company_name": company_name,
                "group_name": "丁香人才校招专题",
                "industry": "医疗医药",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": source_page_url,
                "description_text": f"从丁香人才校招页公开专题同步，补充医疗行业校招单位与招聘计划入口。原始标题：{_primary_text(anchor)}",
                "source_url": DXY_JOB_CAMPUS_URL,
                "source_page_url": source_page_url,
                "topic_source_kind": "campus_company",
                "recruitment_batch": _extract_batch_text(_primary_text(anchor)),
            }
        )
        seen_page_urls.add(source_page_url)

    return items


def parse_dxy_job_campus_notice_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _JOBNOTICE_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(DXY_JOB_CAMPUS_URL, raw_href)
        if source_page_url in seen_page_urls:
            continue

        title = _cleanup_topic_title(_normalize_whitespace(anchor.get_text(" ", strip=True)))
        if not _is_topic_like(title):
            continue

        context_text = _normalize_whitespace(anchor.parent.get_text(" ", strip=True)) if isinstance(anchor.parent, Tag) else title
        items.append(
            _build_topic_item(
                title=title,
                group_name="丁香人才校招招聘公告",
                topic_source_kind="campus_jobnotice",
                source_url=DXY_JOB_CAMPUS_URL,
                source_page_url=source_page_url,
                recruitment_stage="报名中" if "报名中" in context_text else "公告",
                collected_at_text=_extract_date_text(context_text),
            )
        )
        seen_page_urls.add(source_page_url)

    return items


def parse_dxy_job_fair_featured_companies(html: str, *, source_url: str = DXY_JOB_FAIR_URL) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _FAIR_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(source_url, raw_href)
        if source_page_url in seen_page_urls:
            continue

        title = _primary_text(anchor)
        if not _is_topic_like(title):
            continue

        context_text = _normalize_whitespace(anchor.parent.get_text(" ", strip=True)) if isinstance(anchor.parent, Tag) else title
        countdown_match = re.search(r"距结束还有[^\s]+", context_text)
        items.append(
            _build_topic_item(
                title=title,
                group_name="丁香人才双选会",
                topic_source_kind="job_fair_article",
                source_url=source_url,
                source_page_url=source_page_url,
                recruitment_stage="进行中" if "进行中" in context_text else "",
                collected_at_text=_extract_date_text(context_text),
                application_period_text=_normalize_whitespace(countdown_match.group(0)) if countdown_match else "",
            )
        )
        seen_page_urls.add(source_page_url)

    return items


def extract_dxy_job_fair_detail_urls(html: str, *, source_url: str = DXY_JOB_CAMPUS_URL) -> list[str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _FAIR_DETAIL_LINK_PATTERN.search(raw_href):
            continue
        full_url = urljoin(source_url, raw_href)
        if full_url not in urls:
            urls.append(full_url)
    return urls


def parse_dxy_job_fair_company_featured_companies(
    html: str,
    *,
    source_url: str,
    fair_title: str = "",
) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()
    page_text = _normalize_whitespace(soup.get_text(" ", strip=True))
    detail_title = _cleanup_topic_title(fair_title or (soup.title.get_text(" ", strip=True) if soup.title else ""))
    status = "进行中" if "进行中" in page_text else ""
    period_match = re.search(r"(20\d{2}/\d{2}/\d{2}\s*\d{2}:\d{2}\s*-\s*20\d{2}/\d{2}/\d{2}\s*\d{2}:\d{2})", page_text)
    period_text = _normalize_whitespace(period_match.group(1)) if period_match else ""

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _FAIR_COMPANY_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(source_url, raw_href)
        if source_page_url in seen_page_urls:
            continue

        company_name = _cleanup_company_name_text(_primary_text(anchor))
        if not _is_company_like(company_name):
            continue

        items.append(
            {
                "company_name": company_name,
                "group_name": "丁香人才双选会参展单位",
                "industry": "医疗医药",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": source_page_url,
                "description_text": f"从丁香人才双选会详情页同步参展单位清单。双选会：{detail_title or '未命名双选会'}。原始标题：{_primary_text(anchor)}",
                "source_url": source_url,
                "source_page_url": source_page_url,
                "topic_source_kind": "job_fair_company",
                "recruitment_batch": _extract_batch_text(detail_title),
                "recruitment_stage": status,
                "application_period_text": period_text,
            }
        )
        seen_page_urls.add(source_page_url)

    return items


def parse_dxy_job_career_news_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not _CAREER_NEWS_LINK_PATTERN.search(raw_href):
            continue

        source_page_url = urljoin(DXY_JOB_ARTICLE_URL, raw_href)
        if source_page_url in seen_page_urls:
            continue

        title = _primary_text(anchor)
        if not _is_topic_like(title):
            continue

        context_text = _normalize_whitespace(anchor.parent.get_text(" ", strip=True)) if isinstance(anchor.parent, Tag) else title
        if "/article/jobs_campus/" in raw_href:
            group_name = "丁香人才校招公告"
            topic_source_kind = "campus_news"
        else:
            group_name = "丁香人才求职快讯"
            topic_source_kind = "career_news"

        items.append(
            _build_topic_item(
                title=title,
                group_name=group_name,
                topic_source_kind=topic_source_kind,
                source_url=DXY_JOB_ARTICLE_URL,
                source_page_url=source_page_url,
                recruitment_stage="公告",
                collected_at_text=_extract_date_text(context_text),
            )
        )
        seen_page_urls.add(source_page_url)

    return items


def fetch_dxy_job_homepage_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(DXY_JOB_HOME_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_homepage_featured_companies(response.text)


def fetch_dxy_job_campus_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(DXY_JOB_CAMPUS_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_campus_featured_companies(response.text)


def fetch_dxy_job_campus_notice_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(DXY_JOB_CAMPUS_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_campus_notice_featured_companies(response.text)


def fetch_dxy_job_fair_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(DXY_JOB_FAIR_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_fair_featured_companies(response.text)


def fetch_dxy_job_career_news_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(DXY_JOB_ARTICLE_URL, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_career_news_featured_companies(response.text)


def fetch_dxy_job_fair_company_featured_companies(timeout: int = 20, max_detail_pages: int = 8) -> list[dict[str, str]]:
    campus_response = requests.get(DXY_JOB_CAMPUS_URL, timeout=timeout, headers=_build_headers())
    campus_response.raise_for_status()
    detail_urls = extract_dxy_job_fair_detail_urls(campus_response.text, source_url=DXY_JOB_CAMPUS_URL)

    items: list[dict[str, str]] = []
    seen_page_urls: set[str] = set()
    for detail_url in detail_urls[: max(1, max_detail_pages)]:
        detail_response = requests.get(detail_url, timeout=timeout, headers=_build_headers())
        detail_response.raise_for_status()
        detail_items = parse_dxy_job_fair_company_featured_companies(detail_response.text, source_url=detail_url)
        for item in detail_items:
            source_page_url = str(item.get("source_page_url") or "").strip()
            if not source_page_url or source_page_url in seen_page_urls:
                continue
            items.append(item)
            seen_page_urls.add(source_page_url)

    return items


def is_dxy_job_notice_detail_url(source_page_url: str) -> bool:
    normalized = str(source_page_url or "").strip()
    return bool(
        _JOBNOTICE_LINK_PATTERN.search(normalized)
        or _COMPANY_NOTICE_LINK_PATTERN.search(normalized)
        or _ARTICLE_NOTICE_LINK_PATTERN.search(normalized)
    )


def parse_dxy_job_notice_detail_meta(html: str, *, source_page_url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    lines = _extract_text_lines(soup)
    page_text = " ".join(lines)
    title = ""
    title_node = soup.find(["h1", "title"])
    if isinstance(title_node, Tag):
        title = _cleanup_topic_title(title_node.get_text(" ", strip=True))
    if not title:
        title = _cleanup_topic_title(_extract_labeled_value(lines, "标题"))

    notice_source_kind = "jobnotice_detail" if _JOBNOTICE_LINK_PATTERN.search(source_page_url) else "company_notice_detail"
    notice_publisher = _extract_labeled_value(lines, "发布单位") or _extract_notice_publisher(title, page_text)
    notice_location = _extract_labeled_value(lines, "工作地点") or _extract_labeled_value(lines, "工作地区")
    notice_publish_date = _extract_labeled_value(lines, "日期") or _extract_labeled_value(lines, "发布时间")
    application_period_text = _extract_labeled_value(lines, "报名时间")
    notice_deadline = _extract_labeled_value(lines, "报名截止时间")
    notice_contact_person = _extract_labeled_value(lines, "联系人")
    notice_contact_phone = _extract_labeled_value(lines, "联系电话") or _extract_labeled_value(lines, "咨询电话")
    notice_apply_method = _extract_labeled_value(lines, "报名方式")
    notice_position_summary = _extract_labeled_value(lines, "招聘岗位和人数") or _extract_labeled_value(lines, "岗位和人数")
    notice_degree_requirement = _extract_labeled_value(lines, "学历要求")
    notice_major_requirement = _extract_labeled_value(lines, "专业要求")

    if not notice_publish_date:
        publish_match = re.search(r"(?:日期|发布时间)\s*[:：]?\s*(20\d{2}[./-]\d{1,2}[./-]\d{1,2})", page_text)
        if publish_match:
            notice_publish_date = _cleanup_notice_value(publish_match.group(1))
    if not application_period_text:
        period_match = re.search(r"报名时间\s*[:：]?\s*([^。；;]{4,120})", page_text)
        if period_match:
            application_period_text = _cleanup_notice_value(period_match.group(1))
    if not notice_deadline:
        deadline_match = re.search(r"报名截止时间\s*[:：]?\s*([0-9０-９\-/.年月日\s:：]{4,40})", page_text)
        if deadline_match:
            notice_deadline = _cleanup_notice_value(deadline_match.group(1))
    if not notice_contact_person:
        notice_contact_person = _extract_notice_person(page_text)
    if not notice_contact_phone:
        notice_contact_phone = _extract_notice_phone(page_text)
    if not notice_apply_method:
        apply_method_match = re.search(r"报名方式\s*[:：]?\s*([^。；;]{4,120})", page_text)
        if apply_method_match:
            notice_apply_method = _cleanup_notice_value(apply_method_match.group(1))
    if not notice_position_summary:
        notice_position_summary = _extract_notice_position_summary(page_text)
    degree_requirement_from_text = _extract_notice_requirement_summary(page_text, "学历要求") or _extract_notice_requirement_summary(page_text, "学历")
    if len(degree_requirement_from_text) > len(notice_degree_requirement):
        notice_degree_requirement = degree_requirement_from_text
    major_requirement_from_text = _extract_notice_requirement_summary(page_text, "专业要求") or _extract_notice_requirement_summary(page_text, "专业")
    if len(major_requirement_from_text) > len(notice_major_requirement):
        notice_major_requirement = major_requirement_from_text

    notice_region = _extract_notice_region(notice_location, notice_publisher, title)
    notice_unit_type = _extract_notice_keyword(page_text + " " + title, _NOTICE_UNIT_TYPE_KEYWORDS)
    notice_establishment = _extract_notice_keyword(page_text + " " + title, _NOTICE_ESTABLISHMENT_KEYWORDS)

    return {
        "notice_publisher": _cleanup_notice_value(notice_publisher),
        "notice_location": _cleanup_notice_value(notice_location),
        "notice_region": _cleanup_notice_value(notice_region),
        "notice_unit_type": _cleanup_notice_value(notice_unit_type),
        "notice_establishment": _cleanup_notice_value(notice_establishment),
        "notice_publish_date": _cleanup_notice_value(notice_publish_date),
        "notice_deadline": _cleanup_notice_value(notice_deadline),
        "notice_contact_person": _cleanup_notice_value(notice_contact_person),
        "notice_contact_phone": _cleanup_notice_value(notice_contact_phone),
        "notice_apply_method": _cleanup_notice_value(notice_apply_method),
        "notice_position_summary": _cleanup_notice_value(notice_position_summary),
        "notice_degree_requirement": _cleanup_notice_value(notice_degree_requirement),
        "notice_major_requirement": _cleanup_notice_value(notice_major_requirement),
        "notice_detail_url": str(source_page_url or "").strip(),
        "notice_source_kind": notice_source_kind,
        "application_period_text": _cleanup_notice_value(application_period_text),
    }


def fetch_dxy_job_notice_detail_meta(source_page_url: str, timeout: int = 20) -> dict[str, str]:
    normalized_url = str(source_page_url or "").strip()
    if not is_dxy_job_notice_detail_url(normalized_url):
        return {}
    response = requests.get(normalized_url, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_dxy_job_notice_detail_meta(response.text, source_page_url=normalized_url)