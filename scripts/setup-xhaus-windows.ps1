# XHAUS 一键安装脚本（Windows PowerShell）
# 功能：在仓库 RUNXHAUS\ 下克隆 Web 前端 → 配置环境 → 简易 OpenClaw → 启动并打开网页
#
# 用法（在 XHAUS-Project 仓库根目录，PowerShell）：
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup-xhaus-windows.ps1
#
# 可选环境变量：
#   $env:XHAUS_HOME = "<仓库根>\RUNXHAUS"
#   $env:SKIP_OPENCLAW_ONBOARD = "1"    # 跳过 OpenClaw 首次引导

$ErrorActionPreference = "Stop"

# ── 配置 ──────────────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir
$XhausHome   = if ($env:XHAUS_HOME) { $env:XHAUS_HOME } else { Join-Path $RepoRoot "RUNXHAUS" }
$WebRepo      = "https://github.com/hareonna-hina/XHUAS_WEBPAGE.git"
$WebDir       = Join-Path $XhausHome "XHUAS_WEBPAGE"
$RunDir       = Join-Path $XhausHome ".run"
$GatewayPort  = if ($env:OPENCLAW_GATEWAY_PORT) { $env:OPENCLAW_GATEWAY_PORT } else { "18789" }
$WebPort      = if ($env:PORT) { $env:PORT } else { "3000" }
$WebUrl       = "http://127.0.0.1:$WebPort"

function Write-Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

function Test-PortListening($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}

function Wait-Port($port, $maxSeconds = 30) {
    for ($i = 0; $i -lt $maxSeconds; $i++) {
        if (Test-PortListening $port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Set-EnvLine($file, $key, $value) {
    $lines = @()
    $found = $false
    if (Test-Path $file) {
        foreach ($line in Get-Content $file) {
            if ($line -match "^$([regex]::Escape($key))=") {
                $lines += "$key=$value"
                $found = $true
            } else {
                $lines += $line
            }
        }
    }
    if (-not $found) { $lines += "$key=$value" }
    $lines | Set-Content -Path $file -Encoding UTF8
}

# ── 1. 检查依赖 ───────────────────────────────────────────────────────
Write-Info "检查系统依赖 …"

foreach ($cmd in @("git", "node", "npm")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fail "未找到 $cmd。请先安装 Node.js 18+（含 npm）和 Git。"
    }
}

$Python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py -3"
} else {
    Write-Fail "未找到 Python 3.10+，请从 https://www.python.org 安装并勾选 Add to PATH。"
}

$nodeMajor = [int](node -p "process.versions.node.split('.')[0]")
if ($nodeMajor -lt 18) { Write-Fail "需要 Node.js 18+，当前: $(node -v)" }

Write-Ok "Node $(node -v) · Python 已找到"

# ── 2. 创建目录 ───────────────────────────────────────────────────────
Write-Info "创建运行目录: $XhausHome （位于仓库 $RepoRoot 下）"
New-Item -ItemType Directory -Force -Path $XhausHome, $RunDir | Out-Null

# ── 3. 克隆 / 更新 Web 前端仓库 ─────────────────────────────────────
if (Test-Path (Join-Path $WebDir ".git")) {
    Write-Info "仓库已存在，拉取最新代码 …"
    Push-Location $WebDir
    try { git pull --ff-only } catch { Write-Warn "git pull 失败，继续使用本地版本" }
    Pop-Location
} else {
    Write-Info "克隆 Web 前端仓库 …"
    git clone $WebRepo $WebDir
}
Write-Ok "Web 前端路径: $WebDir"

# ── 4. 安装 Node 依赖 ─────────────────────────────────────────────────
Write-Info "安装 Web 后端依赖 (npm install) …"
Push-Location (Join-Path $WebDir "backend")
npm install
Pop-Location
Write-Ok "npm 依赖安装完成"

# ── 5. 安装 Python 依赖 ─────────────────────────────────────────────
Write-Info "安装 XHAUS Python 依赖 …"
if ($Python -eq "py -3") {
    & py -3 -m pip install -q -r (Join-Path $WebDir "XHAUS\requirements.txt")
    $satReq = Join-Path $WebDir "Satellite\meta_skill\requirements.txt"
    if (Test-Path $satReq) { & py -3 -m pip install -q -r $satReq }
    $PythonPath = (& py -3 -c "import sys; print(sys.executable)")
} else {
    & $Python -m pip install -q -r (Join-Path $WebDir "XHAUS\requirements.txt")
    $satReq = Join-Path $WebDir "Satellite\meta_skill\requirements.txt"
    if (Test-Path $satReq) { & $Python -m pip install -q -r $satReq }
    $PythonPath = $Python
}
Write-Ok "Python 依赖安装完成"

# ── 6. 生成 backend/.env ─────────────────────────────────────────────
$EnvFile = Join-Path $WebDir "backend\.env"
if (-not (Test-Path $EnvFile)) {
    Write-Info "生成 backend\.env …"
    Copy-Item (Join-Path $WebDir "backend\.env.example") $EnvFile
}

$JwtSecret = node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
Set-EnvLine $EnvFile "JWT_SECRET" $JwtSecret
Set-EnvLine $EnvFile "PORT" $WebPort
Set-EnvLine $EnvFile "XHUAS_PROJECT_ROOT" ($WebDir -replace '\\', '/')
Set-EnvLine $EnvFile "XHAUS_PYTHON" ($PythonPath -replace '\\', '/')
Set-EnvLine $EnvFile "OPENCLAW_CHAT_COMPLETIONS_URL" "http://127.0.0.1:${GatewayPort}/v1/chat/completions"
Write-Ok ".env 已配置（JWT_SECRET 已自动生成）"

# ── 7. 简易 OpenClaw 配置 ─────────────────────────────────────────────
Write-Info "配置 OpenClaw …"

if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    Write-Info "安装 OpenClaw CLI (npm install -g openclaw@latest) …"
    npm install -g openclaw@latest
}
Write-Ok "OpenClaw CLI 已就绪"

$OpenclawConfig = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"
if (-not (Test-Path $OpenclawConfig) -and $env:SKIP_OPENCLAW_ONBOARD -ne "1") {
    Write-Warn "检测到首次使用 OpenClaw，需要完成约 2 分钟的简易引导："
    Write-Host "  · 选择模型提供商（如 DeepSeek / OpenAI / Anthropic）"
    Write-Host "  · 填入对应的 API Key"
    Write-Host "  · 保持 Gateway 端口为 $GatewayPort（默认即可）"
    Write-Host ""
    Read-Host "按 Enter 开始 OpenClaw 引导，或 Ctrl+C 取消"
    openclaw onboard --install-daemon
} elseif (-not (Test-Path $OpenclawConfig)) {
    Write-Warn "已跳过 OpenClaw 引导，请确保 %USERPROFILE%\.openclaw 已手动配置"
} else {
    Write-Ok "OpenClaw 配置已存在"
}

if (-not (Test-PortListening $GatewayPort)) {
    Write-Info "启动 OpenClaw Gateway (端口 $GatewayPort) …"
    $gatewayStarted = $false
    try {
        openclaw gateway restart 2>$null | Out-Null
        $gatewayStarted = $true
    } catch { }

    if (-not $gatewayStarted) {
        try {
            openclaw gateway install --force 2>$null | Out-Null
            openclaw gateway restart 2>$null | Out-Null
            $gatewayStarted = $true
        } catch { }
    }

    if (-not (Test-PortListening $GatewayPort)) {
        $gwLog = Join-Path $RunDir "openclaw-gateway.log"
        $gwJob = Start-Process -FilePath "openclaw" `
            -ArgumentList "gateway", "--port", $GatewayPort `
            -RedirectStandardOutput $gwLog `
            -RedirectStandardError $gwLog `
            -WindowStyle Hidden `
            -PassThru
        $gwJob.Id | Out-File (Join-Path $RunDir "openclaw-gateway.pid") -Encoding ascii
    }

    if (Wait-Port $GatewayPort 25) {
        Write-Ok "OpenClaw Gateway 已启动 → ws://127.0.0.1:$GatewayPort"
    } else {
        Write-Warn "Gateway 未能及时监听 $GatewayPort，请查看日志: $(Join-Path $RunDir 'openclaw-gateway.log')"
    }
} else {
    Write-Ok "OpenClaw Gateway 已在端口 $GatewayPort 运行"
}

# ── 8. 启动 Web 后端 ──────────────────────────────────────────────────
if (Test-PortListening $WebPort) {
    Write-Warn "端口 $WebPort 已被占用，尝试结束旧进程 …"
    Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

if (Test-PortListening $WebPort) {
    Write-Warn "端口 $WebPort 仍被占用，请手动结束后重新运行本脚本"
} else {
    Write-Info "启动 Web 后端 (端口 $WebPort) …"
    $webLog = Join-Path $RunDir "web-backend.log"
    $webJob = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm start" `
        -WorkingDirectory (Join-Path $WebDir "backend") `
        -RedirectStandardOutput $webLog `
        -RedirectStandardError $webLog `
        -WindowStyle Hidden `
        -PassThru
    $webJob.Id | Out-File (Join-Path $RunDir "web-backend.pid") -Encoding ascii

    if (-not (Wait-Port $WebPort 30)) {
        Write-Fail "Web 后端启动失败，请查看: $webLog"
    }
    Write-Ok "Web 后端已启动"
}

# ── 9. 打开浏览器 ─────────────────────────────────────────────────────
Write-Info "打开 Web 界面 …"
Start-Sleep -Seconds 1
Start-Process $WebUrl

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Ok "XHAUS 安装完成！"
Write-Host ""
Write-Host "  Web 界面:     $WebUrl"
Write-Host "  OpenClaw:     ws://127.0.0.1:$GatewayPort"
Write-Host "  安装目录:     $XhausHome"
Write-Host "  日志目录:     $RunDir"
Write-Host ""
Write-Host "  首次使用步骤："
Write-Host "    1. 在网页点击「开始使用」"
Write-Host "    2. WebSocket 地址填入: ws://127.0.0.1:$GatewayPort"
Write-Host "    3. 选择人格预设（如 Franziska、Emma）后开始对话"
Write-Host ""
Write-Host "  停止服务："
Write-Host "    在任务管理器中结束 web-backend / openclaw 相关进程"
Write-Host "    或运行: openclaw gateway stop"
Write-Host "============================================================" -ForegroundColor Green
