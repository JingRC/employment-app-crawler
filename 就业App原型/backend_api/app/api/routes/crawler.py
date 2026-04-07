from typing import Any

from fastapi import APIRouter, Query

from app.schemas.crawl import BossCookieManualSaveRequest, BossCookiePrepareRequest, BossCookiePrepareResult, BossCookieStatusResult, CrawlSourceItem, CrawlTaskStatus, CrawlTriggerRequest, SafeVerifyTriggerRequest
from app.services.crawler_adapters import list_crawl_sources, load_source_module
from app.services.crawler_service import cancel_incremental_crawl, get_crawl_status, start_incremental_crawl, start_safe_verify_task

router = APIRouter()
_GUOPIN_MODULE: Any | None = None
_GUOPIN_DISTRICT_TREE_CACHE: list[dict[str, Any]] | None = None
_GUOPIN_CITY_CACHE: list[dict[str, Any]] | None = None
_GUOPIN_CITY_DISTRICT_CACHE: dict[str, list[dict[str, Any]]] = {}


def _get_guopin_module() -> Any:
    global _GUOPIN_MODULE
    if _GUOPIN_MODULE is None or getattr(_GUOPIN_MODULE, "requests", None) is None:
        _GUOPIN_MODULE = load_source_module("guopin")
    return _GUOPIN_MODULE


def _get_guopin_district_tree() -> tuple[Any, list[dict[str, Any]]]:
    global _GUOPIN_DISTRICT_TREE_CACHE
    module = _get_guopin_module()
    if _GUOPIN_DISTRICT_TREE_CACHE is not None:
        return module, _GUOPIN_DISTRICT_TREE_CACHE

    timeout_seconds = float(getattr(module, "DEFAULT_SOURCE_OPTIONS", {}).get("request_timeout_seconds", 15.0))
    session = module.build_session()
    try:
        _GUOPIN_DISTRICT_TREE_CACHE = module.fetch_district_tree(session, timeout_seconds=timeout_seconds)
    finally:
        session.close()
    return module, _GUOPIN_DISTRICT_TREE_CACHE or []


def _build_guopin_city_catalog() -> list[dict[str, Any]]:
    global _GUOPIN_CITY_CACHE
    if _GUOPIN_CITY_CACHE is not None:
        return _GUOPIN_CITY_CACHE

    module, district_tree = _get_guopin_district_tree()

    city_map: dict[str, dict[str, Any]] = {}
    for root in district_tree:
        if not isinstance(root, dict):
            continue
        for province in root.get("children") or []:
            if not isinstance(province, dict):
                continue
            province_label = module.clean_text(province.get("label") or province.get("name"))
            province_simple = module.simplify_area_name(province_label)
            is_special = bool(province.get("is_special"))
            for city in province.get("children") or []:
                if not isinstance(city, dict):
                    continue
                city_label_raw = module.clean_text(city.get("label") or city.get("name"))
                city_simple = module.simplify_area_name(city_label_raw)
                city_label = province_label if is_special or city_simple == province_simple else city_label_raw
                if not city_label:
                    continue
                item = city_map.setdefault(
                    city_label,
                    {
                        "city_name": city_label,
                        "city_code": module.resolve_city_district_code(city_label, district_tree),
                        "district_count": 0,
                    },
                )
                district_items = _GUOPIN_CITY_DISTRICT_CACHE.setdefault(city_label, [])
                seen_districts = {district.get("district_name") for district in district_items}
                for district in city.get("children") or []:
                    if not isinstance(district, dict):
                        continue
                    district_label = module.clean_text(district.get("label") or district.get("name"))
                    if not district_label or district_label in seen_districts:
                        continue
                    district_items.append(
                        {
                            "district_name": district_label,
                            "target_value": f"{city_label}-{district_label}",
                            "district_code": module.resolve_city_district_code(f"{city_label}-{district_label}", district_tree),
                        }
                    )
                    seen_districts.add(district_label)
                item["district_count"] = len(district_items)

    _GUOPIN_CITY_CACHE = sorted(city_map.values(), key=lambda item: str(item.get("city_name") or ""))
    return _GUOPIN_CITY_CACHE


def _get_guopin_district_items(city_name: str) -> list[dict[str, Any]]:
    module = _get_guopin_module()
    normalized_city_name = module.clean_text(city_name)
    if not normalized_city_name:
        return []
    if _GUOPIN_CITY_CACHE is None:
        _build_guopin_city_catalog()
    return list(_GUOPIN_CITY_DISTRICT_CACHE.get(normalized_city_name) or [])


@router.get("/status")
def get_status() -> dict:
    data = CrawlTaskStatus(**get_crawl_status())
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.get("/sources")
def get_crawl_sources() -> dict:
    items = [CrawlSourceItem(**item).model_dump() for item in list_crawl_sources(include_disabled=True)]
    return {"code": 0, "message": "success", "data": {"items": items}}


@router.get("/guopin/cities")
def get_guopin_cities() -> dict:
    return {"code": 0, "message": "success", "data": {"items": _build_guopin_city_catalog()}}


@router.get("/guopin/districts")
def get_guopin_districts(city_name: str = Query(default="")) -> dict:
    return {"code": 0, "message": "success", "data": {"items": _get_guopin_district_items(city_name)}}


@router.post("/jobs/incremental")
def start_incremental_job_crawl(body: CrawlTriggerRequest) -> dict:
    status = start_incremental_crawl(
        sources=body.sources,
        queries=body.queries,
        cities=body.cities,
        max_pages=body.max_pages,
        page_size=body.page_size,
        runtime_mode=body.runtime_mode,
        stale_after_hours=body.stale_after_hours,
        source_options=body.source_options,
    )
    data = CrawlTaskStatus(**status)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/jobs/safe-verify")
def start_safe_verify(body: SafeVerifyTriggerRequest) -> dict:
    status = start_safe_verify_task(
        limit=body.limit,
        timeout_seconds=body.timeout_seconds,
        recent_active_hours=body.recent_active_hours,
        cooldown_hours=body.cooldown_hours,
        auto_only=body.auto_only,
    )
    data = CrawlTaskStatus(**status)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/jobs/cancel")
def cancel_incremental_job_crawl() -> dict:
    status = cancel_incremental_crawl()
    data = CrawlTaskStatus(**status)
    return {"code": 0, "message": "success", "data": data.model_dump()}


@router.post("/boss/prepare-cookie")
def prepare_boss_cookie(body: BossCookiePrepareRequest) -> dict:
    module = load_source_module("boss")
    query = str(body.query or "Java").strip() or "Java"
    city = str(body.city or "101010100").strip() or "101010100"
    runtime_mode = str(body.runtime_mode or "requests_only").strip().lower() or "requests_only"
    browser_preference = str(body.browser_preference or "edge").strip().lower() or "edge"
    browser_profile = str(body.browser_profile or "Default").strip() or "Default"
    login_wait_seconds = max(0, int(body.login_wait_seconds or 40))
    try:
        module.prepare_persisted_cookie(
            query=query,
            city=city,
            runtime_mode=runtime_mode,
            browser_preference=browser_preference,
            browser_profile=browser_profile,
            login_wait_seconds=login_wait_seconds,
        )
        local = module.load_local_secrets() if hasattr(module, "load_local_secrets") else {}
        status_payload = module.probe_persisted_cookie(query=query, city=city, runtime_mode=runtime_mode) if hasattr(module, "probe_persisted_cookie") else {}
        data = BossCookiePrepareResult(
            source_code="boss",
            query=query,
            city=city,
            runtime_mode=runtime_mode,
            browser_preference=browser_preference,
            browser_profile=browser_profile,
            login_wait_seconds=login_wait_seconds,
            cookie_refreshed_at=str(local.get("cookie_refreshed_at", "") or ""),
            cookie_runtime_mode=str(local.get("cookie_runtime_mode", "") or ""),
            cookie_present=bool(str(local.get("cookie", "") or "").strip()),
            cookie_valid=bool(status_payload.get("cookie_valid", False)),
            missing_keys=list(status_payload.get("missing_keys", []) or []),
            validation_mode=str(status_payload.get("validation_mode", "") or ""),
            probe_code=str(status_payload.get("probe_code", "") or ""),
            probe_message=str(status_payload.get("probe_message", "") or ""),
            message=str(status_payload.get("message", "") or "Boss 接口实验 Cookie 已保存，可重新执行增量更新。"),
        )
        return {"code": 0, "message": "success", "data": data.model_dump()}
    except Exception as exc:
        data = BossCookiePrepareResult(
            source_code="boss",
            query=query,
            city=city,
            runtime_mode=runtime_mode,
            browser_preference=browser_preference,
            browser_profile=browser_profile,
            login_wait_seconds=login_wait_seconds,
            message=str(exc),
        )
        return {"code": 1, "message": str(exc), "detail": str(exc), "data": data.model_dump()}


@router.post("/boss/save-cookie")
def save_boss_cookie(body: BossCookieManualSaveRequest) -> dict:
    module = load_source_module("boss")
    query = str(body.query or "Java").strip() or "Java"
    city = str(body.city or "101010100").strip() or "101010100"
    runtime_mode = str(body.runtime_mode or "requests_only").strip().lower() or "requests_only"
    cookie_text = str(body.cookie_text or "").strip()
    if cookie_text.lower().startswith("cookie:"):
        cookie_text = cookie_text.split(":", 1)[1].strip()

    try:
        if hasattr(module, "persist_cookie_bundle"):
            module.persist_cookie_bundle(cookie_text, runtime_mode=runtime_mode)
        else:
            raise RuntimeError("当前 Boss 模块不支持手动保存 Cookie")
        local = module.load_local_secrets() if hasattr(module, "load_local_secrets") else {}
        status_payload = module.probe_persisted_cookie(query=query, city=city, runtime_mode=runtime_mode) if hasattr(module, "probe_persisted_cookie") else {}
        data = BossCookiePrepareResult(
            source_code="boss",
            query=query,
            city=city,
            runtime_mode=runtime_mode,
            browser_preference="manual",
            browser_profile=str(local.get("browser_profile", "") or ""),
            login_wait_seconds=0,
            cookie_refreshed_at=str(local.get("cookie_refreshed_at", "") or ""),
            cookie_runtime_mode=str(local.get("cookie_runtime_mode", "") or ""),
            cookie_present=bool(str(local.get("cookie", "") or "").strip()),
            cookie_valid=bool(status_payload.get("cookie_valid", False)),
            missing_keys=list(status_payload.get("missing_keys", []) or []),
            validation_mode=str(status_payload.get("validation_mode", "") or ""),
            probe_code=str(status_payload.get("probe_code", "") or ""),
            probe_message=str(status_payload.get("probe_message", "") or ""),
            message=str(status_payload.get("message", "") or "Boss 接口实验 Cookie 已手动保存。"),
        )
        return {"code": 0, "message": "success", "data": data.model_dump()}
    except Exception as exc:
        data = BossCookiePrepareResult(
            source_code="boss",
            query=query,
            city=city,
            runtime_mode=runtime_mode,
            browser_preference="manual",
            browser_profile="",
            login_wait_seconds=0,
            message=str(exc),
        )
        return {"code": 1, "message": str(exc), "detail": str(exc), "data": data.model_dump()}


@router.get("/boss/cookie-status")
def get_boss_cookie_status(
    query: str = Query(default="Java"),
    city: str = Query(default="101010100"),
    browser_profile: str = Query(default="Default"),
) -> dict:
    module = load_source_module("boss")
    if hasattr(module, "probe_persisted_cookie"):
        status_payload = module.probe_persisted_cookie(query=query, city=city, runtime_mode="requests_only")
    else:
        local = module.load_local_secrets() if hasattr(module, "load_local_secrets") else {}
        cookie_value = str(local.get("cookie", "") or "")
        missing_keys = list(module.missing_required_cookie_keys(cookie_value)) if hasattr(module, "missing_required_cookie_keys") else []
        cookie_present = bool(cookie_value.strip())
        cookie_valid = cookie_present and not missing_keys
        status_payload = {
            "source_code": "boss",
            "cookie_present": cookie_present,
            "cookie_valid": cookie_valid,
            "missing_keys": missing_keys,
            "cookie_refreshed_at": str(local.get("cookie_refreshed_at", "") or ""),
            "cookie_runtime_mode": str(local.get("cookie_runtime_mode", "") or ""),
            "browser_profile": browser_profile,
            "validation_mode": "structure_only",
            "probe_code": "",
            "probe_message": "",
            "query": query,
            "city": city,
            "message": "Boss Cookie 可用" if cookie_valid else ("Boss Cookie 不完整" if cookie_present else "当前还没有 Boss Cookie"),
        }
    data = BossCookieStatusResult(
        source_code="boss",
        cookie_present=bool(status_payload.get("cookie_present", False)),
        cookie_valid=bool(status_payload.get("cookie_valid", False)),
        missing_keys=list(status_payload.get("missing_keys", []) or []),
        cookie_refreshed_at=str(status_payload.get("cookie_refreshed_at", "") or ""),
        cookie_runtime_mode=str(status_payload.get("cookie_runtime_mode", "") or ""),
        browser_profile=str(status_payload.get("browser_profile", browser_profile) or browser_profile),
        validation_mode=str(status_payload.get("validation_mode", "") or ""),
        probe_code=str(status_payload.get("probe_code", "") or ""),
        probe_message=str(status_payload.get("probe_message", "") or ""),
        query=str(status_payload.get("query", query) or query),
        city=str(status_payload.get("city", city) or city),
        message=str(status_payload.get("message", "") or ""),
    )
    return {"code": 0, "message": "success", "data": data.model_dump()}
