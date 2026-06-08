# XHAUS Web setup (Windows PowerShell)
# Usage (from repo root):
#   .\scripts\setup-xhaus-windows.bat
#   or: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-xhaus-windows.ps1
#
# Optional: $env:SKIP_OPENCLAW_ONBOARD = "1"

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir
$XhausHome  = if ($env:XHAUS_HOME) { $env:XHAUS_HOME } else { Join-Path $RepoRoot "RUNXHAUS" }
$WebRepo    = "https://github.com/hareonna-hina/XHUAS_WEBPAGE.git"
$WebDir     = Join-Path $XhausHome "XHUAS_WEBPAGE"
$RunDir     = Join-Path $XhausHome ".run"
$GatewayPort = if ($env:OPENCLAW_GATEWAY_PORT) { $env:OPENCLAW_GATEWAY_PORT } else { "18789" }
$WebPort    = if ($env:PORT) { $env:PORT } else { "3000" }
$WebUrl     = "http://127.0.0.1:$WebPort"

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

function Invoke-PythonCmd {
    param([string[]]$Args)
    if ($script:UsePyLauncher) {
        & py -3 @Args
    } else {
        & $script:PythonExe @Args
    }
}

Write-Info "Checking dependencies..."

foreach ($cmd in @("git", "node", "npm")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fail "Missing $cmd. Install Node.js 18+ (with npm) and Git first."
    }
}

$UsePyLauncher = $false
$PythonExe = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $UsePyLauncher = $true
} else {
    Write-Fail "Python 3.10+ not found. Install from https://www.python.org and enable Add to PATH."
}

$nodeMajor = [int](node -p "process.versions.node.split('.')[0]")
if ($nodeMajor -lt 18) { Write-Fail "Node.js 18+ required. Current: $(node -v)" }

Write-Ok "Node $(node -v) and Python are available"

Write-Info "Creating RUNXHAUS at: $XhausHome"
New-Item -ItemType Directory -Force -Path $XhausHome, $RunDir | Out-Null

if (Test-Path (Join-Path $WebDir ".git")) {
    Write-Info "Repository exists, pulling latest..."
    Push-Location $WebDir
    try { git pull --ff-only } catch { Write-Warn "git pull failed, using local copy" }
    Pop-Location
} else {
    Write-Info "Cloning XHUAS_WEBPAGE..."
    git clone $WebRepo $WebDir
}
Write-Ok "Web path: $WebDir"

Write-Info "Running npm install..."
Push-Location (Join-Path $WebDir "backend")
npm install
Pop-Location
Write-Ok "npm dependencies installed"

Write-Info "Installing Python dependencies..."
Invoke-PythonCmd @("-m", "pip", "install", "-q", "-r", (Join-Path $WebDir "XHAUS\requirements.txt"))
$satReq = Join-Path $WebDir "Satellite\meta_skill\requirements.txt"
if (Test-Path $satReq) {
    Invoke-PythonCmd @("-m", "pip", "install", "-q", "-r", $satReq)
}
if ($UsePyLauncher) {
    $PythonPath = (& py -3 -c "import sys; print(sys.executable)")
} else {
    $PythonPath = $PythonExe
}
Write-Ok "Python dependencies installed"

$EnvFile = Join-Path $WebDir "backend\.env"
if (-not (Test-Path $EnvFile)) {
    Write-Info "Creating backend\.env..."
    Copy-Item (Join-Path $WebDir "backend\.env.example") $EnvFile
}

$JwtSecret = node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
Set-EnvLine $EnvFile "JWT_SECRET" $JwtSecret
Set-EnvLine $EnvFile "PORT" $WebPort
Set-EnvLine $EnvFile "XHUAS_PROJECT_ROOT" ($WebDir -replace '\\', '/')
Set-EnvLine $EnvFile "XHAUS_PYTHON" ($PythonPath -replace '\\', '/')
Set-EnvLine $EnvFile "OPENCLAW_CHAT_COMPLETIONS_URL" "http://127.0.0.1:${GatewayPort}/v1/chat/completions"
Write-Ok ".env configured (JWT_SECRET generated)"

Write-Info "Configuring OpenClaw..."

if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    Write-Info "Installing OpenClaw CLI (npm install -g openclaw@latest)..."
    npm install -g openclaw@latest
}
Write-Ok "OpenClaw CLI ready"

$OpenclawConfig = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"
$skipOnboard = ($env:SKIP_OPENCLAW_ONBOARD -eq "1")

if ((-not (Test-Path $OpenclawConfig)) -and (-not $skipOnboard)) {
    Write-Warn "First-time OpenClaw setup (~2 min): pick a model provider and API key."
    Write-Host "  - Keep gateway port $GatewayPort if prompted"
    Write-Host ""
    Read-Host "Press Enter to start openclaw onboard, or Ctrl+C to cancel"
    openclaw onboard --install-daemon
} elseif ((-not (Test-Path $OpenclawConfig)) -and $skipOnboard) {
    Write-Warn "Skipped onboard. Ensure %USERPROFILE%\.openclaw is configured."
} else {
    Write-Ok "OpenClaw config already exists"
}

if (-not (Test-PortListening $GatewayPort)) {
    Write-Info "Starting OpenClaw Gateway on port $GatewayPort..."
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
        $gwProc = Start-Process -FilePath "openclaw" `
            -ArgumentList @("gateway", "--port", $GatewayPort) `
            -RedirectStandardOutput $gwLog `
            -RedirectStandardError $gwLog `
            -WindowStyle Hidden `
            -PassThru
        $gwProc.Id | Out-File (Join-Path $RunDir "openclaw-gateway.pid") -Encoding ascii
    }

    if (Wait-Port $GatewayPort 25) {
        Write-Ok "OpenClaw Gateway running at ws://127.0.0.1:$GatewayPort"
    } else {
        Write-Warn "Gateway not listening on $GatewayPort. Check: $(Join-Path $RunDir 'openclaw-gateway.log')"
    }
} else {
    Write-Ok "OpenClaw Gateway already on port $GatewayPort"
}

if (Test-PortListening $WebPort) {
    Write-Warn "Port $WebPort in use, stopping old process..."
    Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

if (Test-PortListening $WebPort) {
    Write-Warn "Port $WebPort still in use. Stop it manually and re-run this script."
} else {
    Write-Info "Starting web backend on port $WebPort..."
    $webLog = Join-Path $RunDir "web-backend.log"
    $webProc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @("/c", "npm start") `
        -WorkingDirectory (Join-Path $WebDir "backend") `
        -RedirectStandardOutput $webLog `
        -RedirectStandardError $webLog `
        -WindowStyle Hidden `
        -PassThru
    $webProc.Id | Out-File (Join-Path $RunDir "web-backend.pid") -Encoding ascii

    if (-not (Wait-Port $WebPort 30)) {
        Write-Fail "Web backend failed to start. Check: $webLog"
    }
    Write-Ok "Web backend started"
}

Write-Info "Opening browser..."
Start-Sleep -Seconds 1
Start-Process $WebUrl

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Ok "XHAUS setup complete"
Write-Host ""
Write-Host "  Web UI:       $WebUrl"
Write-Host "  OpenClaw:     ws://127.0.0.1:$GatewayPort"
Write-Host "  Install dir:  $XhausHome"
Write-Host "  Logs:         $RunDir"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Click Start on the web page"
Write-Host "    2. WebSocket: ws://127.0.0.1:$GatewayPort"
Write-Host "    3. Pick a personality preset (Franziska, Emma, ...)"
Write-Host "============================================================" -ForegroundColor Green
