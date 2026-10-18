@echo off
setlocal
rem Installs WoT Sandbox into the World of Tanks game folder.
rem Usage: install.bat ["path\to\World of Tanks\eu"]
set "GAME=%~1"
if "%GAME%"=="" set "GAME=C:\Program Files (x86)\Steam\steamapps\common\World of Tanks\eu"
if not exist "%GAME%\WorldOfTanks.exe" (
  echo Game folder not found: "%GAME%"
  set /p "GAME=Enter path to the World of Tanks folder that contains WorldOfTanks.exe and res_mods: "
)
if not exist "%GAME%\WorldOfTanks.exe" (
  echo WorldOfTanks.exe not found in "%GAME%"
  pause
  exit /b 1
)
xcopy /e /i /y "%~dp0release\eu\*" "%GAME%\" >nul
if errorlevel 1 (
  echo Copy failed. Try running install.bat as administrator.
  pause
  exit /b 1
)
echo Installed to "%GAME%"
echo Start the battle with "%GAME%\sandbox_bots.bat"
pause
