@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto not_installed
if not exist "dictado.py" goto missing_app

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*dictado.py*' }; if ($p) { exit 10 }"
if errorlevel 10 goto already_open

set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
start "" /D "%~dp0" ".venv\Scripts\pythonw.exe" "dictado.py"
exit /b 0

:already_open
echo.
echo O Dictado ja esta aberto.
echo Procure a pilula no canto da tela ou feche a instancia atual.
echo.
ping -n 4 127.0.0.1 >nul
exit /b 0

:not_installed
echo.
echo O Dictado ainda nao foi instalado.
echo Execute primeiro o arquivo 1-INSTALAR-PRIMEIRO.bat.
echo.
pause
exit /b 1

:missing_app
echo.
echo dictado.py nao encontrado nesta pasta.
echo Extraia o projeto completo antes de abrir.
echo.
pause
exit /b 1
