# 就业 App 原型

两个独立软件，一个后台一个前台：

## 软件一：就业数据后台

爬虫采集 + API 服务 + 数据管理 + Web 管理面板

| 功能 | 说明 |
|------|------|
| 自动爬取 | 31 个招聘平台，每天定时采集 |
| API 接口 | RESTful API，供手机 App 调用 |
| Web 面板 | `http://127.0.0.1:8000/` 查看数据、管理爬虫 |
| 数据库 | SQLite，保存在 `backend_api/data/jobs.db` |

### 启动方式

```
双击 → 启动后台.bat
```

或命令行：

```
cd backend_api
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

启动后浏览器打开 `http://127.0.0.1:8000/`

---

## 软件二：就业手机 App (Flutter)

职位浏览 + 收藏 + 投递跟踪

| 页面 | 说明 |
|------|------|
| 职位 | 搜索/筛选/查看职位详情 |
| 收藏 | 收藏感兴趣的职位和企业 |
| 投递 | 导入外部职位链接 + 跟踪投递进度 |
| 通知 | 新职位匹配通知 |

### 启动方式

```
双击 → 启动手机APP.bat
```

前提：电脑已安装 Flutter SDK，手机 USB 连接并开启调试模式。

真机调试需修改 `mobile_app/lib/core/network/api_client.dart` 中的 `_baseUrl` 为电脑局域网 IP。

---

## 项目结构

```
就业App原型/
├── 启动后台.bat          ← 一键启动后台
├── 启动手机APP.bat       ← 一键启动 App
├── backend_api/          ← FastAPI 后台
│   ├── app/
│   │   ├── api/routes/   ← API 路由
│   │   ├── core/         ← 数据库、来源配置
│   │   ├── models/       ← 数据模型
│   │   ├── schemas/      ← 请求/响应模型
│   │   └── services/     ← 业务逻辑
│   ├── data/jobs.db      ← SQLite 数据库
│   └── static/index.html ← Web 管理面板
└── mobile_app/           ← Flutter 手机 App
    └── lib/
        ├── app/shell/    ← App 框架 (Tab导航)
        ├── core/network/ ← API 客户端
        ├── features/
        │   ├── jobs/     ← 职位模块
        │   ├── favorites/← 收藏模块
        │   ├── tracking/ ← 投递跟踪模块
        │   └── notifications/ ← 通知模块
        └── shared/models/← 共享数据模型
```

## API 接口一览

| 模块 | 接口 |
|------|------|
| 职位 | `GET /api/jobs` `GET /api/jobs/{id}` |
| 收藏 | `POST/GET/DELETE /api/favorites/jobs` |
| 投递 | `POST /api/jobs/import` `GET/PATCH/DELETE /api/tracking` |
| 通知 | `GET /api/notifications` `GET /api/notifications/stats` |
| 爬虫 | `POST /api/crawler/start` `GET /api/crawler/status` |
