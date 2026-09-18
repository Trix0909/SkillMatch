param([string]$Python = 'python', [switch]$Demo)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python tools/dev.py setup
if ($LASTEXITCODE -ne 0) { throw 'Development setup failed. See the error above.' }
if ($Demo) {
    & .\.venv\Scripts\python.exe tools/dev.py demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo setup failed; existing data has not been reset.' }
}
