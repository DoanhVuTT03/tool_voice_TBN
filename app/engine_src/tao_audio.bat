@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ============================================================
echo   TAO GIONG NOI (OpenAudio S1)  -  server phai dang chay
echo   (Neu chua bat server: mo run_server_s1.bat truoc)
echo ============================================================
echo.
set /p TEXT=Nhap van ban can doc:
set /p OUT=Ten file ket qua (Enter = salida.wav):
if "%OUT%"=="" set OUT=salida.wav
echo.
.venv\Scripts\python.exe tts_request.py "%TEXT%" "%OUT%"
echo.
if exist "%OUT%" (
  echo Mo file: %OUT%
  start "" "%OUT%"
)
pause
