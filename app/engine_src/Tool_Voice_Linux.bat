@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================================
echo  TOOL VOICE - che do LINUX (WSL2 + torch.compile, nhanh hon)
echo ============================================================
echo.

REM 1) Kiem tra server da chay san chua (vi du chay tay tu truoc)
powershell -NoProfile -Command "try{Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/health' -TimeoutSec 3 -UseBasicParsing|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
  echo Server da chay san tren cong 8080 -^> dung lai luon.
  goto launch_gui
)

REM 2) Bat server WSL trong mot cua so rieng
echo Dang khoi dong server Fish-Speech tren WSL/Ubuntu (--compile)...
echo (Cua so server se hien ra rieng. Lan dau warmup compile ~2-3 phut, dung dong no.)
start "Fish-Speech WSL Server" wsl -d Ubuntu-22.04 -- bash /mnt/d/Tool_voice/wsl_start_server.sh

REM 3) Cho server san sang (poll cong 8080)
echo Dang cho server san sang...
set /a tries=0
:waitloop
powershell -NoProfile -Command "try{Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/health' -TimeoutSec 3 -UseBasicParsing|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% geq 120 (
  echo [LOI] Server van chua san sang sau ~6 phut. Kiem tra cua so "Fish-Speech WSL Server".
  pause
  exit /b 1
)
timeout /t 3 /nobreak >nul
goto waitloop

:ready
echo Server SAN SANG.

:launch_gui
echo Dang mo Tool Voice GUI...
start "Tool Voice" ".venv\Scripts\pythonw.exe" tts_gui.py
echo.
echo Xong. Co the dong cua so nay (cua so server WSL phai giu nguyen khi dung tool).
timeout /t 4 /nobreak >nul
