@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "EXP_OBSERVER_PYTHON=python"
  goto python_ready
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "EXP_OBSERVER_PYTHON=py -3"
  goto python_ready
)
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "EXP_OBSERVER_PYTHON=python3"
  goto python_ready
)
echo ExpObserver requires Python 3.10+. Install Python and add it to PATH.
exit /b 1

:python_ready
if exist dist\index.html goto start_server
if exist node_modules goto build_frontend
call npm ci
if errorlevel 1 exit /b %errorlevel%

:build_frontend
call npm run build
if errorlevel 1 exit /b %errorlevel%

:start_server
%EXP_OBSERVER_PYTHON% -m backend.server --port 4317 %*
exit /b %errorlevel%