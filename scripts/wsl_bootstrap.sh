#!/usr/bin/env bash
# Tool Voice — Linux-side setup, run as ROOT inside the WSL distro.
# Idempotent: safe to re-run; each stage is skipped once its marker exists.
# Mirrors the manual setup that is known to work (S1-era fish-speech + openaudio-s1-mini).
#
# Usage:  wsl_bootstrap.sh <MODEL_BASE_URL>
#   MODEL_BASE_URL e.g. https://github.com/<owner>/<repo>/releases/download/model-v1
#
# Prints "=== step N/6: ... ===" lines so the Windows launcher can drive a progress bar,
# and "TOOLVOICE_BOOTSTRAP_DONE" on full success.
set -e

MODEL_BASE_URL="${1:-${TV_MODEL_BASE_URL}}"
ROOT=/opt/toolvoice
REPO=$ROOT/fish-speech
VENV=$REPO/.venv
MODEL=$REPO/checkpoints/openaudio-s1-mini
COMMIT=d3df505
TORCH_INDEX=https://download.pytorch.org/whl/cu124
mkdir -p "$ROOT"

mark() { echo "$1" > "$ROOT/.stage_$2"; }
done_stage() { [ -f "$ROOT/.stage_$1" ]; }

echo "=== step 1/6: system packages ==="
if ! done_stage sys; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -y
  apt-get install -y python3.11 python3.11-venv python3.11-dev git build-essential ffmpeg portaudio19-dev curl
  mark ok sys
fi

echo "=== step 2/6: fetch fish-speech source ($COMMIT) ==="
if ! done_stage clone; then
  rm -rf "$REPO"
  git clone https://github.com/fishaudio/fish-speech.git "$REPO"
  git -C "$REPO" checkout "$COMMIT"
  mark ok clone
fi

echo "=== step 3/6: python venv ==="
if ! done_stage venv; then
  python3.11 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip wheel setuptools
  mark ok venv
fi

echo "=== step 4/6: install torch (CUDA) — large ==="
if ! done_stage torch; then
  "$VENV/bin/pip" install torch torchaudio --index-url "$TORCH_INDEX"
  mark ok torch
fi

echo "=== step 5/6: install fish-speech + deps ==="
if ! done_stage deps; then
  "$VENV/bin/pip" install -e "$REPO"
  "$VENV/bin/pip" install ormsgpack pyrootutils
  mark ok deps
fi

echo "=== step 6/6: download model ==="
if ! done_stage model; then
  if [ -z "$MODEL_BASE_URL" ]; then echo "ERROR: no MODEL_BASE_URL given"; exit 2; fi
  mkdir -p "$MODEL"
  for f in config.json special_tokens.json tokenizer.tiktoken codec.pth model.pth; do
    if [ ! -s "$MODEL/$f" ]; then
      echo "downloading $f ..."
      # Resumable (-C -) + aggressive retry so a dropped connection on the big
      # files recovers instead of failing the whole install.
      for attempt in 1 2 3 4 5 6 7 8; do
        if curl -fL -C - --retry 5 --retry-delay 3 --retry-all-errors \
                --connect-timeout 30 -o "$MODEL/$f.part" "$MODEL_BASE_URL/$f"; then
          break
        fi
        echo "  (retry $attempt: connection dropped, resuming...)"
        sleep 3
      done
      [ -s "$MODEL/$f.part" ] || { echo "ERROR: failed to download $f"; exit 56; }
      mv "$MODEL/$f.part" "$MODEL/$f"
    fi
  done
  mark ok model
fi

echo "TOOLVOICE_BOOTSTRAP_DONE"
