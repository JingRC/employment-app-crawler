$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if ([string]::IsNullOrWhiteSpace($env:BACKEND_PORT)) {
    $env:BACKEND_PORT = '8000'
}
if ([string]::IsNullOrWhiteSpace($env:BACKEND_HOST)) {
    $env:BACKEND_HOST = '127.0.0.1'
}

$backendPort = [int]$env:BACKEND_PORT
$backendHost = [string]$env:BACKEND_HOST
$backendUrl = 'http://' + $backendHost + ':' + $backendPort + '/'

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Executable = 'py'; Arguments = @('-3') }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Executable = 'python'; Arguments = @() }
    }
    throw 'Python 3 was not found in PATH.'
}

function Test-TruthyEnv([string]$name) {
    $value = [string](Get-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue).Value
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $false
    }
    return @('1', 'true', 'yes', 'on') -contains $value.Trim().ToLowerInvariant()
}

function Stop-ExistingBackend {
    param(
        [int]$Port,
        [string]$HostName,
        [bool]$ForceRestart
    )

    Write-Host ("[INFO] Checking for an existing service on port {0}..." -f $Port) -ForegroundColor Cyan
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host ("[INFO] No existing listener was found on port {0}." -f $Port) -ForegroundColor DarkCyan
        return
    }

    $baseUrl = 'http://' + $HostName + ':' + $Port
    try {
        $statusResponse = Invoke-RestMethod -Uri ($baseUrl + '/api/crawler/status') -TimeoutSec 5 -ErrorAction Stop
        $taskStatus = [string]$statusResponse.data.status
        if (($taskStatus -eq 'running' -or $taskStatus -eq 'cancelling') -and -not $ForceRestart) {
            throw [System.InvalidOperationException]::new('CURRENT_TASK_RUNNING')
        }
        if ($taskStatus -eq 'running' -or $taskStatus -eq 'cancelling') {
            Write-Host '[WARN] A crawler task is still running, but FORCE_RESTART_RUNNING_TASK is enabled. Continuing with a forced restart.' -ForegroundColor Yellow
        }
        else {
            Write-Host ("[INFO] Existing backend status is {0}; restart is allowed." -f $taskStatus) -ForegroundColor DarkCyan
        }
    }
    catch [System.InvalidOperationException] {
        if ($_.Exception.Message -eq 'CURRENT_TASK_RUNNING') {
            Write-Host '[ERROR] A crawler task is still running, so this restart was skipped to avoid interrupting it.' -ForegroundColor Red
            Write-Host '[ERROR] To start on another port, set BACKEND_PORT=8001 and run again.' -ForegroundColor Red
            Write-Host '[ERROR] To force override the running task, set FORCE_RESTART_RUNNING_TASK=1.' -ForegroundColor Red
            exit 1
        }
        throw
    }
    catch {
        Write-Host '[INFO] Failed to read crawler status from the existing service. Treating it as a normal port conflict.' -ForegroundColor DarkCyan
    }

    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host ("[INFO] Stopped existing process PID={0}." -f $processId) -ForegroundColor DarkCyan
        }
        catch {
            Write-Host ("[WARN] Failed to stop existing process PID={0}." -f $processId) -ForegroundColor Yellow
        }
    }
}

try {
    $pythonCmd = Get-PythonCommand

    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Write-Host '[INFO] Creating virtual environment...' -ForegroundColor Cyan
        & $pythonCmd.Executable @($pythonCmd.Arguments) -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    Write-Host '[INFO] Installing or validating dependencies...' -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host '[INFO] Initializing database...' -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe init_db.py
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Stop-ExistingBackend -Port $backendPort -HostName $backendHost -ForceRestart:(Test-TruthyEnv 'FORCE_RESTART_RUNNING_TASK')

    Write-Host '[INFO] Starting backend service...' -ForegroundColor Green
    Write-Host ("[INFO] The browser will open automatically at {0}" -f $backendUrl) -ForegroundColor Green
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        "Start-Sleep -Seconds 3; Start-Process '$backendUrl'"
    ) | Out-Null

    & .\.venv\Scripts\python.exe -m uvicorn app.main:app --host $backendHost --port $backendPort
    exit $LASTEXITCODE
}
catch {
    Write-Host ''
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}