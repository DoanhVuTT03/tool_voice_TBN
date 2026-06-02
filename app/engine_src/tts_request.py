"""
Simple TTS client for the OpenAudio S1 API server (no pyaudio needed).

Usage:
    .venv\\Scripts\\python.exe tts_request.py "Hola, esto es una prueba." salida.wav
    .venv\\Scripts\\python.exe tts_request.py "Van ban tieng Viet" out.wav
    # Clone a voice from a reference wav (5-15s) + its transcript:
    .venv\\Scripts\\python.exe tts_request.py "texto a leer" out.wav  giong_mau.wav  "transcript of giong_mau.wav"

If no arguments are given, it speaks a default Spanish sentence to salida.wav.
The server (run_server_s1.bat) must be running first.
"""
import sys
import time
import wave
import contextlib

import pyrootutils
pyrootutils.setup_root(".", indicator=".project-root", pythonpath=True)

import requests
import ormsgpack
from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio

# ---- read arguments ----
text = sys.argv[1] if len(sys.argv) > 1 else "Hola, esto es una prueba de voz en espanol con OpenAudio S1 Mini."
out = sys.argv[2] if len(sys.argv) > 2 else "salida.wav"
ref_audio_path = sys.argv[3] if len(sys.argv) > 3 else None
ref_text = sys.argv[4] if len(sys.argv) > 4 else ""

references = []
if ref_audio_path:
    with open(ref_audio_path, "rb") as f:
        references = [ServeReferenceAudio(audio=f.read(), text=ref_text)]
    print(f"Cloning voice from: {ref_audio_path}")

req = ServeTTSRequest(
    text=text,
    references=references,
    reference_id=None,
    format="wav",
    max_new_tokens=1024,
    chunk_length=200,
    top_p=0.7,
    repetition_penalty=1.2,
    temperature=0.7,
    streaming=False,
    use_memory_cache="off",
    seed=None,
)

print(f"Text: {text}")
print("Sending to server (http://127.0.0.1:8080) ...")
t0 = time.time()
try:
    resp = requests.post(
        "http://127.0.0.1:8080/v1/tts",
        params={"format": "msgpack"},
        data=ormsgpack.packb(req, option=ormsgpack.OPT_SERIALIZE_PYDANTIC),
        headers={"content-type": "application/msgpack"},
        timeout=300,
    )
except requests.exceptions.ConnectionError:
    print("\n[LOI] Khong ket noi duoc server. Hay bat run_server_s1.bat truoc va de cua so do chay.")
    sys.exit(1)

dt = time.time() - t0
if resp.status_code == 200:
    with open(out, "wb") as f:
        f.write(resp.content)
    with contextlib.closing(wave.open(out, "r")) as w:
        dur = w.getnframes() / float(w.getframerate())
    print(f"OK -> {out}  ({dur:.2f} giay, {len(resp.content):,} bytes, {dt:.1f}s)")
else:
    print(f"[LOI] status {resp.status_code}: {resp.content[:400]}")
    sys.exit(1)
