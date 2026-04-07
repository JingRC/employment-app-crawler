# FastAPI 后端项目骨架与路由拆分

## 一、目标

FastAPI 后端负责：

1. 提供职位搜索和详情接口
2. 提供收藏与通知接口
3. 对接数据库
4. 给采集模块提供写入入口或后台任务入口

## 二、推荐项目结构

```text
backend_api/
  app/
    api/
      deps.py
      router.py
      routes/
        jobs.py
        companies.py
        favorites.py
        saved_searches.py
        notifications.py
        internal_crawl.py
    core/
      config.py
      database.py
      security.py
    models/
      company.py
      favorite.py
      job.py
      notification.py
      saved_search.py
      user.py
    schemas/
      common.py
      company.py
      favorite.py
      job.py
      notification.py
      saved_search.py
      user.py
    services/
      company_service.py
      favorite_service.py
      job_service.py
      notification_service.py
      search_service.py
    main.py
  requirements.txt
```

## 三、各目录职责

## 1. api/routes

按业务拆分路由，而不是把所有接口写到一个文件中。

### jobs.py
负责：

1. 职位搜索
2. 职位详情

### companies.py
负责：

1. 企业详情
2. 企业职位列表

### favorites.py
负责：

1. 收藏企业
2. 取消收藏企业
3. 获取收藏企业列表

### saved_searches.py
负责：

1. 保存搜索条件
2. 获取搜索条件列表
3. 删除搜索条件

### notifications.py
负责：

1. 通知列表
2. 标记已读

### internal_crawl.py
负责内部任务：

1. 手动触发采集
2. 查看采集任务状态

## 2. models

放 SQLAlchemy 数据表模型。

## 3. schemas

放 Pydantic 请求体和响应体模型。

## 4. services

放业务逻辑，避免把复杂逻辑直接写在路由函数里。

## 四、主路由聚合方式

### app/api/router.py

```python
from fastapi import APIRouter

from app.api.routes import jobs, companies, favorites, saved_searches, notifications, internal_crawl

api_router = APIRouter()
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(saved_searches.router, prefix="/saved-searches", tags=["saved-searches"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(internal_crawl.router, prefix="/internal/crawl", tags=["internal-crawl"])
```

## 五、main.py 模板

```python
from fastapi import FastAPI
from app.api.router import api_router

app = FastAPI(title="Job Aggregator API")
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "ok"}
```

## 六、路由文件模板

### routes/jobs.py

```python
from fastapi import APIRouter, Query

router = APIRouter()

@router.get("")
def list_jobs(
    keyword: str | None = Query(default=None),
    city_name: str | None = Query(default=None),
    page: int = 1,
    page_size: int = 20,
):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "items": [],
        },
    }

@router.get("/{job_id}")
def get_job_detail(job_id: int):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "job_id": job_id,
        },
    }
```

### routes/companies.py

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/{company_id}/jobs")
def list_company_jobs(company_id: int):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "company_id": company_id,
            "items": [],
        },
    }
```

### routes/favorites.py

```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class FavoriteCompanyRequest(BaseModel):
    company_id: int

@router.post("/companies")
def favorite_company(body: FavoriteCompanyRequest):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "company_id": body.company_id,
        },
    }
```

### routes/saved_searches.py

```python
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class SavedSearchRequest(BaseModel):
    keyword: str
    city_name: str = ""
    filters: dict = {}

@router.post("")
def create_saved_search(body: SavedSearchRequest):
    return {
        "code": 0,
        "message": "success",
        "data": body.model_dump(),
    }
```

### routes/notifications.py

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("")
def list_notifications(page: int = 1, page_size: int = 20):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "items": [],
        },
    }

@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: int):
    return {
        "code": 0,
        "message": "success",
        "data": True,
    }
```

## 七、Service 层拆分建议

## 1. job_service.py

负责：

1. 查询职位列表
2. 查询职位详情
3. 处理筛选条件

## 2. company_service.py

负责：

1. 获取企业信息
2. 获取企业职位列表

## 3. favorite_service.py

负责：

1. 添加收藏
2. 删除收藏
3. 获取收藏列表

## 4. notification_service.py

负责：

1. 查询通知
2. 标记已读
3. 生成通知

## 八、Schema 建议

### schemas/job.py

```python
from pydantic import BaseModel

class JobListItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    city_name: str
    salary_text: str = ""
    official_apply_url: str = ""

class JobListResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[JobListItem]
```

## 九、开发顺序建议

1. 先搭 main.py + router.py
2. 先写 jobs.py 和 notifications.py
3. 再接数据库模型
4. 再补 favorites 和 saved_searches
5. 最后加 internal_crawl

## 十、MVP 最小骨架

如果只做第一版，最少需要：

1. `main.py`
2. `api/router.py`
3. `api/routes/jobs.py`
4. `api/routes/favorites.py`
5. `api/routes/notifications.py`
6. `models/job.py`
7. `schemas/job.py`
8. `services/job_service.py`

这样已经足够支撑搜索、详情、收藏、提醒四个核心场景。
