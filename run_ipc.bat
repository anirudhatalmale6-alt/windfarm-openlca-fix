@echo off
REM ===================================================================
REM  run_ipc.bat  -  connect to a LIVE openLCA database (READ-ONLY)
REM
REM  Before running:
REM    1) Open openLCA with your database (active / bold).
REM    2) Tools > Developer tools > IPC Server -> click the green RUN
REM       button (leave "gRPC" unchecked). Note the port.
REM
REM  Put ipc_connect.py and this file in the same folder, then
REM  double-click. Installs the client library the first time, asks
REM  for the port, and runs a safe read-only check.
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
echo Optional: narrow the check to part of the IEA-NRL 15MW model.
echo   - by VARIATION: type  monopile  or  floating
echo   - by LIFE-CYCLE PHASE: type  EOL  (end of life), MFG, Transport, etc.
echo Leave blank to check the whole model (ecoinvent background is excluded).
set /p FILTER="Filter word (or press Enter for all): "

echo.
echo Connecting read-only to openLCA on port %PORT% ...
echo.
python ipc_connect.py %PORT% %FILTER%

echo.
echo Done. See live_validation.txt and live_mass_balance.csv in this folder.
echo (Nothing in your database was modified - this run only reads.)
echo.
pause
endlocal
