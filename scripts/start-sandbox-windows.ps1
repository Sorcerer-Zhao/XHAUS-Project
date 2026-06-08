# XHAUS sandbox start (Windows PowerShell)
# Usage:
#   .\scripts\start-sandbox-windows.bat
#   .\scripts\start-sandbox-windows.bat -SandboxOnly
# Stop: .\scripts\stop-sandbox-windows.bat

param(
    [switch]$SandboxOnly,
    [switch]$Demo
)

$ErrorActionPreference = "Stop"

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot     = Split-Path -Parent $ScriptDir
$SandboxRoot  = Join-Path $RepoRoot "后端沙盒\Sand_box"
$DynamicDir   = Join-Path $SandboxRoot "dynamic-sandbox"
$RunDir       = Join-Path $SandboxRoot ".run"
$SandboxPort  = if ($env:SANDBOX_PORT) { $env:SANDBOX_PORT } else { "8787" }
$GatewayPort  = if ($env:OPENCLAW_GATEWAY_PORT) { $env:OPENCLAW_GATEWAY_PORT } else { "18789" }

function Write-Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

function Test-PortListening($port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Port($port, $maxSeconds = 30) {
    for ($i = 0; $i -lt $maxSeconds; $i++) {
        if (Test-PortListening $port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Invoke-SandboxApi($method, $path, $body = $null) {
    $uri = "http://127.0.0.1:${SandboxPort}${path}"
    if ($body) {
        Invoke-RestMethod -Method $method -Uri $uri -Body $body -ContentType "application/json" | Out-Null
    } else {
        Invoke-RestMethod -Method $method -Uri $uri | Out-Null
    }
}

if (-not (Test-Path $SandboxRoot)) {
    Write-Fail "Sandbox directory not found: $SandboxRoot"
}

Write-Info "Sandbox root: $SandboxRoot"

foreach ($cmd in @("node")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fail "Missing $cmd. Install Node.js 18+ first."
    }
}

$Python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
} else {
    Write-Fail "Python 3.10+ not found."
}

function Invoke-Python {
    param([string[]]$Args)
    if ($Python -eq "py") {
        & py -3 @Args
    } else {
        & $Python @Args
    }
}

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  XHAUS Sandbox - one-click start (Windows)" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

Write-Info "Installing sandbox Python dependencies..."
Invoke-Python @("-m", "pip", "install", "-q", "-r", (Join-Path $DynamicDir "requirements.txt"))

if (Test-PortListening $SandboxPort) {
    Write-Ok "Sandbox already running on port $SandboxPort"
} else {
    Write-Info "Starting dynamic-sandbox on port $SandboxPort..."
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    $logFile = Join-Path $RunDir "sandbox.log"
    $pidFile = Join-Path $RunDir "sandbox.pid"

    $proc = Start-Process -FilePath $(if ($Python -eq "py") { "py" } else { $Python }) `
        -ArgumentList $(if ($Python -eq "py") { @("-3", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $SandboxPort, "--no-access-log") } else { @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $SandboxPort, "--no-access-log") }) `
        -WorkingDirectory $DynamicDir `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $logFile `
        -WindowStyle Hidden `
        -PassThru

    $proc.Id | Out-File $pidFile -Encoding ascii

    if (-not (Wait-Port $SandboxPort 30)) {
        Write-Fail "Sandbox start timed out. Check: $logFile"
    }
    Write-Ok "Sandbox started (PID $($proc.Id), log: $logFile)"
}

try {
    Invoke-SandboxApi "POST" "/admin/reset" '{"seed":42}'
    Invoke-SandboxApi "POST" "/admin/clock" '{"time_scale":30}'
    Write-Ok "World reset seed=42, time scale 30x"
} catch {
    Write-Warn "World reset/clock failed: $_"
}

Write-Info "Health check..."
$healthScript = Join-Path $SandboxRoot "scripts\health-check.js"
& node $healthScript
if ($LASTEXITCODE -ne 0) { Write-Fail "Health check failed" }
Write-Ok "Sandbox API healthy"

if ($SandboxOnly) {
    Write-Host ""
    Write-Ok "Sandbox ready -> http://127.0.0.1:${SandboxPort}/docs"
    exit 0
}

Write-Info "Mounting Skills to OpenClaw workspaces..."
$installSh = Join-Path $SandboxRoot "skills\install.sh"
if (Get-Command bash -ErrorAction SilentlyContinue) {
    bash $installSh
} else {
    Write-Warn "bash not found (install Git for Windows). Skipping Skills mount."
    Write-Warn "Run manually: bash `"$installSh`""
}

if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    if (Test-PortListening $GatewayPort) {
        Write-Ok "OpenClaw Gateway already on port $GatewayPort"
    } else {
        Write-Info "Starting OpenClaw Gateway on port $GatewayPort..."
        $gwLog = Join-Path $RunDir "gateway.log"
        $gwPid = Join-Path $RunDir "gateway.pid"
        $gwProc = Start-Process -FilePath "openclaw" `
            -ArgumentList "gateway", "--port", $GatewayPort `
            -RedirectStandardOutput $gwLog `
            -RedirectStandardError $gwLog `
            -WindowStyle Hidden `
            -PassThru
        $gwProc.Id | Out-File $gwPid -Encoding ascii
        if (Wait-Port $GatewayPort 25) {
            Write-Ok "Gateway started -> ws://127.0.0.1:$GatewayPort"
        } else {
            Write-Warn "Gateway failed to start. Log: $gwLog"
        }
    }

    $cronSh = Join-Path $SandboxRoot "skills\sandbox-heartbeat\install-cron.sh"
    if ((Test-Path $cronSh) -and (Get-Command bash -ErrorAction SilentlyContinue)) {
        Write-Info "Registering sandbox-heartbeat cron..."
        bash $cronSh
    }
} else {
    Write-Warn "openclaw CLI not found. Start manually: openclaw gateway --port $GatewayPort"
}

if ($Demo) {
    Write-Info "Running end-to-end demo..."
    & node (Join-Path $SandboxRoot "demo\e2e-story.js")
}

Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Ok "Sandbox startup complete"
Write-Host "  Sandbox API:  http://127.0.0.1:${SandboxPort}/docs"
Write-Host "  OpenClaw:     ws://127.0.0.1:${GatewayPort}"
Write-Host "  Full check:   node `"$healthScript`" --skills"
Write-Host "  Stop:         .\scripts\stop-sandbox-windows.bat"
Write-Host "====================================================" -ForegroundColor Green
