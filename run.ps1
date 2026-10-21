param([string]$AptosPath = 'aptos', [switch]$Deploy)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is required.' }
    & '.venv/Scripts/python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if ($Deploy) {
    & '.venv/Scripts/python.exe' scripts/deploy.py --aptos $AptosPath
    if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. Check your Aptos CLI path and internet connection.' }
}
& '.venv/Scripts/python.exe' scripts/check_deployment.py
if ($LASTEXITCODE -ne 0) {
    throw 'Setup could not be verified. No new deployment was made. Review the README; choose -Deploy only when ready.'
}
& '.venv/Scripts/python.exe' -m uvicorn blockword.app:app --host 127.0.0.1 --port 8000
