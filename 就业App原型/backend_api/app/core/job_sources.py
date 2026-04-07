from typing import Any


SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "boss": {
        "source_code": "boss",
        "source_name": "Boss直聘",
        "platform_code": "boss",
        "platform_name": "Boss直聘",
        "status": "beta",
        "enabled": True,
        "strategy": "requests_api",
        "description": "接口实验链路；当前常受环境校验影响，适合做 requests 探测与诊断，不建议作为主抓取方案。",
    },
    "boss_dp": {
        "source_code": "boss_dp",
        "source_name": "Boss直聘（浏览器拦截）",
        "platform_code": "boss",
        "platform_name": "Boss直聘",
        "status": "active",
        "enabled": True,
        "strategy": "browser_intercept",
        "description": "当前 Boss 主抓取方案；通过 DrissionPage 监听接口响应，整体比 requests 链路更贴近真实浏览器环境。",
    },
    "lagou": {
        "source_code": "lagou",
        "source_name": "拉勾",
        "platform_code": "lagou",
        "platform_name": "拉勾",
        "status": "beta",
        "enabled": True,
        "strategy": "browser_manual_intercept",
        "description": "浏览器打开搜索页；若命中滑动验证需人工通过。当前首屏优先读取 __NEXT_DATA__ 注水职位列表，后续分页主要依赖结果页 DOM 回退；近期 bundle 逆向显示站点更偏向路由切页 + 注水刷新，packet 分支暂未观察到稳定可依赖入口。",
    },
    "liepin": {
        "source_code": "liepin",
        "source_name": "猎聘",
        "platform_code": "liepin",
        "platform_name": "猎聘",
        "status": "active",
        "enabled": True,
        "strategy": "browser_intercept_api",
        "description": "通过浏览器拦截 pc-search-job 列表接口；热门城市优先走站内精确检索，更多城市会通过城市招聘网入口动态解析后再精确搜索。",
    },
    "job51": {
        "source_code": "job51",
        "source_name": "前程无忧",
        "platform_code": "51job",
        "platform_name": "前程无忧",
        "status": "active",
        "enabled": True,
        "strategy": "browser_intercept_api",
        "description": "通过浏览器拦截 search-pc 列表接口，并动态解析 51job 城市字典。",
    },
    "guopin": {
        "source_code": "guopin",
        "source_name": "国聘",
        "platform_code": "guopin",
        "platform_name": "国聘",
        "status": "active",
        "enabled": True,
        "strategy": "requests_api",
        "description": "直接请求 gp-api 的 jobs/v1/recom-job 与 jobs/v1/info；城市条件通过 search.district 精确传入，详情页链接拼接为 /job/detail?id=...。",
    },
    "jobmohrss": {
        "source_code": "jobmohrss",
        "source_name": "中国公共招聘网",
        "platform_code": "mohrss",
        "platform_name": "中国公共招聘网",
        "status": "active",
        "enabled": True,
        "strategy": "requests_html",
        "description": "直接请求 /cjobs/jobinfolist/listJobinfolist 服务端分页页面，并解析隐藏字段 findjoblist 与 showgw 详情页，适合补公共就业体系和官方岗位来源。",
    },
    "ncss24365": {
        "source_code": "ncss24365",
        "source_name": "24365 国家大学生就业服务平台",
        "platform_code": "ncss",
        "platform_name": "24365 国家大学生就业服务平台",
        "status": "active",
        "enabled": True,
        "strategy": "requests_api",
        "description": "直接请求 /student/jobs/jobslist/ajax/ 列表接口，并补抓 /student/jobs/{job_id}/detail.html 详情页，适合补官方校招与高校来源职位。",
    },
    "qingdao_rc": {
        "source_code": "qingdao_rc",
        "source_name": "青岛人才招聘e站",
        "platform_code": "qingdao_rc",
        "platform_name": "青岛人才招聘e站",
        "status": "active",
        "enabled": True,
        "strategy": "requests_api",
        "description": "直接请求 qdzhrcww 的 jzQuery/findQuery 列表接口，并补抓 toDetail/toFwDetail 详情页，适合补青岛本地官方岗位来源。",
    },
    "qdhr": {
        "source_code": "qdhr",
        "source_name": "青帆引才",
        "platform_code": "qdhr",
        "platform_name": "青帆引才",
        "status": "active",
        "enabled": True,
        "strategy": "requests_html",
        "description": "抓取 qdhr 的公开职位列表页和详情页，适合补青岛本地市场化岗位来源。",
    },
    "sdgxbys": {
        "source_code": "sdgxbys",
        "source_name": "山东高校毕业生就业市场主职位",
        "platform_code": "sdgxbys",
        "platform_name": "山东高校毕业生就业市场",
        "status": "active",
        "enabled": True,
        "strategy": "requests_html",
        "description": "抓取山东高校毕业生就业市场主职位分页；列表内容通过页面内嵌压缩 payload 解码后解析，适合补省级公开职位主表来源。",
    },
    "sdgxbys_campus": {
        "source_code": "sdgxbys_campus",
        "source_name": "山东高校毕业生就业市场校园公告",
        "platform_code": "sdgxbys",
        "platform_name": "山东高校毕业生就业市场",
        "status": "active",
        "enabled": True,
        "strategy": "requests_html",
        "description": "抓取山东高校毕业生就业市场公开 campus 公告分页与详情标题元信息，适合补省级校园招聘公告来源。",
    },
    "rcsd_talents": {
        "source_code": "rcsd_talents",
        "source_name": "人才山东引才公告",
        "platform_code": "rcsd",
        "platform_name": "人才山东",
        "status": "active",
        "enabled": True,
        "strategy": "requests_html",
        "description": "抓取人才山东 demand/talents 静态分页栏目与公告详情，适合补山东省级引才与招聘公告来源。",
    },
    "shixiseng": {
        "source_code": "shixiseng",
        "source_name": "实习僧",
        "platform_code": "shixiseng",
        "platform_name": "实习僧",
        "status": "active",
        "enabled": True,
        "strategy": "browser_nuxt_detail",
        "description": "通过浏览器读取 Nuxt 注水数据，优先覆盖实习/校招岗位。",
    },
    "zhilian": {
        "source_code": "zhilian",
        "source_name": "智联招聘",
        "platform_code": "zhilian",
        "platform_name": "智联招聘",
        "status": "active",
        "enabled": True,
        "strategy": "browser_intercept_api",
        "description": "通过浏览器首屏注水加翻页接口拦截，优先读取 search/positions 真列表响应。",
    },
    "unknown": {
        "source_code": "unknown",
        "source_name": "未知来源",
        "platform_code": "unknown",
        "platform_name": "未知来源",
        "status": "unknown",
        "enabled": False,
        "strategy": "unknown",
        "description": "未知来源。",
    },
}

SOURCE_LABELS = {code: item["source_name"] for code, item in SOURCE_CATALOG.items()}
SOURCE_LABELS["manual_seed"] = "专题种子"


def get_source_name(source_code: str) -> str:
    normalized = (source_code or "").strip().lower()
    if not normalized:
        normalized = "unknown"
    return SOURCE_LABELS.get(normalized, normalized)


def get_source_info(source_code: str) -> dict[str, Any]:
    normalized = (source_code or "").strip().lower()
    if not normalized:
        normalized = "unknown"
    return dict(SOURCE_CATALOG.get(normalized, SOURCE_CATALOG["unknown"]))


def list_source_catalog(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    items = [dict(item) for code, item in SOURCE_CATALOG.items() if code != "unknown"]
    if not include_disabled:
        items = [item for item in items if item.get("enabled")]
    return sorted(items, key=lambda item: (not item.get("enabled", False), item.get("platform_name", ""), item.get("source_name", "")))
