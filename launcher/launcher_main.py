"""
Tool Voice launcher (frozen to ToolVoice.exe).
Stdlib-only. Runs BEFORE the heavy runtime exists, so it cannot import torch etc.

Responsibilities:
  1. Locate the install dir (folder containing this exe).
  2. First run: build the portable Python runtime (scripts\bootstrap_runtime.ps1) with a progress window.
  3. First run: download the model from HuggingFace with a progress bar.
  4. Check GitHub for app updates (small) -> offer to apply; runtime updates -> point to installer.
  5. Launch the GUI under the portable runtime python.

Install layout (created by installer + first run):
  INSTALL_DIR\
    ToolVoice.exe
    app\  (tts_gui.py, version.json, config.json, engine_src\<fish-speech source>)
    scripts\bootstrap_runtime.ps1
    runtime\   (built first run)
    models\    (downloaded first run)
"""
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import bootstrap
import updater


def install_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root when running source


BASE = install_dir()
APP_DIR = os.path.join(BASE, "app")
RUNTIME_DIR = os.path.join(BASE, "runtime")
SCRIPTS_DIR = os.path.join(BASE, "scripts")


def load_config():
    for p in (os.path.join(APP_DIR, "config.json"), os.path.join(BASE, "config.json")):
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:  # tolerate BOM
                return json.load(f)
    return {}


CFG = load_config()
MODEL_DIR = os.path.join(BASE, CFG.get("model_dir", "models/openaudio-s1-mini").replace("/", os.sep))
ENGINE_SRC = os.path.join(APP_DIR, "engine_src")


# --------------------------- progress window --------------------------- #
class Splash:
    def __init__(self, title="Tool Voice"):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("460x150")
        self.root.resizable(False, False)
        self.msg = tk.StringVar(value="Dang chuan bi...")
        tk.Label(self.root, textvariable=self.msg, anchor="w", justify="left",
                 wraplength=430).pack(fill="x", padx=15, pady=(18, 8))
        self.bar = ttk.Progressbar(self.root, length=430, mode="determinate", maximum=100)
        self.bar.pack(padx=15, pady=5)
        self.sub = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.sub, anchor="w", fg="#666").pack(fill="x", padx=15)
        self.root.update()

    def set(self, msg=None, pct=None, sub=None):
        if msg is not None:
            self.msg.set(msg)
        if pct is not None:
            self.bar["value"] = pct
        if sub is not None:
            self.sub.set(sub)
        try:
            self.root.update()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# --------------------------- steps --------------------------- #
def build_runtime(splash):
    splash.set(msg="Lan dau chay: dang cai dat dong co AI (tai ~3GB, can mang, mot lan duy nhat)...",
               pct=0, sub="Buoc nay co the mat 10-20 phut.")
    ps1 = os.path.join(SCRIPTS_DIR, "bootstrap_runtime.ps1")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
           "-RuntimeDir", RUNTIME_DIR, "-RepoSrc", ENGINE_SRC,
           "-TkBundle", os.path.join(BASE, "tk_bundle")]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    pct = 2
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if not line:
            continue
        if line.startswith("==="):
            pct = min(pct + 14, 95)
            splash.set(pct=pct, sub=line.strip("= "))
        else:
            splash.set(sub=line[:70])
    proc.wait()
    if proc.returncode != 0 or not bootstrap.runtime_ready(RUNTIME_DIR):
        raise RuntimeError("Cai dat dong co that bai. Kiem tra ket noi mang roi mo lai app.")
    splash.set(pct=100, sub="Dong co da san sang.")


def download_model(splash):
    splash.set(msg="Dang tai mo hinh giong noi (~3.4GB, mot lan duy nhat)...", pct=0, sub="")

    def prog(done, total, name):
        pct = 100 * done / total if total else 0
        splash.set(pct=pct, sub="%s  (%.0f%%)" % (name, pct))

    base = CFG.get("model_base_url") or bootstrap.DEFAULT_BASE
    ok = bootstrap.ensure_model(MODEL_DIR, base, progress=prog)
    if not ok:
        raise RuntimeError("Tai mo hinh that bai. Kiem tra mang roi mo lai app.")


def check_update(splash):
    owner = CFG.get("github_owner", "")
    repo = CFG.get("github_repo", "")
    if not owner or owner.startswith("REPLACE"):
        return  # not configured yet
    splash.set(msg="Dang kiem tra ban cap nhat...", pct=None, sub="")
    info = updater.check_for_update(owner, repo, APP_DIR)
    if not info.get("available"):
        return
    if info["kind"] == "runtime":
        messagebox.showinfo("Co ban cap nhat lon",
                            "Da co phien ban moi (%s) yeu cau cai dat lai.\n"
                            "Vui long tai bo cai moi tai:\n%s"
                            % (info["remote_app"], info.get("html_url", "")))
        return
    # app hot-swap
    if messagebox.askyesno("Co ban cap nhat",
                           "Da co phien ban %s (ban dang dung %s).\nCap nhat ngay?"
                           % (info["remote_app"], info["local_app"])):
        splash.set(msg="Dang tai ban cap nhat...", pct=0)
        zpath = os.path.join(BASE, "_update.zip")
        updater.download(info["app_zip_url"], zpath,
                         progress=lambda d, t: splash.set(pct=100 * d / t if t else 0))
        updater.apply_app_update(zpath, APP_DIR)
        try:
            os.remove(zpath)
        except OSError:
            pass
        splash.set(msg="Da cap nhat xong.", pct=100)


def launch_gui():
    py = os.path.join(RUNTIME_DIR, "python.exe")
    gui = os.path.join(APP_DIR, "tts_gui.py")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # Tell the GUI where things live (it reads these).
    env["TV_BASE"] = BASE
    env["TV_MODEL_DIR"] = MODEL_DIR
    env["TV_ENGINE_SRC"] = ENGINE_SRC
    env["TV_RUNTIME"] = RUNTIME_DIR
    # tkinter in the embeddable runtime needs Tcl/Tk pointed at the bundled libs.
    env["TCL_LIBRARY"] = os.path.join(RUNTIME_DIR, "tcl", "tcl8.6")
    env["TK_LIBRARY"] = os.path.join(RUNTIME_DIR, "tcl", "tk8.6")
    env["TV_PORT"] = str(CFG.get("server_port", 8080))
    subprocess.Popen([py, gui], cwd=ENGINE_SRC, env=env,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    # First-run heavy setup needs a window; subsequent runs are quick.
    first_run = not bootstrap.runtime_ready(RUNTIME_DIR) or not bootstrap.model_ready(MODEL_DIR)
    splash = Splash()
    error = [None]

    def work():
        try:
            if not bootstrap.runtime_ready(RUNTIME_DIR):
                build_runtime(splash)
            if not bootstrap.model_ready(MODEL_DIR):
                download_model(splash)
            check_update(splash)
        except Exception as e:  # noqa
            error[0] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        splash.set()  # pump UI
        splash.root.after(100)
        splash.root.update()
    if error[0]:
        splash.close()
        messagebox.showerror("Tool Voice", error[0])
        sys.exit(1)
    splash.set(msg="Dang mo Tool Voice...", pct=100)
    launch_gui()
    splash.close()


if __name__ == "__main__":
    main()
