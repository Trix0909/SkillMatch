$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$skillmatchPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $skillmatchPython)) {
    throw 'Run the installation steps in README.md to create the project virtual environment.'
}
& $skillmatchPython manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $skillmatchPython manage.py runserver 127.0.0.1:8000
