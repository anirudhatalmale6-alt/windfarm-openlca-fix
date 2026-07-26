@echo off
REM ===================================================================
REM  run_ipc.bat  -  connect to a LIVE openLCA database (READ-ONLY)
REM
REM  Before running:
REM    1) Open openLCA with your database.
REM    2) Tools > Developer tools > IPC Server -> Start. Note the port.
REM
REM  Put ipc_connect.py and this file in the same folder, then
REM  double-click. It installs the client library the first time,
REM  asks for the port, and runs a safe read-only check.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo Making sure the openLCA client library is installed (first run only)...
python -m pip install --quiet olca-ipc olca-schema
if errorlevel 1 (
  echo.
  echo Could not install olca-ipc. If 'python' is not recognized, install
  echo Python from python.org and tick "Add to PATH", then run this again.
  pause
  exit /b 1
)

echo.
set /p PORT="openLCA IPC Server port (press Enter for 8080): "
if "%PORT%"=="" set PORT=8080

echo.
echo Connecting read-only to openLCA on port %PORT% ...
echo.
python ipc_connect.py %PORT%

echo.
echo Done. See live_validation.txt and live_mass_balance.csv in this folder.
echo (Nothing in your database was modified - this run only reads.)
echo.
pause
endlocal
