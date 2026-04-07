# 就业 App 原型

本目录包含两个最小项目骨架：

1. backend_api: FastAPI 后端原型
2. mobile_app: Flutter 前端原型

## FastAPI 启动

1. 进入 backend_api
2. 安装依赖: pip install -r requirements.txt
3. 可选初始化数据库: python init_db.py
4. 启动服务: uvicorn app.main:app --reload
5. Windows 下一键启动:
	- 推荐: 在 PowerShell 中执行 ./start_backend.ps1
	- 兼容方式: 双击 backend_api/start_backend.bat，或在 PowerShell 中执行 ./start_backend.bat
	- 两个启动脚本都会在服务起来后自动打开浏览器首页 http://127.0.0.1:8000/
6. Boss Cookie 预热:
	- 前端推荐流程：先点“打开 Boss 登录页”，登录完成后再点“我已登录，开始保存 Boss Cookie”
	- 如需先确认状态，可点“检测当前 Boss Cookie”查看是否存在、是否完整
	- 备用方式：在 PowerShell 中执行 ./prepare_boss_cookie.ps1
	- 两种方式都会把 Cookie 保存到 zhipin_secrets.json

说明:

1. 首次启动时会自动创建 SQLite 数据库并导入 [代码/提交/joblist_Java_101120200.json](代码/提交/joblist_Java_101120200.json) 样本数据
2. SQLite 文件位置为 backend_api/data/jobs.db
3. 可访问接口:
	1. /api/jobs
	2. /api/jobs/{job_id}
	3. /api/favorites/companies
	4. /api/notifications

## Flutter 启动

1. 确保本机已安装 Flutter SDK
2. 进入 mobile_app
3. 执行: flutter pub get
4. 执行: flutter run

## 当前状态

1. 后端提供基于 SQLite 的职位列表、职位详情、收藏企业、通知列表接口
2. 前端提供职位列表页、职位详情页、收藏页、通知页的基础页面
3. 当前职位数据来自本地样本 JSON，后续可替换为真实采集导入流程
