# CodeRAG Windows Startup Script
# Fixes: GBK encoding issues + port zombie processes + Vite proxy alignment
# Usage: .\start_all.ps1

param(
    [int]$StartPort = 8080,
    [int]$MaxPort = 8090,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptDir "backend"
$frontendDir = Join-Path $scriptDir "frontend"

# ── 1. UTF-8 Encoding ────────────────────────────────────────
Write-Host "[1/5] Setting UTF-8 encoding..." -ForegroundColor Cyan
chcp 65001 >$null 2>&1
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "       Console: chcp 65001 | PYTHONUTF8=1" -ForegroundColor Green

# ── 2. Kill zombie processes ──────────────────────────────────
Write-Host "[2/5] Cleaning up zombie processes..." -ForegroundColor Cyan
$zombiePorts = @(8080, 8081, 8082, 8083, 8084, 8085)
foreach ($port in $zombiePorts) {
    $connections = netstat -ano 2>$null | Select-String ":$port " | Select-String "LISTENING"
    foreach ($conn in $connections) {
        $parts = $conn -split '\s+'
        $pid = $parts[-1]
        if ($pid -and $pid -match '^\d+$') {
            try {
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($proc -and $proc.ProcessName -like "*python*") {
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                    Write-Host "       Killed python PID $pid on port $port" -ForegroundColor Yellow
                } elseif ($proc) {
                    Write-Host "       Non-python PID $pid ($($proc.ProcessName)) on port $port — skipped" -ForegroundColor DarkGray
                } else {
                    Write-Host "       Orphan PID $pid on port $port (no process) — attempting netsh cleanup" -ForegroundColor DarkGray
                    # Try Windows socket cleanup for truly orphaned sockets
                    netsh int ipv4 delete excludedportrange protocol=tcp number=$port 2>$null
                }
            } catch {}
        }
    }
}
Start-Sleep -Seconds 3
Write-Host "       Done." -ForegroundColor Green

# ── 3. Find available backend port ────────────────────────────
Write-Host "[3/5] Finding available backend port..." -ForegroundColor Cyan
$backendPort = 0
for ($port = $StartPort; $port -le $MaxPort; $port++) {
    $inUse = netstat -ano 2>$null | Select-String ":$port " | Select-String "LISTENING"
    if (-not $inUse) {
        $backendPort = $port
        break
    }
}
if ($backendPort -eq 0) {
    Write-Host "ERROR: No free port in range $StartPort-$MaxPort" -ForegroundColor Red
    exit 1
}
Write-Host "       Backend will run on port $backendPort" -ForegroundColor Green

# ── 4. Update Vite proxy config ───────────────────────────────
Write-Host "[4/5] Updating Vite proxy target to :$backendPort..." -ForegroundColor Cyan
$viteConfig = Join-Path $frontendDir "vite.config.ts"
if (Test-Path $viteConfig) {
    $content = Get-Content $viteConfig -Raw -Encoding UTF8
    # Match and replace the proxy target port
    $content = $content -replace "(target:\s*'http://localhost:)\d+'", "`$1${backendPort}'"
    Set-Content $viteConfig $content -Encoding UTF8 -NoNewline
    Write-Host "       vite.config.ts updated to :$backendPort" -ForegroundColor Green
}

# ── 5. Start services ─────────────────────────────────────────
Write-Host "[5/5] Starting services..." -ForegroundColor Cyan

# Backend
Write-Host "       Starting backend..." -ForegroundColor Yellow
$backendLog = Join-Path $env:TEMP "coderag_api.log"
Push-Location $backendDir
try {
    $backendProc = Start-Process python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$backendPort", "--reload" `
        -PassThru -NoNewWindow -RedirectStandardOutput $backendLog -RedirectStandardError $backendLog
    Write-Host "       Backend PID: $($backendProc.Id) | Port: $backendPort | Log: $backendLog" -ForegroundColor Green
} finally {
    Pop-Location
}

# Wait for backend
for ($i = 1; $i -le 20; $i++) {
    try {
        $health = Invoke-WebRequest -Uri "http://localhost:$backendPort/health" -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Host "       Backend ready (attempt $i)" -ForegroundColor Green
            break
        }
    } catch {
        Start-Sleep 1
    }
}

# Frontend
Write-Host "       Starting frontend..." -ForegroundColor Yellow
$frontendLog = Join-Path $env:TEMP "coderag_frontend.log"
Push-Location $frontendDir
try {
    $frontendProc = Start-Process npx `
        -ArgumentList "vite", "--host", "0.0.0.0", "--port", "$FrontendPort" `
        -PassThru -NoNewWindow -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendLog
    Write-Host "       Frontend PID: $($frontendProc.Id) | Port: $FrontendPort | Log: $frontendLog" -ForegroundColor Green
} finally {
    Pop-Location
}

Start-Sleep 3

# ── Done ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  CodeRAG Running" -ForegroundColor White
Write-Host "  Frontend:  http://localhost:$FrontendPort" -ForegroundColor Green
Write-Host "  Backend:   http://localhost:$backendPort" -ForegroundColor Green
Write-Host "  Swagger:   http://localhost:$backendPort/docs" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stop with:  Ctrl+C  (then close terminal windows)" -ForegroundColor DarkGray
Write-Host "Backend log: $backendLog" -ForegroundColor DarkGray
Write-Host "Frontend log: $frontendLog" -ForegroundColor DarkGray

# Keep the script running so the user can see the output
Write-Host "Press Ctrl+C to stop all services..." -ForegroundColor Yellow
try {
    while ($true) { Start-Sleep 1 }
} finally {
    Write-Host "Stopping services..." -ForegroundColor Yellow
    if ($backendProc) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
    if ($frontendProc) { Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "Stopped." -ForegroundColor Green
}
