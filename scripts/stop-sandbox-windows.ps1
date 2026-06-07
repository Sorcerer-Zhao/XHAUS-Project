# XHAUS 动态沙盒一键停止（Windows PowerShell）
#
# 用法：.\scripts\stop-sandbox-windows.ps1

$ErrorActionPreference = "Continue"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir
$SandboxRoot = Join-Path $RepoRoot "后端沙盒\Sand_box"
$RunDir      = Join-Path $SandboxRoot ".run"
$SandboxPort = if ($env:SANDBOX_PORT) { $env:SANDBOX_PORT } else { "8787" }
$GatewayPort = if ($env:OPENCLAW_GATEWAY_PORT) { $env:OPENCLAW_GATEWAY_PORT } else { "18789" }

function Stop-FromPidFile($name, $file) {
    if (-not (Test-Path $file)) {
        Write-Host "[INFO] 无 $name PID 文件: $file"
        return
    }
    $pid = Get-Content $file -Raw
    $pid = $pid.Trim()
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "[ OK ] 已停止 $name (PID $pid)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] $name 进程已不存在 (PID $pid)"
    }
    Remove-Item $file -Force -ErrorAction SilentlyContinue
}

Write-Host "[INFO] 停止 Sand_box 服务 …" -ForegroundColor Cyan

Stop-FromPidFile "沙箱" (Join-Path $RunDir "sandbox.pid")
Stop-FromPidFile "Gateway" (Join-Path $RunDir "gateway.pid")

if (Get-NetTCPConnection -LocalPort $SandboxPort -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "[WARN] 端口 $SandboxPort 仍被占用。可尝试:" -ForegroundColor Yellow
    Write-Host "       Get-NetTCPConnection -LocalPort $SandboxPort | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }"
}

$cronSh = Join-Path $SandboxRoot "skills\sandbox-heartbeat\uninstall-cron.sh"
if ((Get-Command bash -ErrorAction SilentlyContinue) -and (Test-Path $cronSh)) {
    bash $cronSh 2>$null
}

if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    openclaw gateway stop 2>$null
}

Write-Host "[ OK ] 完成" -ForegroundColor Green
