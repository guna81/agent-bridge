# ==============================================================================
# LLM CLI Gateway (ai-credit-proxy) - Windows Service Manager (PowerShell)
# Manages the app as an always-running background service via Windows Task Scheduler
# Usage: powershell -ExecutionPolicy Bypass -File .\manage-service.ps1 {install|start|stop|restart|status|logs|uninstall}
# ==============================================================================

param (
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("install", "start", "stop", "restart", "status", "logs", "uninstall")]
    [string]$Action
)

$ErrorActionPreference = "Stop"

$ServiceName = "LLMCliGateway"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RepoDir "backend"
$PythonBin = Join-Path $BackendDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $env:USERPROFILE ".ai-credit-proxy\logs"
$LogFile = Join-Path $LogDir "server.log"
$ErrLogFile = Join-Path $LogDir "server.err.log"
$Port = 8765

# Load port from backend\.env if present
$EnvFile = Join-Path $BackendDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*PROXY_PORT\s*=\s*([0-9]+)") {
            $Port = [int]$matches[1]
        }
    }
}

function Check-Python {
    if (-not (Test-Path $PythonBin)) {
        Write-Error "Python virtual environment not found at: $PythonBin`nPlease run: cd backend; uv sync"
        exit 1
    }
}

function Ensure-LogDirs {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    if (-not (Test-Path $LogFile)) {
        New-Item -ItemType File -Path $LogFile -Force | Out-Null
    }
    if (-not (Test-Path $ErrLogFile)) {
        New-Item -ItemType File -Path $ErrLogFile -Force | Out-Null
    }
}

function Stop-ProcessOnPort {
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) {
                $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
                if ($p -and ($p.ProcessName -match "python")) {
                    Write-Host "Stopping existing Python process on port $Port (PID: $($p.Id))..."
                    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        # Fallback for systems without Get-NetTCPConnection
        $netstat = netstat -ano | Select-String ":$Port " | Select-String "LISTENING"
        foreach ($line in $netstat) {
            $parts = ($line -split '\s+') | Where-Object { $_ -ne "" }
            $pidToKill = $parts[-1]
            if ($pidToKill -as [int]) {
                Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Wait-ForHealth {
    Write-Host "Waiting for service to respond on http://127.0.0.1:$Port..."
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($res.ok -eq $true) {
                $ready = $true
                break
            }
        } catch { }
    }

    if ($ready) {
        Write-Host "Service is running successfully!" -ForegroundColor Green
        Write-Host "URL: http://127.0.0.1:$Port"
        Write-Host "Logs: $LogFile"
        Write-Host "Task Scheduler will restart this task automatically on failure and on user logon."
    } else {
        Write-Warning "Service was triggered but health check (/healthz) did not respond in time."
        Write-Host "Check error log at: $ErrLogFile"
    }
}

function Install-Service {
    Check-Python
    Ensure-LogDirs
    Write-Host "Installing $ServiceName as a Windows Scheduled Task (Always-On)..."

    # Create launcher VBScript / CMD script so it runs silently in the background without pop-up window
    $VbsScript = Join-Path $LogDir "run_silent.vbs"
    $BatchScript = Join-Path $LogDir "run_server.cmd"

    $BatchContent = @"
@echo off
set "PYTHONUNBUFFERED=1"
cd /d "$BackendDir"
"$PythonBin" run.py >> "$LogFile" 2>> "$ErrLogFile"
"@
    Set-Content -Path $BatchScript -Value $BatchContent -Encoding ASCII

    $VbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """ & "$BatchScript" & """", 0, False
"@
    Set-Content -Path $VbsScript -Value $VbsContent -Encoding ASCII

    # Unregister old task if exists
    Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false -ErrorAction SilentlyContinue

    # Register task
    $ActionObj = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsScript`"" -WorkingDirectory $BackendDir
    $TriggerObj = New-ScheduledTaskTrigger -AtLogOn
    $SettingsObj = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask -TaskName $ServiceName -Action $ActionObj -Trigger $TriggerObj -Settings $SettingsObj -Description "LLM CLI Gateway Background Service" | Out-Null
    Write-Host "Scheduled Task registered."

    Stop-ProcessOnPort
    Start-ScheduledTask -TaskName $ServiceName
    Wait-ForHealth
}

function Start-ServiceCmd {
    Check-Python
    Stop-ProcessOnPort
    try {
        Start-ScheduledTask -TaskName $ServiceName
        Write-Host "Service start triggered."
        Wait-ForHealth
    } catch {
        Write-Error "Task not registered. Run .\manage-service.ps1 install first."
    }
}

function Stop-ServiceCmd {
    try {
        Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
    } catch { }
    Stop-ProcessOnPort
    Write-Host "Service stopped."
}

function Restart-ServiceCmd {
    Write-Host "Restarting $ServiceName..."
    Stop-ServiceCmd
    Start-Sleep -Seconds 1
    Start-ServiceCmd
}

function Status-ServiceCmd {
    Write-Host "=== Service Status (Windows: $ServiceName) ==="
    $task = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Task Scheduler: REGISTERED ($($task.State))"
    } else {
        Write-Host "Task Scheduler: NOT REGISTERED"
    }

    $isListening = $false
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = ($conns | Select-Object -ExpandProperty OwningProcess) -join ", "
            Write-Host "Port $Port: LISTENING (PID: $pids)"
            $isListening = $true
        }
    } catch { }

    if (-not $isListening) {
        Write-Host "Port $Port: NOT LISTENING"
    }

    try {
        $res = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($res.ok -eq $true) {
            Write-Host "Health Check (/healthz): OK" -ForegroundColor Green
            Write-Host "Application is UP at http://127.0.0.1:$Port"
        } else {
            Write-Host "Health Check (/healthz): UNEXPECTED RESPONSE" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Health Check (/healthz): FAILED / UNRESPONSIVE" -ForegroundColor Red
    }
    Write-Host "Log file: $LogFile"
}

function Show-Logs {
    Ensure-LogDirs
    Write-Host "Streaming logs from $LogFile (Press Ctrl+C to exit)..."
    Get-Content -Path $LogFile -Wait -Tail 50
}

function Uninstall-Service {
    Write-Host "Uninstalling $ServiceName..."
    Stop-ServiceCmd
    Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled task removed."
}

switch ($Action) {
    "install"   { Install-Service }
    "start"     { Start-ServiceCmd }
    "stop"      { Stop-ServiceCmd }
    "restart"   { Restart-ServiceCmd }
    "status"    { Status-ServiceCmd }
    "logs"      { Show-Logs }
    "uninstall" { Uninstall-Service }
}
