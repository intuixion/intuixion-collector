# Start Qdrant vector database with persistent local storage.
# Run this once before using ingest.py, query.py, or agent.py.
# Qdrant listens on http://localhost:6333

$env:QDRANT__STORAGE__STORAGE_PATH = "$PSScriptRoot\qdrant\storage"
$exe = "$PSScriptRoot\qdrant\qdrant.exe"

if (-not (Test-Path $exe)) {
    Write-Error "qdrant.exe not found at $exe. Run setup first."
    exit 1
}

$existing = Get-Process -Name "qdrant" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Qdrant already running (PID $($existing.Id)) on http://localhost:6333"
    exit 0
}

Write-Host "Starting Qdrant v1.18.0..."
Write-Host "Storage : $env:QDRANT__STORAGE__STORAGE_PATH"
Write-Host "API     : http://localhost:6333"

New-Item -ItemType Directory -Force -Path $env:QDRANT__STORAGE__STORAGE_PATH | Out-Null
Start-Process -FilePath $exe -WorkingDirectory "$PSScriptRoot\qdrant" -WindowStyle Hidden

Start-Sleep -Seconds 4
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:6333/" -UseBasicParsing -TimeoutSec 5
    $info = $resp.Content | ConvertFrom-Json
    Write-Host "Qdrant $($info.version) is UP and ready."
} catch {
    Write-Warning "Qdrant may still be starting. Check http://localhost:6333 in a moment."
}
