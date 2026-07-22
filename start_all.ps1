# Start all DocuRAG services: Qdrant + FastAPI + Next.js
# Run this once each time you open a new terminal session.

$root = "C:\Users\DELL\intuixion_collector"
$webapp = "C:\Users\DELL\intuixion-app"

# ── 1. Qdrant ────────────────────────────────────────────────────────────
$qdrantRunning = $null -ne (Get-Process -Name "qdrant" -ErrorAction SilentlyContinue)
if (-not $qdrantRunning) {
    $env:QDRANT__STORAGE__STORAGE_PATH = "$root\qdrant\storage"
    Start-Process -FilePath "$root\qdrant\qdrant.exe" -WorkingDirectory "$root\qdrant" -WindowStyle Hidden
    Start-Sleep -Seconds 4
    Write-Host "Qdrant     started  ->  http://localhost:6333"
} else {
    Write-Host "Qdrant     already running"
}

# ── 2. FastAPI ──────────────────────────────────────────────────────────
$apiRunning = $null -ne (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if (-not $apiRunning) {
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "cd /d $root && .\venv\Scripts\python.exe -m uvicorn api:app --port 8000 > api.log 2>&1" `
        -WindowStyle Hidden
    Start-Sleep -Seconds 4
    Write-Host "FastAPI    started  ->  http://localhost:8000"
} else {
    Write-Host "FastAPI    already running"
}

# ── 3. Next.js ──────────────────────────────────────────────────────────
$webRunning = $null -ne (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)
if (-not $webRunning) {
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "cd /d $webapp && npm run dev > dev.log 2>&1" `
        -WindowStyle Hidden
    Start-Sleep -Seconds 10
    Write-Host "Next.js    started  ->  http://localhost:3000"
} else {
    Write-Host "Next.js    already running"
}

Write-Host ""
Write-Host "All services ready. Open http://localhost:3000"
