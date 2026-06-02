@echo off
REM Launch the Tool Voice GUI (OpenAudio S1 local). Server starts automatically inside the app.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "Tool Voice" ".venv\Scripts\pythonw.exe" tts_gui.py
