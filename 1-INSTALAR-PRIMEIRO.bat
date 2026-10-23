@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Dictado - Instalador

echo ============================================================
echo  DICTADO - INSTALAR (execute este arquivo uma vez)
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*dictado.py*' }; if ($p) { exit 10 }"
if errorlevel 10 (
    echo O Dictado esta aberto. Feche a pilula antes de instalar ou atualizar.
    echo.
    pause
    exit /b 1
)

set "PYCMD="
py -3.11 -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3.11"
if not defined PYCMD (
    py -3 -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 and (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
    python -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 and (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)
if defined PYCMD goto run

echo Python 3.11 ou 3.12 nao encontrado.
where winget >nul 2>nul
if errorlevel 1 goto manual

echo.
choice /C SN /M "Deseja instalar o Python 3.11 automaticamente agora"
if errorlevel 2 goto manual
echo.
winget install -e --id Python.Python.3.11 --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto manual

set "PYCMD="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYCMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe""
if not defined PYCMD if exist "%PROGRAMFILES%\Python311\python.exe" set "PYCMD="%PROGRAMFILES%\Python311\python.exe""
if not defined PYCMD goto manual
goto run

:manual
echo.
echo Nao consegui instalar o Python automaticamente.
echo Abra o site abaixo, instale o Python 3.11 e marque a opcao
echo "Add python.exe to PATH". Depois execute este instalador de novo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:run
echo Usando: %PYCMD%
%PYCMD% "instalar.py" %*
if errorlevel 1 (
    echo.
    echo A instalacao falhou. Leia as mensagens acima.
    pause
    exit /b 1
)
echo.
pause
exit /b 0
