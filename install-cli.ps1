$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js and npm first.' }
Push-Location "$root\backend"
try { uv sync --python 3.12 --inexact; if ($LASTEXITCODE -ne 0) { throw 'Backend installation failed.' } } finally { Pop-Location }
Push-Location "$root\frontend"
try {
    npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
$bin = if ($env:AGENTBRIDGE_BIN_DIR) { $env:AGENTBRIDGE_BIN_DIR } else { Join-Path $env:LOCALAPPDATA 'AgentBridge\bin' }
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$launcher = Join-Path $bin 'agentbridge.cmd'
if (Test-Path $launcher) { throw "$launcher already exists; remove it or choose AGENTBRIDGE_BIN_DIR." }
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
@"
@echo off
set "PYTHONPATH=$root\backend;%PYTHONPATH%"
"$python" -m app.cli %*
"@ | Set-Content -Encoding Ascii $launcher
Write-Host "Installed $launcher. Keep this checkout in place."
Write-Host "Add $bin to your PATH, then run: agentbridge start --personal"
