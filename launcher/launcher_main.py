"""
Tool Voice launcher (frozen to ToolVoice.exe). Stdlib-only.

WSL-first design:
  - GUI runs under the Windows portable runtime (built first run).
  - The TTS server prefers WSL with torch.compile (fast ~2.6s/clip).
  - If WSL can't be set up, the GUI automatically falls back to the
    Windows --half server (~13s/clip) — the app always works.

First-run WSL setup may require Admin (UAC) + one reboot; the launcher guides this.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import ttk, messagebox

import bootstrap
import updater
import wsl_engine

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def install_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE = install_dir()
APP_DIR = os.path.join(BASE, "app")
RUNTIME_DIR = os.path.join(BASE, "runtime")
SCRIPTS_DIR = os.path.join(BASE, "scripts")
REBOOT_MARK = os.path.join(BASE, ".wsl_reboot_pending")


def load_config():
    for p in (os.path.join(APP_DIR, "config.json"), os.path.join(BASE, "config.json")):
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                return json.load(f)
    return {}


CFG = load_config()
MODE = CFG.get("mode", "wsl")
DISTRO = CFG.get("wsl_distro", "Ubuntu-22.04")
PORT = int(CFG.get("server_port", 8080))
MODEL_DIR = os.path.join(BASE, CFG.get("model_dir", "models/openaudio-s1-mini").replace("/", os.sep))
ENGINE_SRC = os.path.join(APP_DIR, "engine_src")
MODEL_BASE_URL = CFG.get("model_base_url") or bootstrap.DEFAULT_BASE


# ----------------------------- progress UI ----------------------------- #
class Splash:
    """Thread-safe splash: workers push updates onto a queue; only the main
    thread (via pump) touches Tk."""
    def __init__(self, title="Tool Voice"):
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("470x160")
        self.root.resizable(False, False)
        self.msg = tk.StringVar(value="Dang chuan bi...")
        tk.Label(self.root, textvariable=self.msg, anchor="w", justify="left",
                 wraplength=440).pack(fill="x", padx=15, pady=(18, 8))
        self.bar = ttk.Progressbar(self.root, length=440, mode="determinate", maximum=100)
        self.bar.pack(padx=15, pady=5)
        self.sub = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.sub, anchor="w", fg="#666",
                 wraplength=440).pack(fill="x", padx=15)
        self.root.update()

    # called from any thread
    def post(self, msg=None, pct=None, sub=None):
        self.q.put((msg, pct, sub))

    # called on main thread
    def _drain(self):
        try:
            while True:
                msg, pct, sub = self.q.get_nowait()
                if msg is not None:
                    self.msg.set(msg)
                if pct is not None:
                    self.bar["value"] = max(0, min(100, pct))
                if sub is not None:
                    self.sub.set(sub)
        except queue.Empty:
            pass

    def run_until(self, worker_thread):
        """Pump the queue on the main thread until the worker finishes."""
        while worker_thread.is_alive():
            self._drain()
            self.root.update()
            time.sleep(0.05)
        self._drain()
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# ----------------------------- helpers ----------------------------- #
def port_up(port, timeout=2):
    for path in ("/v1/health", "/"):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout)
            return True
        except Exception:
            continue
    return False


def build_windows_runtime(sp):
    sp.post(msg="Lan dau: dang cai dong co chay GUI (~vai phut, can mang)...", pct=2, sub="")
    ps1 = os.path.join(SCRIPTS_DIR, "bootstrap_runtime.ps1")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
           "-RuntimeDir", RUNTIME_DIR, "-RepoSrc", ENGINE_SRC,
           "-TkBundle", os.path.join(BASE, "tk_bundle")]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=CREATE_NO_WINDOW)
    pct = 3
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if not line:
            continue
        if line.startswith("==="):
            pct = min(pct + 12, 95)
            sp.post(pct=pct, sub=line.strip("= "))
        else:
            sp.post(sub=line[:80])
    proc.wait()
    if not bootstrap.runtime_ready(RUNTIME_DIR):
        raise RuntimeError("Khong cai duoc dong co GUI. Kiem tra mang roi mo lai app.")


def ensure_wsl(sp):
    """Return 'ready' | 'reboot' | 'failed'."""
    st = wsl_engine.status(SCRIPTS_DIR, DISTRO)

    if st["engine"] != "yes":
        if os.path.exists(REBOOT_MARK):
            return "reboot"  # already installed; just needs the restart
        sp.post(msg="Dang cai Windows Subsystem for Linux (se hien hop thoai Admin - bam Yes)...",
                pct=5, sub="")
        wsl_engine.install_engine_elevated()
        try:
            open(REBOOT_MARK, "w").close()
        except OSError:
            pass
        return "reboot"

    if st["distro"] != "yes":
        sp.post(msg="Dang cai Ubuntu cho engine nhanh...", pct=10, sub="")
        ok, _ = wsl_engine.install_distro(DISTRO)
        st = wsl_engine.status(SCRIPTS_DIR, DISTRO)
        if st["distro"] != "yes":
            # distro install sometimes needs the reboot too
            if not os.path.exists(REBOOT_MARK):
                open(REBOOT_MARK, "w").close()
            return "reboot"

    if st["bootstrap"] != "yes":
        sp.post(msg="Dang cai engine TTS trong Linux (lan dau ~15-30 phut: tai torch + model)...",
                pct=12, sub="")
        steps = {"1/6": 15, "2/6": 25, "3/6": 30, "4/6": 60, "5/6": 75, "6/6": 90}

        def on_line(l):
            for k, v in steps.items():
                if k in l:
                    sp.post(pct=v, sub=l.strip("= "))
                    return
            sp.post(sub=l[:80])

        ok = wsl_engine.run_bootstrap(SCRIPTS_DIR, DISTRO, MODEL_BASE_URL, on_line=on_line)
        if not ok:
            return "failed"

    # clear reboot marker once everything is up
    if os.path.exists(REBOOT_MARK):
        try:
            os.remove(REBOOT_MARK)
        except OSError:
            pass
    return "ready"


def start_wsl_server_and_wait(sp):
    """Start the WSL --compile server and wait until it answers. Returns True/False."""
    sp.post(msg="Dang khoi dong engine nhanh (compile lan dau ~2-3 phut)...", pct=92, sub="")
    proc = wsl_engine.start_server(SCRIPTS_DIR, DISTRO, PORT)
    # Readiness is detected by polling the port (server logs to a file in WSL).
    for _ in range(160):  # ~5 min
        if port_up(PORT):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(2)
    return False


def ensure_windows_model(sp):
    """Fallback path: download model to the Windows side for the --half server."""
    if bootstrap.model_ready(MODEL_DIR):
        return
    sp.post(msg="Dang tai mo hinh giong noi (~3.4GB, mot lan)...", pct=20, sub="")

    def prog(done, total, name):
        pct = 100 * done / total if total else 0
        sp.post(pct=pct, sub="%s (%.0f%%)" % (name, pct))

    bootstrap.ensure_model(MODEL_DIR, MODEL_BASE_URL, progress=prog)


def check_update(sp):
    owner = CFG.get("github_owner", "")
    repo = CFG.get("github_repo", "")
    if not owner or owner.startswith("REPLACE"):
        return
    info = updater.check_for_update(owner, repo, APP_DIR)
    if not info.get("available") or info["kind"] != "app":
        return
    zpath = os.path.join(BASE, "_update.zip")
    sp.post(msg="Dang tai ban cap nhat...", pct=0)
    try:
        updater.download(info["app_zip_url"], zpath,
                         progress=lambda d, t: sp.post(pct=100 * d / t if t else 0))
        updater.apply_app_update(zpath, APP_DIR)
        os.remove(zpath)
    except Exception:
        pass


def launch_gui():
    py = os.path.join(RUNTIME_DIR, "python.exe")
    gui = os.path.join(APP_DIR, "tts_gui.py")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TV_BASE"] = BASE
    env["TV_MODEL_DIR"] = MODEL_DIR
    env["TV_ENGINE_SRC"] = ENGINE_SRC
    env["TV_RUNTIME"] = RUNTIME_DIR
    env["TCL_LIBRARY"] = os.path.join(RUNTIME_DIR, "tcl", "tcl8.6")
    env["TK_LIBRARY"] = os.path.join(RUNTIME_DIR, "tcl", "tk8.6")
    env["TV_PORT"] = str(PORT)
    subprocess.Popen([py, gui], cwd=ENGINE_SRC, env=env, creationflags=CREATE_NO_WINDOW)


# ----------------------------- main ----------------------------- #
def main():
    sp = Splash()
    result = {"error": None, "reboot": False, "fast": False}

    def work():
        try:
            if not bootstrap.runtime_ready(RUNTIME_DIR):
                build_windows_runtime(sp)
            check_update(sp)

            wsl_state = "failed"
            if MODE == "wsl":
                wsl_state = ensure_wsl(sp)
                if wsl_state == "reboot":
                    result["reboot"] = True
                    return
                if wsl_state == "ready":
                    if start_wsl_server_and_wait(sp):
                        result["fast"] = True
                    else:
                        wsl_state = "failed"
            if not result["fast"]:
                ensure_windows_model(sp)  # GUI will spawn the Windows --half server
        except Exception as e:  # noqa
            result["error"] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    sp.run_until(t)

    if result["error"]:
        sp.close()
        messagebox.showerror("Tool Voice", result["error"])
        sys.exit(1)
    if result["reboot"]:
        sp.close()
        messagebox.showinfo(
            "Tool Voice — can khoi dong lai",
            "Da cai dat Linux engine.\n\nVui long KHOI DONG LAI may tinh, "
            "roi mo lai Tool Voice de tiep tuc cai dat.")
        sys.exit(0)

    sp.post(msg=("Dang mo Tool Voice (che do nhanh)..." if result["fast"]
                 else "Dang mo Tool Voice..."), pct=100)
    sp.root.update()
    launch_gui()
    sp.close()


if __name__ == "__main__":
    main()
