"""
WSL orchestration for Tool Voice (stdlib-only; runs from the frozen launcher).

State machine (re-detected every launch):
  engine no            -> install WSL (elevated) + ask reboot        -> 'reboot'
  engine yes, distro no-> install distro (no elevation)              -> may be 'reboot' or continue
  distro yes, boot no  -> run wsl_bootstrap.sh (as root) with progress
  boot yes             -> 'ready'

The Linux server then runs with torch.compile (fast). If anything here fails,
the caller falls back to the Windows --half server.
"""
import os
import re
import subprocess
import time

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def win_to_wsl(path):
    """C:\\a\\b  ->  /mnt/c/a/b"""
    p = os.path.abspath(path)
    drive, rest = os.path.splitdrive(p)
    drive = drive.rstrip(":").lower()
    rest = rest.replace("\\", "/")
    return "/mnt/" + drive + rest


def _run(args, timeout=None):
    """Run a command, return (rc, stdout+stderr)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa
        return 1, str(e)


def status(scripts_dir, distro):
    """Return dict {engine, distro, bootstrap} via wsl_status.ps1."""
    ps1 = os.path.join(scripts_dir, "wsl_status.ps1")
    rc, out = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps1, "-Distro", distro], timeout=60)
    m = re.search(r"STATE=(\w+)\|(\w+)\|(\w+)", out)
    if not m:
        return {"engine": "no", "distro": "no", "bootstrap": "na", "raw": out}
    return {"engine": m.group(1), "distro": m.group(2), "bootstrap": m.group(3)}


def install_engine_elevated():
    """Run `wsl --install --no-launch` elevated (UAC). Returns True if the
    elevated process was launched (a reboot will then be required)."""
    # -Verb RunAs triggers the UAC prompt; -Wait so we know when it's done.
    inner = "wsl.exe --install --no-launch"
    cmd = ["powershell", "-NoProfile", "-Command",
           "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
           "'-NoProfile','-Command','{}'".format(inner)]
    rc, out = _run(cmd, timeout=600)
    return rc == 0


def install_distro(distro):
    """Install the distro without launching its first-run OOBE."""
    rc, out = _run(["wsl.exe", "--install", "-d", distro, "--no-launch"], timeout=900)
    return rc == 0, out


def run_bootstrap(scripts_dir, distro, model_base_url, on_line=None):
    """Run wsl_bootstrap.sh as root inside the distro, streaming lines to on_line.
    Returns True on TOOLVOICE_BOOTSTRAP_DONE."""
    sh = win_to_wsl(os.path.join(scripts_dir, "wsl_bootstrap.sh"))
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"
    cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "bash", sh, model_base_url]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace",
                             env=env, creationflags=CREATE_NO_WINDOW)
    except Exception as e:  # noqa
        if on_line:
            on_line("ERROR launching bootstrap: %s" % e)
        return False
    ok = False
    for line in iter(p.stdout.readline, ""):
        line = line.rstrip()
        if not line:
            continue
        if "TOOLVOICE_BOOTSTRAP_DONE" in line:
            ok = True
        if on_line:
            on_line(line)
    p.wait()
    return ok and p.returncode == 0


def start_server(scripts_dir, distro, port):
    """Start the WSL server (torch.compile) in the background. Returns the Popen.
    Output is discarded here (the server logs to a file inside WSL) so the
    server never depends on a Windows pipe that closes when the launcher exits
    — writing to a closed pipe is what caused '[Errno 32] Broken pipe' 500s."""
    sh = win_to_wsl(os.path.join(scripts_dir, "wsl_run_server.sh"))
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"
    cmd = ["wsl.exe", "-d", distro, "-u", "root", "--", "bash", sh, str(port)]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, env=env,
                            creationflags=CREATE_NO_WINDOW)
