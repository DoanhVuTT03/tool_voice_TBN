#!/usr/bin/env bash
# Start the Tool Voice TTS server inside WSL with torch.compile (fast path).
# Run as root. Arg 1 = port (default 8080).
set -e
PORT="${1:-8080}"
REPO=/opt/toolvoice/fish-speech
cd "$REPO"
source .venv/bin/activate
export CC=gcc CXX=g++
MODEL=checkpoints/openaudio-s1-mini
# Log to a file inside WSL, NOT to stdout. The launcher starts this as a child
# whose stdout pipe closes when the launcher exits; if the server kept writing
# to that pipe it would die with "[Errno 32] Broken pipe" on every request.
LOG=/opt/toolvoice/server.log
exec python -u -m tools.api_server \
  --listen "0.0.0.0:${PORT}" \
  --llama-checkpoint-path "$MODEL" \
  --decoder-checkpoint-path "$MODEL/codec.pth" \
  --decoder-config-name modded_dac_vq \
  --half --compile >>"$LOG" 2>&1
