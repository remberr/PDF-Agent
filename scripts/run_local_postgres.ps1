param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$settingsPath = '.evaluation-local/vector-local.env'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw 'Local database credentials file is missing. Follow docs/LOCAL_STORAGE.md.'
}
$localPassword = ((Get-Content -LiteralPath $settingsPath | Where-Object { $_.StartsWith('POSTGRES_PASSWORD=') }) -replace '^POSTGRES_PASSWORD=', '')
if (-not $localPassword) { throw 'Local PostgreSQL password is missing.' }
$env:DATABASE_URL = 'postgresql+psycopg://pdf_agent:' + [uri]::EscapeDataString($localPassword) + '@127.0.0.1:55433/pdf_agent_local'
$env:SESSION_RETENTION_ENABLED = 'false'
$env:HF_HUB_OFFLINE = '1'
& .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
