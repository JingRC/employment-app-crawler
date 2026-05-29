from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

NIUKE_CAMPUS_HOME_URL = "https://www.nowcoder.com/"
NIUKE_CAMPUS_SCHEDULE_URL = "https://www.nowcoder.com/jobs/school/schedule"
NIUKE_NOWPICK_BASE_URL = "https://nowpick.nowcoder.com"
NIUKE_CAMPUS_SCHEDULE_LIST_API = f"{NIUKE_NOWPICK_BASE_URL}/u/school-schedule/list-card"

NIUKE_BATCH_PATTERN = re.compile(r"(?:\d{2}(?:/\d{2})?届(?:实习|校招)?|\d{2}(?:/\d{2})?(?:春招|秋招)|春招|秋招|实习|校招|训练营|提前批)")
NIUKE_STAGE_PATTERN = re.compile(r"(?:网申中|网申[:：]?\s*未开始|未开始|内推中|招聘中|补录中|进行中|已截止)")
NIUKE_APPLICATION_PERIOD_PATTERN = re.compile(r"网申时间[:：]\s*([^\n\r]+?)\s*(?:招聘城市[:：]|招聘岗位[:：]|$)")
NIUKE_NON_COMPANY_NAME_PATTERN = re.compile(r"实\s*习\s*交流|网申\s*助手|AI\s*网申\s*助手")


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value or "").replace("→", " ").split())


def _clean_company_name(value: str) -> str:
    text = _normalize_whitespace(value).replace("官网投递", "").replace("立即投递", "").strip()
    return text


def _extract_redirect_target(href: str) -> tuple[str, dict[str, str]]:
    full_url = urljoin(NIUKE_CAMPUS_HOME_URL, str(href or "").strip())
    parsed = urlparse(full_url)
    query = parse_qs(parsed.query)
    raw_target = str((query.get("url") or [""])[0] or "").strip()
    target_url = unquote(raw_target) if raw_target else full_url
    metadata = {
        "company_id": str((query.get("companyId") or [""])[0] or "").strip(),
        "entity_id": str((query.get("entityId") or [""])[0] or "").strip(),
        "source_url": full_url,
    }
    return target_url, metadata


def _build_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _build_nowpick_api_headers() -> dict[str, str]:
    headers = _build_headers()
    headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nowcoder.com",
            "Referer": NIUKE_CAMPUS_SCHEDULE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    return headers


def _decode_response_text(response: requests.Response) -> str:
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _extract_anchor_text(anchor: BeautifulSoup) -> str:
    return _normalize_whitespace(anchor.get_text(" ", strip=True))


def _cleanup_schedule_company_name(value: str) -> str:
    text = _clean_company_name(value)
    for prefix in ("收藏 ", "已收藏 ", "收藏", "已收藏"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    text = re.split(r"[，。；;]", text, maxsplit=1)[0].strip()
    tokens = [token.strip() for token in text.split(" ") if token.strip()]
    if not tokens:
        return ""

    descriptor_keywords = ("龙头", "领先", "投入", "成长", "空间", "平台", "方案", "能力", "覆盖", "岗位", "机会", "全球", "标杆", "领先", "转型", "稳健", "一手", "海量", "显著", "总部", "全国性", "第一品牌", "十强")
    corporate_keywords = ("集团", "银行", "基金", "研发", "研究院", "研究所", "有限公司", "股份", "科技", "系统", "保险", "产险", "汽车", "大学", "学院", "医院")
    name_tokens: list[str] = [tokens[0]]
    for token in tokens[1:]:
        if any(symbol in token for symbol in ("，", "。", "；", ",", ";", "：", ":")):
            break
        if any(keyword in token for keyword in descriptor_keywords):
            break
        if any(keyword in token for keyword in corporate_keywords) or len(token) <= 6:
            name_tokens.append(token)
            if len(name_tokens) >= 3:
                break
            continue
        break
    return _normalize_whitespace(" ".join(name_tokens))


def _is_non_company_schedule_name(value: str) -> bool:
    return bool(NIUKE_NON_COMPANY_NAME_PATTERN.search(_normalize_whitespace(value)))


def _format_niuke_timestamp_date(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return ""
    try:
        normalized = int(timestamp_ms) / 1000
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(normalized).strftime("%Y/%m/%d")


def _format_niuke_collected_at_text(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return ""
    try:
        normalized = int(timestamp_ms) / 1000
    except (TypeError, ValueError):
        return ""
    date_text = datetime.fromtimestamp(normalized).strftime("%m.%d")
    return f"{date_text}收录"


def _build_niuke_schedule_application_period_text(item: dict[str, object]) -> str:
    begin_date = _format_niuke_timestamp_date(item.get("wangshenBeginDate"))
    end_date = _format_niuke_timestamp_date(item.get("wangshenEndDate"))
    if begin_date and end_date:
        return f"{begin_date} ~ {end_date}"
    return begin_date or end_date


def _derive_niuke_schedule_recruitment_stage(item: dict[str, object]) -> str:
    if bool(item.get("end")):
        return "已截止"
    begin_date = _format_niuke_timestamp_date(item.get("wangshenBeginDate"))
    end_date = _format_niuke_timestamp_date(item.get("wangshenEndDate"))
    if not begin_date and not end_date:
        return ""
    return "网申中"


def _build_niuke_schedule_enterprise_url(company_id: object) -> str:
    normalized_company_id = str(company_id or "").strip()
    if not normalized_company_id:
        return ""
    return urljoin(NIUKE_CAMPUS_HOME_URL, f"/enterprise/{normalized_company_id}?pageSource=5014&channel=recruitmentSchedule")


def _build_niuke_schedule_jump_url(company_id: object, ad_info: dict[str, object]) -> str:
    normalized_company_id = str(company_id or ad_info.get("companyId") or "").strip()
    if not normalized_company_id:
        return ""
    raw_url = str(
        ad_info.get("specialWangshenLink")
        or ad_info.get("customWangshenLink")
        or ad_info.get("rawUrl")
        or ""
    ).strip()
    entity_id = str(ad_info.get("id") or normalized_company_id).strip()
    source_value = "113" if bool(ad_info.get("cardListTop")) else "102"
    if not raw_url:
        return _build_niuke_schedule_enterprise_url(normalized_company_id)
    return urljoin(
        NIUKE_CAMPUS_HOME_URL,
        f"/jump?type=ad&source={source_value}&companyId={normalized_company_id}&entityId={entity_id}&url={requests.utils.quote(raw_url, safe='')}",
    )


def parse_niuke_campus_schedule_api_items(items: list[dict[str, object]]) -> list[dict[str, str]]:
    parsed_items: list[dict[str, str]] = []
    seen_company_names: set[str] = set()

    for item in items:
        raw_name = _normalize_whitespace(str(item.get("name") or "").strip())
        company_name = _cleanup_schedule_company_name(raw_name)
        if not company_name or _is_non_company_schedule_name(raw_name) or _is_non_company_schedule_name(company_name):
            continue

        dedupe_key = company_name.lower()
        if dedupe_key in seen_company_names:
            continue

        ad_info = item.get("adInfo") if isinstance(item.get("adInfo"), dict) else {}
        company_id = str(item.get("companyId") or ad_info.get("companyId") or "").strip()
        batch_name = _normalize_whitespace(str(item.get("batchName") or ""))
        recruitment_stage = _derive_niuke_schedule_recruitment_stage(item)
        collected_at_text = _format_niuke_collected_at_text(item.get("wangshenUpdateTime") or item.get("updateTime"))
        application_period_text = _build_niuke_schedule_application_period_text(item)
        city_text = _normalize_whitespace("、".join(str(city).strip() for city in (item.get("cityList") or []) if str(city).strip()))
        career_site_url = str(
            ad_info.get("specialWangshenLink")
            or item.get("customWangshenLink")
            or ad_info.get("rawUrl")
            or _build_niuke_schedule_enterprise_url(company_id)
        ).strip()
        source_page_url = _build_niuke_schedule_jump_url(company_id, {**ad_info, "cardListTop": bool(item.get("cardListTop"))}) if ad_info else _build_niuke_schedule_enterprise_url(company_id)
        apply_label = "官网投递" if ad_info else "立即投递"

        description_parts = ["从牛客校招日程接口同步"]
        if batch_name:
            description_parts.append(batch_name)
        if recruitment_stage:
            description_parts.append(recruitment_stage)
        if collected_at_text:
            description_parts.append(collected_at_text)

        parsed_items.append(
            {
                "company_name": company_name,
                "group_name": "牛客校招日程",
                "industry": _normalize_whitespace("、".join(str(value).strip() for value in (item.get("industryList") or []) if str(value).strip())),
                "scale_text": "",
                "city_text": city_text,
                "official_site_url": "",
                "career_site_url": career_site_url,
                "description_text": "，".join(description_parts) + "，优先补齐批次、时间和投递入口。",
                "source_url": source_page_url,
                "source_page_url": source_page_url,
                "company_id": company_id,
                "entity_id": str(ad_info.get("id") or company_id).strip(),
                "recruitment_batch": batch_name,
                "recruitment_stage": recruitment_stage,
                "collected_at_text": collected_at_text,
                "application_period_text": application_period_text,
                "apply_label": apply_label,
                "topic_source_kind": "schedule",
            }
        )
        seen_company_names.add(dedupe_key)

    return parsed_items


def _cleanup_enterprise_page_company_name(value: str) -> str:
    text = _normalize_whitespace(value)
    text = re.sub(r"\d{4}年校招职位信息\s*[-_]?\s*牛客网$", "", text)
    text = re.sub(r"\d{4}年校招职位信息$", "", text)
    text = re.sub(r"\s*[-_]?\s*牛客网$", "", text)
    return _clean_company_name(text)


def _is_nowcoder_enterprise_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.netloc.endswith("nowcoder.com") and parsed.path.startswith("/enterprise/")


def parse_niuke_enterprise_schedule_meta(html: str) -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    page_text = _normalize_whitespace(soup.get_text(" ", strip=True))

    company_name = ""
    title_node = soup.find("h1")
    if title_node is not None:
        company_name = _cleanup_enterprise_page_company_name(title_node.get_text(" ", strip=True))
    if not company_name:
        title_text = _normalize_whitespace(soup.title.get_text(" ", strip=True) if soup.title else "")
        company_name = _cleanup_enterprise_page_company_name(title_text.split("_", 1)[0])

    recruitment_batch_match = re.search(r"招聘批次[:：]\s*([^\s]+)", page_text)
    application_period_match = NIUKE_APPLICATION_PERIOD_PATTERN.search(page_text)

    return {
        "company_name": company_name,
        "recruitment_batch": _normalize_whitespace(recruitment_batch_match.group(1)) if recruitment_batch_match else "",
        "application_period_text": _normalize_whitespace(application_period_match.group(1)) if application_period_match else "",
    }


def fetch_niuke_enterprise_schedule_meta(url: str, timeout: int = 20) -> dict[str, str]:
    response = requests.get(url, timeout=timeout, headers=_build_headers())
    response.raise_for_status()
    return parse_niuke_enterprise_schedule_meta(_decode_response_text(response))


def _parse_schedule_card_text(text: str) -> dict[str, str]:
    normalized = _normalize_whitespace(text)
    prefix_text, _, location_and_action = normalized.partition("地点：")
    left_text, separator, right_text = prefix_text.partition("丨")
    header_text = _normalize_whitespace(left_text)
    collected_at_text = _normalize_whitespace(right_text if separator else "")

    recruitment_batch_match = NIUKE_BATCH_PATTERN.search(header_text)
    recruitment_stage_match = NIUKE_STAGE_PATTERN.search(header_text)
    recruitment_batch = _normalize_whitespace(recruitment_batch_match.group(0)) if recruitment_batch_match else ""
    recruitment_stage = _normalize_whitespace(recruitment_stage_match.group(0)) if recruitment_stage_match else ""

    company_name = header_text
    if recruitment_batch:
        company_name = company_name.replace(recruitment_batch, " ")
    if recruitment_stage:
        company_name = company_name.replace(recruitment_stage, " ")
    company_name = _cleanup_schedule_company_name(company_name)

    apply_label = ""
    if "官网投递" in location_and_action or "官网投递" in normalized:
        apply_label = "官网投递"
    elif "立即投递" in location_and_action or "立即投递" in normalized:
        apply_label = "立即投递"

    city_text = _normalize_whitespace(location_and_action)
    if apply_label:
        city_text = _normalize_whitespace(city_text.split(apply_label, 1)[0])

    return {
        "company_name": company_name,
        "recruitment_batch": recruitment_batch,
        "recruitment_stage": recruitment_stage,
        "collected_at_text": collected_at_text,
        "apply_label": apply_label,
        "city_text": city_text,
    }


def parse_niuke_campus_homepage_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_company_names: set[str] = set()

    for anchor in soup.select('a[href*="/jump?type=ad"]'):
        href = str(anchor.get("href") or "").strip()
        company_name = _clean_company_name(anchor.get_text(" ", strip=True))
        if not href or not company_name or _is_non_company_schedule_name(company_name):
            continue

        dedupe_key = company_name.lower()
        if dedupe_key in seen_company_names:
            continue

        career_site_url, metadata = _extract_redirect_target(href)
        items.append(
            {
                "company_name": company_name,
                "group_name": "牛客招聘动态",
                "industry": "",
                "scale_text": "",
                "city_text": "",
                "official_site_url": "",
                "career_site_url": career_site_url,
                "description_text": "从牛客首页公开招聘动态卡片同步，优先补齐企业专题与官网投递入口。",
                "source_url": metadata["source_url"],
                "source_page_url": metadata["source_url"],
                "company_id": metadata["company_id"],
                "entity_id": metadata["entity_id"],
                "topic_source_kind": "homepage",
            }
        )
        seen_company_names.add(dedupe_key)

    return items


def parse_niuke_campus_schedule_featured_companies(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    items: list[dict[str, str]] = []
    seen_company_names: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if "/jump?type=ad&source=102" not in href and "channel=recruitmentSchedule" not in href:
            continue

        text = _extract_anchor_text(anchor)
        if _is_non_company_schedule_name(text):
            continue
        parsed = _parse_schedule_card_text(text)
        company_name = str(parsed.get("company_name") or "").strip()
        if not href or not company_name or _is_non_company_schedule_name(company_name):
            continue

        dedupe_key = company_name.lower()
        if dedupe_key in seen_company_names:
            continue

        career_site_url, metadata = _extract_redirect_target(href)
        description_parts = ["从牛客校招日程页同步"]
        if parsed["recruitment_batch"]:
            description_parts.append(parsed["recruitment_batch"])
        if parsed["recruitment_stage"]:
            description_parts.append(parsed["recruitment_stage"])
        if parsed["collected_at_text"]:
            description_parts.append(parsed["collected_at_text"])

        items.append(
            {
                "company_name": company_name,
                "group_name": "牛客校招日程",
                "industry": "",
                "scale_text": "",
                "city_text": parsed["city_text"],
                "official_site_url": "",
                "career_site_url": career_site_url,
                "description_text": "，".join(description_parts) + "，优先补齐批次、时间和投递入口。",
                "source_url": metadata["source_url"],
                "source_page_url": metadata["source_url"],
                "company_id": metadata["company_id"],
                "entity_id": metadata["entity_id"],
                "recruitment_batch": parsed["recruitment_batch"],
                "recruitment_stage": parsed["recruitment_stage"],
                "collected_at_text": parsed["collected_at_text"],
                "apply_label": parsed["apply_label"],
                "topic_source_kind": "schedule",
            }
        )
        seen_company_names.add(dedupe_key)

    return items


def fetch_niuke_campus_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(
        NIUKE_CAMPUS_HOME_URL,
        timeout=timeout,
        headers=_build_headers(),
    )
    response.raise_for_status()
    return parse_niuke_campus_homepage_featured_companies(_decode_response_text(response))


def fetch_niuke_campus_schedule_featured_companies(timeout: int = 20) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    api_response = requests.post(
        NIUKE_CAMPUS_SCHEDULE_LIST_API,
        timeout=timeout,
        headers=_build_nowpick_api_headers(),
        data={"query": "", "tab": 0, "page": 1, "pageSize": 20},
    )
    api_response.raise_for_status()
    payload = api_response.json()
    if int(payload.get("code") or 0) == 0:
        data = payload.get("data") or {}
        if isinstance(data, dict):
            items = parse_niuke_campus_schedule_api_items(list(data.get("datas") or []))

    if not items:
        response = requests.get(
            NIUKE_CAMPUS_SCHEDULE_URL,
            timeout=timeout,
            headers=_build_headers(),
        )
        response.raise_for_status()
        items = parse_niuke_campus_schedule_featured_companies(_decode_response_text(response))

    enterprise_meta_cache: dict[str, dict[str, str]] = {}
    enriched_items: list[dict[str, str]] = []
    for item in items:
        enriched_item = dict(item)
        source_page_url = str(item.get("source_page_url") or item.get("career_site_url") or "").strip()
        if source_page_url and _is_nowcoder_enterprise_url(source_page_url):
            detail_meta = enterprise_meta_cache.get(source_page_url)
            if detail_meta is None:
                try:
                    detail_meta = fetch_niuke_enterprise_schedule_meta(source_page_url, timeout=timeout)
                except Exception:
                    detail_meta = {}
                enterprise_meta_cache[source_page_url] = detail_meta
            if str(detail_meta.get("company_name") or "").strip():
                enriched_item["company_name"] = str(detail_meta.get("company_name") or "").strip()
            if not str(enriched_item.get("recruitment_batch") or "").strip() and str(detail_meta.get("recruitment_batch") or "").strip():
                enriched_item["recruitment_batch"] = str(detail_meta.get("recruitment_batch") or "").strip()
            if str(detail_meta.get("application_period_text") or "").strip():
                enriched_item["application_period_text"] = str(detail_meta.get("application_period_text") or "").strip()
        enriched_items.append(enriched_item)
    return enriched_items