# XHAUS sandbox stop (Windows PowerShell)
# Usage: .\scripts\stop-sandbox-windows.bat

$ErrorActionPreference = "Continue"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir
$SandboxRoot = Join-Path $RepoRoot "后端沙盒\Sand_box"
$RunDir      = Join-Path $SandboxRoot ".run"
$SandboxPort = if ($env:SANDBOX_PORT) { $env:SANDBOX_PORT } else { "8787" }
$GatewayPort = if ($env:OPENCLAW_GATEWAY_PORT) { $env:OPENCLAW_GATEWAY_PORT } else { "18789" }

function Stop-FromPidFile($name, $file) {
    if (-not (Test-Path $file)) {
        Write-Host "[INFO] No $name PID file: $file"
        return
    }
    $pid = Get-Content $file -Raw
    $pid = $pid.Trim()
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "[ OK ] Stopped $name (PID $pid)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] $name process not running (PID $pid)"
    }
    Remove-Item $file -Force -ErrorAction SilentlyContinue
}

Write-Host "[INFO] Stopping Sand_box services..." -ForegroundColor Cyan

Stop-FromPidFile "sandbox" (Join-Path $RunDir "sandbox.pid")
Stop-FromPidFile "Gateway" (Join-Path $RunDir "gateway.pid")

if (Get-NetTCPConnection -LocalPort $SandboxPort -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "[WARN] Port $SandboxPort still in use. Try:" -ForegroundColor Yellow
    Write-Host "       Get-NetTCPConnection -LocalPort $SandboxPort | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }"
}

$cronSh = Join-Path $SandboxRoot "skills\sandbox-heartbeat\uninstall-cron.sh"
if ((Get-Command bash -ErrorAction SilentlyContinue) -and (Test-Path $cronSh)) {
    bash $cronSh 2>$null
}

if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    openclaw gateway stop 2>$null
}

Write-Host "[ OK ] Done" -ForegroundColor Green
