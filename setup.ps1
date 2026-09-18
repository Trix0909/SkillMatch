param([string]$Python, [switch]$Demo)
$ErrorActionPreference = 'Stop'
$previousPython = $env:SKILLMATCH_PYTHON
try {
    if ($Python) { $env:SKILLMATCH_PYTHON = $Python }
    & (Join-Path $PSScriptRoot 'start.cmd') --setup-only
    if ($LASTEXITCODE -ne 0) { throw 'Setup failed. See the error above.' }
    if ($Demo) {
        & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'tools\dev.py') demo
        if ($LASTEXITCODE -ne 0) { throw 'Demo setup failed; existing data has not been reset.' }
    }
} finally {
    $env:SKILLMATCH_PYTHON = $previousPython
}
