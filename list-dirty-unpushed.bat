@echo off
rem list-dirty-unpushed.bat
rem Double-click: sweeps %%USERPROFILE%%\Documents\GitHub, window stays open.
rem From a terminal:  list-dirty-unpushed.bat [--dir PATH] [--all] [--json]
python "%~dp0list-dirty-unpushed.py" %*
pause
