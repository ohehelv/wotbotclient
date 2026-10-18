@echo off
rem Built-in developer offline mode: map + free camera (WASD, mouse, wheel = speed)
cd /d "%~dp0"
> "%~dp0sandbox_launch.txt" echo mode=freecam map=05_prohorovka
copy /y "%~dp0sandbox_launch.txt" "%~dp0win64\sandbox_launch.txt" >nul
start "" "%~dp0WorldOfTanks.exe"
