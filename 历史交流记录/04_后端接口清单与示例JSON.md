# 就业聚合 App 后端接口清单与请求/响应示例 JSON

## 设计原则

后端 API 面向移动端 App，建议统一采用 REST 风格，并遵循以下约定：

1. 基础路径：`/api`
2. 返回格式统一：`code`、`message`、`data`
3. 分页字段统一：`page`、`page_size`、`total`、`items`
4. 时间字段统一使用 ISO 8601 或 `yyyy-MM-dd HH:mm:ss`

统一响应格式建议：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

错误响应示例：

```json
{
  "code": 4001,
  "message": "invalid params",
  "data": null
}
```

---

## 1. 职位搜索接口

### 请求

`GET /api/jobs`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| keyword | string | 否 | 搜索关键词，例如 Java |
| city_name | string | 否 | 城市名称 |
| degree | string | 否 | 学历要求 |
| experience | string | 否 | 经验要求 |
| company_name | string | 否 | 公司名称 |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20 |
| sort_by | string | 否 | 排序方式，例如 latest |

### 请求示例

```http
GET /api/jobs?keyword=Java&city_name=青岛&page=1&page_size=20
```

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "page": 1,
    "page_size": 20,
    "total": 15,
    "items": [
      {
        "job_id": 1001,
        "title": "Java开发工程师",
        "company_name": "易诚互动",
        "city_name": "青岛",
        "district_name": "市北区",
        "salary_text": "10-15K",
        "degree_text": "本科",
        "experience_text": "1-3年",
        "source_name": "企业官网",
        "source_url": "https://example.com/jobs/1001",
        "official_apply_url": "https://example.com/careers/apply/1001",
        "published_at": "2026-03-25 10:00:00"
      }
    ]
  }
}
```

---

## 2. 职位详情接口

### 请求

`GET /api/jobs/{job_id}`

### 请求示例

```http
GET /api/jobs/1001
```

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "job_id": 1001,
    "title": "Java开发工程师",
    "company": {
      "company_id": 2001,
      "company_name": "易诚互动",
      "industry": "互联网",
      "company_size": "1000-9999人",
      "financing_stage": "不需要融资",
      "official_site_url": "https://company.example.com",
      "careers_url": "https://company.example.com/careers"
    },
    "city_name": "青岛",
    "district_name": "市北区",
    "salary_text": "10-15K",
    "degree_text": "本科",
    "experience_text": "1-3年",
    "job_type": "全职",
    "description_text": "负责 Java 服务端开发、接口设计与系统维护。",
    "source_name": "企业官网",
    "source_url": "https://example.com/jobs/1001",
    "official_apply_url": "https://example.com/careers/apply/1001",
    "published_at": "2026-03-25 10:00:00",
    "status": "active"
  }
}
```

---

## 3. 收藏企业接口

### 请求

`POST /api/favorites/companies`

### 请求体示例

```json
{
  "company_id": 2001
}
```

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "favorite_id": 5001,
    "company_id": 2001,
    "created_at": "2026-03-25 12:30:00"
  }
}
```

---

## 4. 取消收藏企业接口

### 请求

`DELETE /api/favorites/companies/{company_id}`

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": true
}
```

---

## 5. 收藏搜索条件接口

### 请求

`POST /api/saved-searches`

### 请求体示例

```json
{
  "keyword": "Java",
  "city_name": "青岛",
  "filters": {
    "degree": "本科",
    "experience": "3-5年"
  }
}
```

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "saved_search_id": 6001,
    "keyword": "Java",
    "city_name": "青岛",
    "filters": {
      "degree": "本科",
      "experience": "3-5年"
    },
    "enabled": true,
    "created_at": "2026-03-25 12:35:00"
  }
}
```

---

## 6. 获取收藏搜索条件列表

### 请求

`GET /api/saved-searches`

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "saved_search_id": 6001,
        "keyword": "Java",
        "city_name": "青岛",
        "filters": {
          "degree": "本科",
          "experience": "3-5年"
        },
        "enabled": true
      }
    ]
  }
}
```

---

## 7. 通知列表接口

### 请求

`GET /api/notifications?page=1&page_size=20`

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "page": 1,
    "page_size": 20,
    "total": 3,
    "items": [
      {
        "notification_id": 7001,
        "notification_type": "company_new_job",
        "title": "你收藏的企业有新岗位",
        "content": "易诚互动新增了 2 个 Java 岗位",
        "is_read": false,
        "created_at": "2026-03-25 13:00:00",
        "related_company_id": 2001,
        "related_job_id": null
      }
    ]
  }
}
```

---

## 8. 标记通知已读接口

### 请求

`POST /api/notifications/{notification_id}/read`

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": true
}
```

---

## 9. 获取收藏企业职位动态接口

### 请求

`GET /api/companies/{company_id}/jobs`

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "company_id": 2001,
    "company_name": "易诚互动",
    "items": [
      {
        "job_id": 1001,
        "title": "Java开发工程师",
        "status": "active",
        "published_at": "2026-03-25 10:00:00",
        "official_apply_url": "https://example.com/careers/apply/1001"
      }
    ]
  }
}
```

---

## 10. 管理后台采集任务接口（内部）

### 请求

`POST /internal/crawl/run`

### 请求体示例

```json
{
  "source_code": "company_site",
  "task_type": "incremental"
}
```

### 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": 9001,
    "status": "pending"
  }
}
```

---

## 11. 后端状态码建议

| code | 说明 |
|---|---|
| 0 | 成功 |
| 4001 | 参数错误 |
| 4004 | 资源不存在 |
| 4010 | 未登录 |
| 4030 | 无权限 |
| 5000 | 服务器内部错误 |
| 6001 | 采集任务失败 |
| 6002 | 数据源不可用 |

---

## 12. MVP 最小接口集

如果只做第一版，优先实现以下接口：

1. `GET /api/jobs`
2. `GET /api/jobs/{job_id}`
3. `POST /api/favorites/companies`
4. `POST /api/saved-searches`
5. `GET /api/notifications`
6. `POST /api/notifications/{notification_id}/read`

这样即可支撑“搜索 + 收藏 + 提醒”三大核心能力。
