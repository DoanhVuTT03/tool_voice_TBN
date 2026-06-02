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
exec python -m tools.api_server \
  --listen "0.0.0.0:${PORT}" \
  --llama-checkpoint-path "$MODEL" \
  --decoder-checkpoint-path "$MODEL/codec.pth" \
  --decoder-config-name modded_dac_vq \
  --half --compile
