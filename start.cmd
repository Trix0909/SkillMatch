@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
call :find_python
if errorlevel 1 goto missing_python
"%skillmatchPython%" %skillmatchPythonArg% tools\launch.py %*
set "skillmatchExit=%errorlevel%"
goto finished

:missing_python
echo Python 3.12 could not be found.
echo Install Python 3.12 with the Python launcher, then run start.cmd again.
echo Or set SKILLMATCH_PYTHON to the full path of your Python 3.12 executable.
set "skillmatchExit=1"

:finished
popd
if not "%skillmatchExit%"=="0" (
    echo.
    echo SkillMatch could not start. Read the error above.
    if /I not "%SKILLMATCH_NO_PAUSE%"=="1" pause
)
exit /b %skillmatchExit%

:find_python
if defined SKILLMATCH_PYTHON (
    call :try_python "%SKILLMATCH_PYTHON%"
    exit /b
)
call :try_python "%~dp0.venv\Scripts\python.exe"
if not errorlevel 1 exit /b 0
call :try_python py.exe -3.12
if not errorlevel 1 exit /b 0
call :try_python python.exe
if not errorlevel 1 exit /b 0
rem Reuse the Python bundled on the original development machine when available.
call :try_python "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
exit /b

:try_python
"%~1" %~2 -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if errorlevel 1 exit /b 1
set "skillmatchPython=%~1"
set "skillmatchPythonArg=%~2"
exit /b 0
