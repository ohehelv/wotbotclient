@echo off
rem EXPERIMENTAL: the game's own battle client with an emulated server (real battle UI, minimap, markers)
rem Connection to Wargaming servers is blocked while this mode is active.
cd /d "%~dp0"
> "%~dp0sandbox_launch.txt" echo mode=native map=05_prohorovka tank=germany:G04_PzVI_Tiger_I bots=6 allies=0 dmg=2.0
copy /y "%~dp0sandbox_launch.txt" "%~dp0win64\sandbox_launch.txt" >nul
start "" "%~dp0WorldOfTanks.exe"
