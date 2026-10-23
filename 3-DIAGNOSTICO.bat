@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto not_installed
if not exist "dictado.py" goto missing_app

set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo Abrindo o Dictado com console de diagnostico...
echo Feche esta janela somente quando o aplicativo terminar.
echo.
".venv\Scripts\python.exe" "dictado.py"
echo.
echo O aplicativo terminou. Copie as mensagens acima se precisar de ajuda.
pause
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
