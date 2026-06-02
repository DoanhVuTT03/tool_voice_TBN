# -*- coding: utf-8 -*-
"""
Tool Voice - OpenAudio S1 (Local)
A simplified TTS GUI that drives the local OpenAudio S1-mini API server.

Features (per spec):
- Only the current model (OpenAudio S1-mini local). No Edge-TTS / Applio / phonetic dict / Join MP3 / SRT export / advanced settings.
- Import File (*.txt, *.srt): each line / each subtitle becomes one row.
- Import Folder + "Chay hang loat": run every .txt/.srt file in a folder one by one.
- Start = run the currently loaded file.
- Tam dung <-> Tiep tuc (pause/resume), Stop.
- Speed / Pitch / So luong AI (parallel workers).
- Optional voice cloning via a reference WAV/MP3 ("Chon Giong Mau").
- Auto-starts the API server in the background (no separate window needed).
"""
import io
import os
import sys
import re
import time
import socket
import threading
import subprocess
from pathlib import Path
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import requests
import ormsgpack

# Light import (pydantic models only; does NOT load the torch model)
import pyrootutils
HERE = Path(__file__).resolve().parent

# --- Portable-app path resolution (set by launcher_main.py via env) -----------
# TV_ENGINE_SRC = folder containing the fish-speech source (fish_speech/, tools/)
# TV_MODEL_DIR  = folder containing the openaudio-s1-mini checkpoint files
# Fall back to the local dev checkout when env is not set (running from source).
ENGINE_SRC = Path(os.environ.get("TV_ENGINE_SRC", str(HERE))).resolve()
MODEL_DIR = Path(os.environ.get(
    "TV_MODEL_DIR",
    str(ENGINE_SRC / "checkpoints" / "openaudio-s1-mini"))).resolve()

# setup_root is best-effort; fish_speech is importable from site-packages anyway.
try:
    pyrootutils.setup_root(str(ENGINE_SRC), indicator=".project-root", pythonpath=True)
except Exception:
    pass
from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio

SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("TV_PORT", "8080"))
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/v1/tts"

LANGUAGES = [
    "es (Tay Ban Nha)", "vi (Tieng Viet)", "en (English)", "zh (Trung)",
    "ja (Nhat)", "ko (Han)", "fr (Phap)", "de (Duc)", "it (Y)", "ru (Nga)",
]


# --------------------------------------------------------------------------- #
# File parsing (module-level so it is testable without the GUI)
# --------------------------------------------------------------------------- #
def parse_srt(text):
    """Return list of (timing_str, content) from SRT content."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks = re.split(r"\n\s*\n", text.strip())
    rows = []
    ts_re = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if not lines:
            continue
        timing = ""
        content_lines = []
        for l in lines:
            m = ts_re.search(l)
            if m:
                timing = f"{m.group(1)} --> {m.group(2)}"
                continue
            # skip a pure index line at the top
            if l.strip().isdigit() and not content_lines and timing == "":
                continue
            content_lines.append(l.strip())
        content = " ".join(content_lines).strip()
        if content:
            rows.append((timing, content))
    return rows


def parse_txt(text):
    """Return list of (timing_str, content): one non-empty line per row."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    rows = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            rows.append(("", line))
    return rows


_END_PUNCT = ".!?…。！？”\"')]}"


def normalize_text(text):
    """Avoid the model cutting the final word: ensure the line ends with sentence
    punctuation. (Empirically, a missing terminal period makes generation stop early.)"""
    t = (text or "").strip()
    if not t:
        return t
    if t[-1] not in _END_PUNCT:
        t += "."
    return t


def parse_file(path):
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".srt":
        return parse_srt(raw)
    return parse_txt(raw)


def apply_fx(wav_bytes, speed, pitch):
    """Apply speed (time-stretch, keeps pitch) and pitch shift. Returns wav bytes."""
    if abs(speed - 1.0) < 1e-3 and int(pitch) == 0:
        return wav_bytes
    import soundfile as sf
    import numpy as np
    import librosa
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    if abs(speed - 1.0) >= 1e-3:
        data = librosa.effects.time_stretch(data, rate=float(speed))
    if int(pitch) != 0:
        data = librosa.effects.pitch_shift(data, sr=sr, n_steps=int(pitch))
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


_SENT_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")


def split_sentences(text):
    """Split a line into sentences (keeping punctuation). Generating each sentence
    separately prevents the model from cutting the last word of a multi-sentence line."""
    t = (text or "").strip()
    if not t:
        return []
    parts = _SENT_SPLIT.split(t)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(normalize_text(p))
    return out or [normalize_text(t)]


def _tts_segment(session, text, references):
    """Generate one short segment; returns (mono float32 audio, samplerate)."""
    import soundfile as sf
    req = ServeTTSRequest(
        text=text, references=references, reference_id=None, format="wav",
        max_new_tokens=1024, chunk_length=200, top_p=0.7, repetition_penalty=1.2,
        temperature=0.7, streaming=False, use_memory_cache="on", seed=None)
    resp = session.post(
        SERVER_URL, params={"format": "msgpack"},
        data=ormsgpack.packb(req, option=ormsgpack.OPT_SERIALIZE_PYDANTIC),
        headers={"content-type": "application/msgpack"}, timeout=600)
    resp.raise_for_status()
    data, sr = sf.read(io.BytesIO(resp.content), dtype="float32")
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    return data, sr


def synthesize(session, content, references, speed, pitch):
    """One generation per line (natural pacing), then apply speed/pitch. Returns WAV bytes.
    The generated WAV is already complete; any 'cut ending' is a PC media-player artifact,
    not a real truncation, so no sentence-splitting / padding is needed."""
    import soundfile as sf
    audio, sr = _tts_segment(session, normalize_text(content), references)
    if abs(speed - 1.0) >= 1e-3 or int(pitch) != 0:
        import librosa
        if abs(speed - 1.0) >= 1e-3:
            audio = librosa.effects.time_stretch(audio, rate=float(speed))
        if int(pitch) != 0:
            audio = librosa.effects.pitch_shift(audio, sr=sr, n_steps=int(pitch))
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# GUI application
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root):
        self.root = root
        root.title("Tool Voice - OpenAudio S1 (Local)")
        root.geometry("1180x800")

        # state
        self.rows = []                       # list of dicts: {iid, idx, output, timing, content}
        self.input_path = None
        self.batch_files = []
        self.ref_audio_bytes = None
        self.ref_text = ""
        self.ref_name = ""

        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()               # set => running, clear => paused
        self.runner_thread = None
        self.running = False

        self.server_proc = None
        self.we_started_server = False
        self.server_ready = threading.Event()

        self.start_time = 0.0
        self.done_count = 0

        self._build_ui()
        # warm up server in the background so it is ready by first Start
        threading.Thread(target=self.ensure_server, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -------------------- UI construction -------------------- #
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        # ----- Voice Generation -----
        vg = ttk.LabelFrame(top, text="Voice Generation")
        vg.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.btn_ref = ttk.Button(vg, text="Chon Giong Mau\n(File WAV/MP3 de clone)",
                                  command=self.choose_reference, width=24)
        self.btn_ref.grid(row=0, column=0, rowspan=2, padx=8, pady=8, sticky="ns")

        ttk.Label(vg, text="Ngon Ngu:").grid(row=0, column=1, sticky="e", padx=4, pady=6)
        self.cmb_lang = ttk.Combobox(vg, values=LANGUAGES, state="readonly", width=22)
        self.cmb_lang_set("es (Tay Ban Nha)")
        self.cmb_lang.grid(row=0, column=2, sticky="w", padx=4, pady=6)
        self.lbl_ref = ttk.Label(vg, text="Chua chon file mau (WAV)", foreground="#888")
        self.lbl_ref.grid(row=0, column=3, sticky="w", padx=8)

        ttk.Label(vg, text="Mo Hinh AI:").grid(row=1, column=1, sticky="e", padx=4, pady=6)
        self.cmb_model = ttk.Combobox(vg, values=["OpenAudio S1-mini (Local)"],
                                      state="readonly", width=22)
        self.cmb_model.current(0)
        self.cmb_model.grid(row=1, column=2, sticky="w", padx=4, pady=6)
        ttk.Button(vg, text="Bo giong mau", command=self.clear_reference).grid(
            row=1, column=3, sticky="w", padx=8)

        # ----- Change voice settings -----
        cv = ttk.LabelFrame(top, text="Change voice settings")
        cv.pack(side="left", fill="y")

        ttk.Label(cv, text="Speed:").grid(row=0, column=0, sticky="e", padx=6, pady=8)
        self.var_speed = tk.DoubleVar(value=1.00)
        ttk.Spinbox(cv, from_=0.5, to=2.0, increment=0.05, textvariable=self.var_speed,
                    width=10, format="%.2f").grid(row=0, column=1, padx=6, pady=8)

        ttk.Label(cv, text="Pitch:").grid(row=1, column=0, sticky="e", padx=6, pady=8)
        self.var_pitch = tk.IntVar(value=0)
        ttk.Spinbox(cv, from_=-12, to=12, increment=1, textvariable=self.var_pitch,
                    width=10).grid(row=1, column=1, padx=6, pady=8)

        ttk.Label(cv, text="So luong AI:").grid(row=2, column=0, sticky="e", padx=6, pady=8)
        self.var_threads = tk.IntVar(value=1)
        ttk.Spinbox(cv, from_=1, to=8, increment=1, textvariable=self.var_threads,
                    width=10).grid(row=2, column=1, padx=6, pady=8)

        # Resume: skip lines whose output wav already exists (re-run after a crash
        # / power loss only generates what's missing). On by default.
        self.var_resume = tk.BooleanVar(value=True)
        ttk.Checkbutton(cv, text="Tiep tuc: bo qua cau da co voice (chong mat dien)",
                        variable=self.var_resume).grid(row=3, column=0, columnspan=3,
                                                        sticky="w", padx=6, pady=4)

        # ----- Batch Job Options -----
        bj = ttk.LabelFrame(self.root, text="Batch Job Options")
        bj.pack(fill="x", padx=8, pady=4)
        ttk.Label(bj, text="Thu muc:").pack(side="left", padx=6, pady=8)
        self.var_folder = tk.StringVar()
        ttk.Entry(bj, textvariable=self.var_folder).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bj, text="...", width=4, command=self.choose_folder).pack(side="left", padx=2)
        self.btn_batch = ttk.Button(bj, text="Chay hang loat", command=self.start_batch)
        self.btn_batch.pack(side="left", padx=6)

        # ----- status line -----
        self.lbl_status = ttk.Label(
            self.root, text="Subtitles (Done: 0  Threads: 1  Total: 0)   Elapsed: 0s")
        self.lbl_status.pack(fill="x", padx=10, pady=(2, 0))

        # ----- control buttons -----
        ctl = ttk.Frame(self.root)
        ctl.pack(fill="x", padx=8, pady=4)
        self.btn_start = ttk.Button(ctl, text="Start", command=self.start_single)
        self.btn_start.pack(side="left", padx=3)
        self.btn_pause = ttk.Button(ctl, text="Tam dung", command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(ctl, text="Stop", command=self.stop_run, state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        ttk.Button(ctl, text="Import File (*.txt, *.srt)", command=self.import_file).pack(side="left", padx=10)
        ttk.Button(ctl, text="Import Folder", command=self.import_folder).pack(side="left", padx=3)

        # ----- table -----
        cols = ("id", "output", "timing", "content", "voice", "status")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", height=16)
        headers = {"id": ("Id", 40), "output": ("Output", 90), "timing": ("Timing", 150),
                   "content": ("Content", 520), "voice": ("Voice #", 70), "status": ("Status", 180)}
        for c in cols:
            t, w = headers[c]
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        # ----- log -----
        self.txt_log = tk.Text(self.root, height=6, wrap="word")
        self.txt_log.pack(fill="x", padx=8, pady=(0, 8))
        self.log("San sang. Model: OpenAudio S1-mini (local). Dang khoi dong dong co o nen...")

    def cmb_lang_set(self, value):
        try:
            self.cmb_lang.set(value)
        except Exception:
            pass

    # -------------------- helpers (thread-safe GUI) -------------------- #
    def log(self, msg):
        def _do():
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
        self.root.after(0, _do)

    def set_row(self, iid, voice=None, status=None):
        def _do():
            if voice is not None:
                self.tree.set(iid, "voice", voice)
            if status is not None:
                self.tree.set(iid, "status", status)
        self.root.after(0, _do)

    def refresh_status(self):
        total = len(self.rows)
        el = int(time.time() - self.start_time) if self.running else 0
        txt = (f"Subtitles (Done: {self.done_count}  Threads: {self.var_threads.get()}  "
               f"Total: {total})   Elapsed: {el}s")
        self.root.after(0, lambda: self.lbl_status.config(text=txt))

    # -------------------- reference voice -------------------- #
    def choose_reference(self):
        path = filedialog.askopenfilename(
            title="Chon file giong mau (WAV/MP3)",
            filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg"), ("All", "*.*")])
        if not path:
            return
        p = Path(path)
        self.ref_audio_bytes = p.read_bytes()
        self.ref_name = p.name
        # try sidecar transcript: same name .txt or .lab
        self.ref_text = ""
        for ext in (".txt", ".lab"):
            sc = p.with_suffix(ext)
            if sc.exists():
                self.ref_text = sc.read_text(encoding="utf-8", errors="replace").strip()
                break
        note = f"  (transcript: {len(self.ref_text)} ky tu)" if self.ref_text else "  (khong co transcript)"
        self.lbl_ref.config(text=p.name + note, foreground="#070")
        self.log(f"Da chon giong mau: {p.name}{note}")

    def clear_reference(self):
        self.ref_audio_bytes = None
        self.ref_text = ""
        self.ref_name = ""
        self.lbl_ref.config(text="Chua chon file mau (WAV)", foreground="#888")
        self.log("Da bo giong mau (dung giong mac dinh cua model).")

    # -------------------- file/folder import -------------------- #
    def _populate_table(self, rows):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        for i, (timing, content) in enumerate(rows, start=1):
            iid = self.tree.insert("", "end", values=(i, f"{i}.wav", timing, content, "", "Waiting..."))
            self.rows.append({"iid": iid, "idx": i, "output": f"{i}.wav",
                              "timing": timing, "content": content})
        self.done_count = 0
        self.refresh_status()

    def import_file(self):
        path = filedialog.askopenfilename(
            title="Import File", filetypes=[("Text/SRT", "*.txt *.srt"), ("All", "*.*")])
        if not path:
            return
        try:
            rows = parse_file(path)
        except Exception as e:
            messagebox.showerror("Loi", f"Khong doc duoc file:\n{e}")
            return
        self.input_path = path
        self._populate_table(rows)
        kind = "SRT" if path.lower().endswith(".srt") else "TXT"
        self.log(f"Da nap {kind}: {Path(path).name}  ->  {len(rows)} dong.")

    def import_folder(self):
        folder = filedialog.askdirectory(title="Import Folder (chua .txt/.srt)")
        if not folder:
            return
        self.var_folder.set(folder)
        self._scan_folder(folder)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Chon thu muc")
        if folder:
            self.var_folder.set(folder)
            self._scan_folder(folder)

    def _scan_folder(self, folder):
        files = sorted([str(p) for p in Path(folder).iterdir()
                        if p.suffix.lower() in (".txt", ".srt")])
        self.batch_files = files
        self.log(f"Thu muc: {folder}  ->  {len(files)} file (.txt/.srt).")
        # preview the first file in the table
        if files:
            try:
                self._populate_table(parse_file(files[0]))
                self.input_path = files[0]
            except Exception:
                pass

    # -------------------- server management -------------------- #
    def _port_open(self):
        try:
            with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=1.5):
                return True
        except OSError:
            return False

    def ensure_server(self):
        """Make sure the API server is up; reuse if already running, else spawn it."""
        if self.server_ready.is_set():
            return True
        if self._port_open():
            self.server_ready.set()
            self.log("Server da chay san tren cong 8080 -> dung lai.")
            return True
        # spawn
        self.log("Dang khoi dong server OpenAudio S1 (nap model ~30s, lan dau co the lau hon)...")
        cmd = [sys.executable, "-m", "tools.api_server",
               "--listen", f"0.0.0.0:{SERVER_PORT}",
               "--llama-checkpoint-path", str(MODEL_DIR),
               "--decoder-checkpoint-path", str(MODEL_DIR / "codec.pth"),
               "--decoder-config-name", "modded_dac_vq", "--half"]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        try:
            self.server_proc = subprocess.Popen(
                cmd, cwd=str(ENGINE_SRC), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=creationflags)
        except Exception as e:
            self.log(f"[LOI] Khong khoi dong duoc server: {e}")
            return False
        self.we_started_server = True
        threading.Thread(target=self._read_server_output, daemon=True).start()
        # wait until ready marker or port opens
        for _ in range(600):  # up to ~5 min
            if self.server_ready.is_set():
                return True
            if self.server_proc.poll() is not None:
                self.log("[LOI] Server thoat som. Xem log o tren.")
                return False
            time.sleep(0.5)
        self.log("[LOI] Server khong san sang sau 5 phut.")
        return False

    def _read_server_output(self):
        proc = self.server_proc
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if not line:
                continue
            # surface only meaningful lines to keep the log readable
            low = line.lower()
            if any(k in low for k in ("startup done", "uvicorn running", "error",
                                      "traceback", "warmed", "listening", "exception")):
                self.log("[server] " + line)
            if ("startup done" in low) or ("uvicorn running" in low):
                if not self.server_ready.is_set():
                    self.server_ready.set()
                    self.log("Server SAN SANG. Co the bam Start.")

    # -------------------- run control -------------------- #
    def _set_running_ui(self, running):
        self.running = running
        st_run = "disabled" if running else "normal"
        st_act = "normal" if running else "disabled"
        self.btn_start.config(state=st_run)
        self.btn_batch.config(state=st_run)
        self.btn_pause.config(state=st_act, text="Tam dung")
        self.btn_stop.config(state=st_act)

    def start_single(self):
        if self.running:
            return
        if not self.rows:
            messagebox.showinfo("Thong bao", "Chua co noi dung. Hay Import File truoc.")
            return
        self.runner_thread = threading.Thread(
            target=self._run_files, args=([self.input_path],), daemon=True)
        self._begin_run()

    def start_batch(self):
        if self.running:
            return
        if not self.batch_files:
            messagebox.showinfo("Thong bao", "Chua chon thu muc co file .txt/.srt.")
            return
        self.runner_thread = threading.Thread(
            target=self._run_files, args=(list(self.batch_files),), daemon=True)
        self._begin_run()

    def _begin_run(self):
        self.stop_event.clear()
        self.pause_event.set()
        self.done_count = 0
        self.start_time = time.time()
        self._set_running_ui(True)
        self._tick_elapsed()
        self.runner_thread.start()

    def _tick_elapsed(self):
        if self.running:
            self.refresh_status()
            self.root.after(1000, self._tick_elapsed)

    def toggle_pause(self):
        if not self.running:
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.btn_pause.config(text="Tiep tuc")
            self.log("== Tam dung ==")
        else:
            self.pause_event.set()
            self.btn_pause.config(text="Tam dung")
            self.log("== Tiep tuc ==")

    def stop_run(self):
        if not self.running:
            return
        self.stop_event.set()
        self.pause_event.set()  # release any paused workers so they can exit
        self.log("== Stop: dang dung lai... ==")

    def _run_files(self, files):
        try:
            if not self.ensure_server():
                self.log("[LOI] Khong chay duoc vi server chua san sang.")
                return
            for fpath in files:
                if self.stop_event.is_set():
                    break
                if fpath is None:
                    rows = self.rows
                else:
                    if len(files) > 1:
                        # batch: load this file's content into the table
                        try:
                            parsed = parse_file(fpath)
                        except Exception as e:
                            self.log(f"[LOI] Bo qua {Path(fpath).name}: {e}")
                            continue
                        self.input_path = fpath
                        self.root.after(0, lambda r=parsed: self._populate_table(r))
                        time.sleep(0.2)  # let UI populate
                    rows = self.rows
                self.log(f"--- Bat dau: {Path(fpath).name if fpath else 'file hien tai'} "
                         f"({len(rows)} dong) ---")
                self._generate(rows, fpath)
            self.log("=== HOAN TAT ===" if not self.stop_event.is_set() else "=== DA DUNG ===")
        finally:
            self.root.after(0, lambda: self._set_running_ui(False))
            self.refresh_status()

    def _generate(self, rows, fpath):
        # output dir per input file
        if fpath:
            base = Path(fpath)
            outdir = base.parent / (base.stem + "_tts")
        else:
            outdir = HERE / "output_tts"
        outdir.mkdir(parents=True, exist_ok=True)
        self.log(f"Output -> {outdir}")

        n_workers = max(1, int(self.var_threads.get()))
        id_q = Queue()
        for i in range(1, n_workers + 1):
            id_q.put(i)

        speed = float(self.var_speed.get())
        pitch = int(self.var_pitch.get())
        references = []
        if self.ref_audio_bytes:
            references = [ServeReferenceAudio(audio=self.ref_audio_bytes, text=self.ref_text)]

        session = requests.Session()

        def work(row):
            if self.stop_event.is_set():
                self.set_row(row["iid"], status="Stopped")
                return
            out_path = outdir / f"{row['idx']}.wav"
            # Resume: a non-empty output already exists -> skip (don't regenerate).
            if self.var_resume.get() and out_path.exists() and out_path.stat().st_size > 0:
                self.set_row(row["iid"], status="Da co (bo qua)")
                self.done_count += 1
                self.refresh_status()
                return
            self.pause_event.wait()
            if self.stop_event.is_set():
                self.set_row(row["iid"], status="Stopped")
                return
            vid = id_q.get()
            try:
                self.set_row(row["iid"], voice=vid, status="Generating...")
                t0 = time.time()
                audio = synthesize(session, row["content"], references, speed, pitch)
                # Atomic write: a crash mid-write leaves only a .part file, never a
                # half-written .wav that resume would mistake for "done".
                tmp = out_path.parent / (out_path.name + ".part")
                with open(tmp, "wb") as f:
                    f.write(audio)
                os.replace(tmp, out_path)
                dt = time.time() - t0
                self.set_row(row["iid"], status=f"Done ({dt:.1f}s)")
                self.done_count += 1
                self.refresh_status()
            except Exception as e:
                self.set_row(row["iid"], status="Loi")
                self.log(f"[LOI] dong {row['idx']}: {e}")
            finally:
                id_q.put(vid)

        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futures = [ex.submit(work, row) for row in rows]
            for f in futures:
                try:
                    f.result()
                except Exception:
                    pass

    def on_close(self):
        try:
            self.stop_event.set()
            self.pause_event.set()
        except Exception:
            pass
        if self.we_started_server and self.server_proc and self.server_proc.poll() is None:
            try:
                self.server_proc.terminate()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
