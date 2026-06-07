# XHAUS 动态沙盒一键启动（Windows PowerShell）
# 在仓库根目录运行
#
# 用法：
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\start-sandbox-windows.ps1           # 沙盒 + Skills（需 Git Bash）+ Gateway + Cron
#   .\scripts\start-sandbox-windows.ps1 -SandboxOnly # 仅启动沙盒引擎
#
# 停止：.\scripts\stop-sandbox-windows.ps1

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
    Write-Fail "找不到沙盒目录: $SandboxRoot"
}

Write-Info "沙盒目录: $SandboxRoot"

# ── 依赖检查 ──
foreach ($cmd in @("node")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fail "未找到 $cmd，请先安装 Node.js 18+"
    }
}

$Python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $PythonArgs = @("-3")
} else {
    Write-Fail "未找到 Python 3.10+"
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
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  XHAUS 动态沙盒 · 一键启动 (Windows)              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. 安装 Python 依赖 ──
Write-Info "安装沙盒 Python 依赖 …"
Invoke-Python @("-m", "pip", "install", "-q", "-r", (Join-Path $DynamicDir "requirements.txt"))

# ── 2. 启动沙盒 ──
if (Test-PortListening $SandboxPort) {
    Write-Ok "沙盒已在运行 (端口 $SandboxPort)"
} else {
    Write-Info "启动 dynamic-sandbox (端口 $SandboxPort) …"
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
        Write-Fail "沙盒启动超时，请查看: $logFile"
    }
    Write-Ok "沙盒已启动 (PID $($proc.Id), 日志: $logFile)"
}

# ── 3. 复位世界 + 加速时钟 ──
try {
    Invoke-SandboxApi "POST" "/admin/reset" '{"seed":42}'
    Invoke-SandboxApi "POST" "/admin/clock" '{"time_scale":30}'
    Write-Ok "世界已复位 seed=42，倍速 30x"
} catch {
    Write-Warn "世界复位/倍速设置失败: $_"
}

# ── 4. 健康检查 ──
Write-Info "健康检查 …"
$healthScript = Join-Path $SandboxRoot "scripts\health-check.js"
& node $healthScript
if ($LASTEXITCODE -ne 0) { Write-Fail "健康检查失败" }
Write-Ok "沙盒 API 健康"

if ($SandboxOnly) {
    Write-Host ""
    Write-Ok "沙盒已就绪 → http://127.0.0.1:${SandboxPort}/docs"
    exit 0
}

# ── 5. 挂载 Skills（需 Git Bash）──
Write-Info "挂载 Skills 到 OpenClaw workspaces …"
$installSh = Join-Path $SandboxRoot "skills\install.sh"
if (Get-Command bash -ErrorAction SilentlyContinue) {
    bash $installSh
} else {
    Write-Warn "未找到 bash（可安装 Git for Windows），已跳过 Skills 挂载"
    Write-Warn "手动运行: bash `"$installSh`""
}

# ── 6. OpenClaw Gateway ──
if (Get-Command openclaw -ErrorAction SilentlyContinue) {
    if (Test-PortListening $GatewayPort) {
        Write-Ok "OpenClaw Gateway 已在端口 $GatewayPort 运行"
    } else {
        Write-Info "启动 OpenClaw Gateway (端口 $GatewayPort) …"
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
            Write-Ok "Gateway 已启动 → ws://127.0.0.1:$GatewayPort"
        } else {
            Write-Warn "Gateway 启动失败，日志: $gwLog"
        }
    }

    # ── 7. 管家心跳 Cron ──
    $cronSh = Join-Path $SandboxRoot "skills\sandbox-heartbeat\install-cron.sh"
    if ((Test-Path $cronSh) -and (Get-Command bash -ErrorAction SilentlyContinue)) {
        Write-Info "注册 sandbox-heartbeat Cron …"
        bash $cronSh
    }
} else {
    Write-Warn "未找到 openclaw CLI，请手动: openclaw gateway --port $GatewayPort"
}

# ── 8. 端到端演示（可选）──
if ($Demo) {
    Write-Info "运行端到端演示 …"
    & node (Join-Path $SandboxRoot "demo\e2e-story.js")
}

Write-Host ""
Write-Host "══════════════════════════════════════════════════" -ForegroundColor Green
Write-Ok "沙盒一键启动完成"
Write-Host "  沙箱 API:   http://127.0.0.1:${SandboxPort}/docs"
Write-Host "  OpenClaw:   ws://127.0.0.1:${GatewayPort}"
Write-Host "  完整检查:   node `"$healthScript`" --skills"
Write-Host "  停止服务:   .\scripts\stop-sandbox-windows.ps1"
Write-Host "══════════════════════════════════════════════════" -ForegroundColor Green
