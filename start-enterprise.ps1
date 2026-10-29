param([int]$Port = 8093)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run the installation steps in README.enterprise.md first.'
}
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    throw 'Build the frontend first: cd frontend; npm.cmd ci; npm.cmd run build'
}
docker compose -f compose.enterprise.yaml up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not start.' }
& .venv\Scripts\python.exe -X utf8 -m uvicorn enterprise.api:app --host 127.0.0.1 --port $Port
