@echo off
REM Run the OpenAudio S1-mini TTS API server (S1-era code at commit d3df505).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m tools.api_server ^
  --listen 0.0.0.0:8080 ^
  --llama-checkpoint-path checkpoints/openaudio-s1-mini ^
  --decoder-checkpoint-path checkpoints/openaudio-s1-mini/codec.pth ^
  --decoder-config-name modded_dac_vq ^
  --half
pause
