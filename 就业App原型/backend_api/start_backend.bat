@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo [ERROR] 未找到 Python，请先安装 Python 3 并加入 PATH。
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] 正在创建虚拟环境...
    call %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :fail
)

echo [INFO] 正在安装或校验依赖...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [INFO] 正在初始化数据库...
call .venv\Scripts\python.exe init_db.py
if errorlevel 1 goto :fail

echo [INFO] 正在启动服务...
echo [INFO] 启动后会自动打开浏览器 http://127.0.0.1:8000/
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000/'"
call .venv\Scripts\python.exe -m uvicorn app.main:app --reload
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo [ERROR] 启动失败，请根据上面的日志排查问题。
pause
exit /b 1