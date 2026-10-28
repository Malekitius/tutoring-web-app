@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.14 3.13 3.12 3.11) do (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 (
      py -%%V install.py
      goto done
    )
  )
)
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python and run this file again.
  goto done
)
python install.py
:done
echo.
pause
