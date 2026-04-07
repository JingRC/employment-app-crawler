$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Executable = 'py'; Arguments = @('-3') }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Executable = 'python'; Arguments = @() }
    }
    throw '未找到 Python，请先安装 Python 3 并加入 PATH。'
}

try {
    $pythonCmd = Get-PythonCommand

    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Write-Host '[INFO] 正在创建虚拟环境...' -ForegroundColor Cyan
        & $pythonCmd.Executable @($pythonCmd.Arguments) -m venv .venv
    }

    Write-Host '[INFO] 正在安装或校验依赖...' -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt

    Write-Host '[INFO] 正在初始化数据库...' -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe init_db.py

    Write-Host '[INFO] 正在启动服务...' -ForegroundColor Green
    Write-Host '[INFO] 启动后会自动打开浏览器 http://127.0.0.1:8000/' -ForegroundColor Green
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000/'"
    )
    & .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
}
catch {
    Write-Host ''
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host '按回车键退出'
    exit 1
}