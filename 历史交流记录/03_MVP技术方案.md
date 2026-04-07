# 就业聚合 App MVP 技术方案

## 一、MVP 目标

第一版不追求“全网职位聚合”，而是先验证以下核心价值：

1. 用户可以按关键词和城市搜索职位
2. 用户可以查看职位详情和官网投递链接
3. 用户可以收藏企业或收藏搜索条件
4. 用户可以收到新职位提醒

## 二、MVP 范围

### 必做功能

1. 职位搜索
2. 职位详情
3. 企业收藏
4. 搜索订阅
5. 新职位提醒
6. 官网链接跳转

### 暂不做功能

1. 在线简历编辑
2. App 内直接投递
3. 聊天沟通
4. AI 简历诊断
5. 复杂推荐系统

## 三、技术选型

### 客户端

推荐：Flutter

原因：

1. 一套代码可覆盖 Android/iOS
2. 界面开发效率高
3. 适合做搜索、列表、详情、收藏等业务型页面

### 服务端

推荐：FastAPI

原因：

1. Python 与采集模块天然统一
2. 开发 REST API 非常高效
3. 便于和爬虫、定时任务放在同一技术栈中

### 采集模块

推荐：Python

建议拆成四类采集器：

1. `html_spider`：静态网页采集
2. `json_spider`：接口 JSON 采集
3. `dynamic_spider`：动态渲染页面采集
4. `company_site_adapter`：官网招聘页适配器

### 数据库

推荐：PostgreSQL

### 缓存与任务调度

推荐：Redis + Celery

### 推送

初期可先做站内通知；后期接入移动推送。

## 四、系统模块拆分

```text
mobile_app/
backend_api/
collector_service/
notification_service/
shared_models/
```

### 1. mobile_app

页面建议：

1. 首页搜索页
2. 职位列表页
3. 职位详情页
4. 收藏页
5. 消息页
6. 我的页面

### 2. backend_api

职责：

1. 提供搜索接口
2. 提供职位详情接口
3. 提供收藏接口
4. 提供订阅接口
5. 提供通知接口

### 3. collector_service

职责：

1. 定时采集职位数据
2. 标准化字段
3. 去重与更新检测
4. 写入数据库

### 4. notification_service

职责：

1. 识别新增职位
2. 匹配收藏规则
3. 生成通知记录
4. 推送到用户

## 五、后端 API 设计

## 1. 搜索职位

### 请求

`GET /api/jobs`

### 参数

1. `keyword`
2. `city`
3. `degree`
4. `experience`
5. `page`
6. `page_size`

### 返回

```json
{
  "total": 120,
  "items": [
    {
      "id": 1001,
      "title": "Java开发工程师",
      "company_name": "某科技公司",
      "city_name": "青岛",
      "salary_text": "10-18K",
      "source_name": "企业官网",
      "official_apply_url": "https://company.com/careers/123"
    }
  ]
}
```

## 2. 职位详情

### 请求

`GET /api/jobs/{job_id}`

### 返回字段

1. 职位标题
2. 公司名
3. 工作地点
4. 薪资
5. 学历
6. 经验
7. 描述
8. 来源链接
9. 官网投递链接

## 3. 收藏企业

### 请求

`POST /api/favorites/companies`

### body

```json
{
  "company_id": 2001
}
```

## 4. 收藏搜索条件

### 请求

`POST /api/saved-searches`

### body

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

## 5. 通知列表

### 请求

`GET /api/notifications`

## 六、采集模块怎么拆

## 1. 统一数据模型

每个采集器最终都要输出统一结构：

```python
{
    "source_code": "company_site",
    "company_name": "某公司",
    "title": "Java开发工程师",
    "city_name": "青岛",
    "district_name": "崂山区",
    "salary_text": "10-18K",
    "degree_text": "本科",
    "experience_text": "3-5年",
    "description_text": "...",
    "source_url": "https://...",
    "official_apply_url": "https://...",
    "published_at": "2026-03-25 10:00:00"
}
```

## 2. 采集器目录建议

```text
collector_service/
  spiders/
    base_spider.py
    html_spider.py
    json_spider.py
    dynamic_spider.py
  adapters/
    company_a.py
    company_b.py
    gov_jobs.py
  pipeline/
    normalizer.py
    deduplicator.py
    notifier.py
```

## 3. 各模块职责

### base_spider.py

定义统一接口：

1. `fetch()`
2. `parse()`
3. `normalize()`

### html_spider.py

适合：

1. requests + BeautifulSoup
2. requests + lxml
3. requests + XPath

### json_spider.py

适合：

1. 抓包确认 JSON 接口
2. requests/httpx 获取 JSON
3. JSONPath 提取字段

### dynamic_spider.py

适合：

1. Playwright 打开动态页面
2. 等待页面加载完成
3. 获取 HTML 或接口响应

### normalizer.py

职责：

1. 字段标准化
2. 城市名统一
3. 时间格式统一
4. URL 清洗

### deduplicator.py

职责：

1. 计算 unique_hash
2. 识别新增职位
3. 识别内容更新
4. 识别职位下线

### notifier.py

职责：

1. 匹配收藏企业
2. 匹配收藏搜索条件
3. 生成通知记录

## 七、前端页面结构

## 1. 首页搜索页

组件：

1. 搜索框
2. 热门关键词
3. 城市选择器
4. 最近搜索

## 2. 列表页

每条职位卡片显示：

1. 职位名
2. 公司名
3. 城市
4. 薪资
5. 来源
6. 是否已收藏

## 3. 详情页

显示：

1. 基础信息
2. 职位描述
3. 来源链接
4. 官网投递按钮
5. 收藏企业按钮

## 4. 收藏页

分类：

1. 收藏企业
2. 收藏搜索条件
3. 收藏职位

## 5. 消息页

展示：

1. 新职位提醒
2. 职位更新提醒
3. 职位下线提醒

## 八、MVP 开发顺序

### 第一周

1. 设计数据库
2. 完成职位表与企业表
3. 写 2 到 3 个官网采集器

### 第二周

1. 完成搜索 API
2. 完成职位详情 API
3. 完成移动端搜索与列表页

### 第三周

1. 完成收藏企业与收藏搜索条件
2. 完成通知表和通知接口
3. 编写新增职位识别逻辑

### 第四周

1. 打通完整闭环
2. 增加推送或站内通知
3. 修复数据去重和链接跳转问题

## 九、MVP 成功标准

满足以下条件即可认为 MVP 成功：

1. 用户可以搜索到职位
2. 用户可以打开职位详情
3. 用户可以跳转官网投递
4. 用户可以收藏企业
5. 企业新增职位后系统可以提醒用户

## 十、后续扩展方向

1. 增加更多来源站点
2. 增加职位推荐与排序策略
3. 增加简历管理
4. 增加面试进度记录
5. 增加 AI 岗位匹配分析
