# 免费云端 requests-only 部署方案

## 目标

把以下来源放到免费云端定时跑：

- qdhr
- sdgxbys
- ncss24365
- jobmohrss

Boss、拉勾这类需要稳定浏览器态和人工验证的来源继续留在本机或低价 VPS。

## 方案选型

当前仓库已经补了 GitHub Actions 方案，核心思路是：

1. GitHub Actions 按计划定时启动一个短时任务。
2. 任务只运行 requests-only 来源，不启动浏览器。
3. 抓取结果直接写入 就业App原型/backend_api/data/jobs.db。
4. 任务结束后把更新后的 jobs.db 和 cloud_sync_last_result.json 自动提交回仓库。

这个方案的优点：

- 免费。
- 不需要常驻服务器。
- 数据能直接持久化，不会因为 runner 是临时机器而丢失。
- 最适合 SQLite 小规模项目。

## 已补文件

- .github/workflows/requests-only-cloud-sync.yml
- 就业App原型/backend_api/run_requests_only_cloud_sync.py

## 默认执行频率

工作流当前使用：

- 每天 3 次执行一次
- 对应北京时间约 09:15 / 14:15 / 19:15
- 同时支持手动触发 workflow_dispatch

注意：GitHub Actions 的 cron 使用 UTC 时间。

## 默认抓取范围

run_requests_only_cloud_sync.py 当前默认：

- qdhr：青岛，高收益词 4 个，8 页
- sdgxbys：山东/青岛/济南，4 个泛岗词，4 页
- ncss24365：全国 + 部分城市，3 个关键词，2 页
- jobmohrss：全国 + 部分城市，3 个关键词，2 页

如果后续要调范围，优先改 run_requests_only_cloud_sync.py 里的 REQUESTS_ONLY_PRESETS。

## 本地验证方式

为了避免本地验证时误触发真实抓取，当前脚本已经补了两个显式模式：

1. 只验证启动、建库和摘要写出：

	python run_requests_only_cloud_sync.py --validate-startup

2. 显式跳过所有来源：

	python run_requests_only_cloud_sync.py --sources none

这两种方式都应该快速退出，并生成 cloud_sync_last_result.json。

## 你需要做的事

### 1. 把项目放到 GitHub 仓库

建议：

- 如果仓库不涉及敏感内容，可以用 public
- 如果是 private，也能跑，但受 GitHub 免费分钟数限制

### 2. 打开 GitHub Actions

进入仓库：

- Actions
- 启用 workflows

### 3. 确认默认 Token 有写权限

进入：

- Settings
- Actions
- General

确认 GITHUB_TOKEN 权限允许：

- Read and write permissions

否则 workflow 没法把 jobs.db 提交回仓库。

### 4. 首次手动运行一次

进入：

- Actions
- requests-only-cloud-sync
- Run workflow

现在手动触发时还可以直接填两个参数：

- sources：逗号分隔来源，例如 qdhr 或 qdhr,sdgxbys
- validate_startup：勾选后只做启动验证，不执行真实抓取
- retry_once_on_failure：首次真实抓取失败时自动再试一次

建议首次先这样跑：

- sources=none
- validate_startup=true

先确认 workflow 能正常启动、安装依赖、初始化数据库并写出摘要；确认通过后，再手动跑一次真实来源。

真实抓取阶段默认会在首轮失败后自动重试一次，更适合应对免费 runner 上的临时网络抖动；如果后面你想做严格失败观测，也可以把 retry_once_on_failure 改成 false。

现在每次 workflow 跑完后，Actions 页面还会自动生成一段摘要，直接显示：

- 本次是否为启动验证
- 本次执行了哪些来源
- 总抓取量 / 新增量 / 更新量
- 每个来源的 success 或 failed 状态

后续你看运行结果时，优先看页面顶部 Summary，不需要先翻完整日志。

第一次运行后，仓库里会自动出现或更新：

- 就业App原型/backend_api/data/jobs.db
- 就业App原型/backend_api/data/cloud_sync_last_result.json

### 5. 本地继续只负责浏览器态来源

本地继续跑：

- boss_dp
- boss
- lagou

云端不要跑这些来源。

## 本地如何同步云端结果

最简单的方法：

1. 本地 git pull
2. 启动 backend_api
3. 直接读取更新后的 jobs.db

因为当前数据就是 SQLite 文件本身，所以 pull 下来就是最新库。

## 风险和限制

### 1. SQLite 会越来越大

当前方案适合早期项目。后续如果 jobs.db 变得很大，频繁提交会变慢。

### 2. private 仓库分钟数有限

如果你是 private 仓库，建议先维持每天 2 到 3 次，而不是太高频。当前默认已经收敛到每天 3 次。

### 3. 免费 runner 不是固定 IP

所以不要把 Boss 这类来源放上去。requests-only 来源相对更适合。

## 推荐运行分层

### 云端免费跑

- qdhr
- sdgxbys
- ncss24365
- jobmohrss

### 本机或低价 VPS 跑

- boss_dp
- boss
- lagou

## 下一步可继续补的内容

如果继续迭代，更适合补：

1. workflow_dispatch 输入参数，允许你临时只跑某一个来源
2. 失败批次自动重试
3. 云端跑完后自动导出 CSV 快照
4. 把 stale 默认阈值从 72 小时提高到 168 小时