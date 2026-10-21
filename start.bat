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
%EXP_OBSERVER_PYTHON% start.py %*
exit /b %errorlevel%