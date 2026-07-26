@echo off
REM ===================================================================
REM  run_validate.bat  -  double-click wrapper for validate_openlca.py
REM
REM  Put THREE things in this same folder:
REM     run_validate.bat         (this file)
REM     validate_openlca.py      (the script)
REM     EXPORT.zip               (an openLCA JSON-LD export to check)
REM
REM  Then double-click this file. It asks for the export name, runs the
REM  full check (errors, double-counting, mass balance, calc-readiness,
REM  ISO snapshot) and saves the result to VALIDATION-REPORT.txt.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
set /p EXPORT="Name of the openLCA export zip to validate (e.g. EXPORT.zip): "

echo.
echo Validating... (also saving to VALIDATION-REPORT.txt)
echo.

python validate_openlca.py "%EXPORT%" > VALIDATION-REPORT.txt 2>&1
type VALIDATION-REPORT.txt

if errorlevel 1 (
  echo.
  echo [Errors were found above - see the ERRORS section. If it says
  echo  'python is not recognized', install Python from python.org and
  echo  tick "Add to PATH".]
)

echo.
echo Saved full report to VALIDATION-REPORT.txt in this folder.
echo.
pause
endlocal
