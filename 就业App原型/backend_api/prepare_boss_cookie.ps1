$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Get-PythonExecutable {
    if (Test-Path '.venv\Scripts\python.exe') {
        return '.\.venv\Scripts\python.exe'
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return 'py -3'
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return 'python'
    }
    throw '未找到 Python，请先安装 Python 3 并加入 PATH。'
}

function Invoke-PythonCommand {
    param(
        [string]$PythonExecutable,
        [string[]]$Arguments
    )
    if ($PythonExecutable -eq 'py -3') {
        & py -3 @Arguments
        return
    }
    & $PythonExecutable @Arguments
}

try {
    $pythonExe = Get-PythonExecutable

    Write-Host '[INFO] 检查 Boss Cookie 预热依赖...' -ForegroundColor Cyan
    Invoke-PythonCommand $pythonExe @('-c', "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('DrissionPage') else 1)")
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[INFO] 正在安装 DrissionPage...' -ForegroundColor Cyan
        Invoke-PythonCommand $pythonExe @('-m', 'pip', 'install', 'DrissionPage')
    }

    if (-not $env:ZHIPIN_QUERY) { $env:ZHIPIN_QUERY = 'Java' }
    if (-not $env:ZHIPIN_CITY) { $env:ZHIPIN_CITY = '101010100' }
    $env:ZHIPIN_MODE = 'prepare_cookie'
    $env:ZHIPIN_RUNTIME_MODE = 'requests_only'

    Write-Host '[INFO] 即将打开 Boss 直聘页面进行 Cookie 预热。' -ForegroundColor Green
    Write-Host '[INFO] 如果跳到登录页或验证页，请在浏览器里手动完成登录/验证，脚本会等待并自动保存 Cookie。' -ForegroundColor Green
    Write-Host ('[INFO] 当前预热参数：query=' + $env:ZHIPIN_QUERY + ' / city=' + $env:ZHIPIN_CITY) -ForegroundColor Green

    Invoke-PythonCommand $pythonExe @('..\..\zhipin_joblist_crawl.py')
}
catch {
    Write-Host ''
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host '按回车键退出'
    exit 1
}