@echo off
chcp 65001 >nul
title 就业手机App - Flutter

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║      就业手机App (Flutter)                     ║
echo  ║      职位浏览 + 收藏 + 投递跟踪                  ║
echo  ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0mobile_app"

echo [1/3] 检查 Flutter 环境...
where flutter >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Flutter SDK
    echo   安装指引: https://docs.flutter.dev/get-started/install/windows
    pause
    exit /b 1
)

echo [2/3] 安装依赖...
call flutter pub get
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [3/3] 启动应用...
echo.
echo   ⚠ 使用说明:
echo     - 模拟器: 自动连接，后台地址为 10.0.2.2:8000
echo     - 真机: 需将 api_client.dart 中 _baseUrl 改为电脑IP
echo.
echo   按 Ctrl+C 停止
echo.

flutter run

pause
