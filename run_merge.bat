@echo off
REM ===================================================================
REM  run_merge.bat  -  double-click wrapper for merge_openlca_fix.py
REM
REM  Put THREE things in this same folder:
REM     run_merge.bat            (this file)
REM     merge_openlca_fix.py     (the script)
REM     EXPORT.zip               (your CURRENT openLCA export)
REM     FIX.zip                  (the fix package from Claude)
REM
REM  Then double-click this file. It asks for the two zip names,
REM  prints the CHANGE PREVIEW + MASS BALANCE, and writes MERGED.zip.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
set /p EXPORT="Name of your openLCA export zip (e.g. EXPORT.zip): "
set /p FIX="Name of the fix package zip (e.g. FIX.zip): "

echo.
echo Running merge...
echo.

python merge_openlca_fix.py "%EXPORT%" "%FIX%" "MERGED.zip"
if errorlevel 1 (
  echo.
  echo Something went wrong. If it says 'python is not recognized',
  echo install Python from python.org and tick "Add to PATH".
)

echo.
echo Done. Review the CHANGE PREVIEW above before importing MERGED.zip.
echo.
pause
endlocal
