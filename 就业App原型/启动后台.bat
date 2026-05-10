@echo off
chcp 65001 >nul
title 就业数据后台 - 爬虫采集 + API服务

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║      就业数据后台 (Backend)                    ║
echo  ║      爬虫采集 + API 服务 + 数据管理             ║
echo  ╚══════════════════════════════════════════════╝
echo.
echo  启动内容:
echo     - SQLite 数据库初始化
echo     - FastAPI 后台服务 (端口 8000)
echo     - Web 管理面板
echo     - 爬虫调度接口
echo.
echo  启动后自动打开浏览器: http://127.0.0.1:8000/
echo.

cd /d "%~dp0backend_api"
call start_backend.bat
pause
