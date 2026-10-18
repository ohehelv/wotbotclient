@echo off
rem WoT Sandbox - offline battle with bots
rem map=  e.g. 05_prohorovka 01_karelia 02_malinovka 10_hills 04_himmelsdorf
rem tank= nation:Name, e.g. ussr:R04_T-34  germany:G03_PzV_Panther  usa:A05_M4_Sherman
rem bots= enemies, allies= allied bots, difficulty= bot accuracy 0.5..2
rem dmg= your damage multiplier, pen= your penetration chance 0..1
rem repairs= repair kits per battle, repairhp= share of HP restored by one kit, tracks=0 disables experimental track animation
cd /d "%~dp0"
> "%~dp0sandbox_launch.txt" echo map=05_prohorovka tank=germany:G04_PzVI_Tiger_I bots=6 allies=0 difficulty=1.0 dmg=2.0 pen=0.95 repairs=3 repairhp=0.4 tracks=1
copy /y "%~dp0sandbox_launch.txt" "%~dp0win64\sandbox_launch.txt" >nul
start "" "%~dp0WorldOfTanks.exe"
