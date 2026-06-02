"""
Update checker for Tool Voice.
Stdlib-only (urllib/json/zipfile) so it can run on any Python without extra deps.

Release convention on GitHub:
  - tag:   v<app_version>            e.g. v1.0.1
  - asset: app-v<app_version>.zip    contains the updated files for the app/ folder
  - the release body / a version.json asset carries {app_version, runtime_version}

We hot-swap the small app/ folder when only app_version changed.
If runtime_version changed (torch/model code), we tell the user to run the full installer.
"""
import json
import os
import re
import shutil
import ssl
import tempfile
import urllib.request
import zipfile

API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
_UA = {"User-Agent": "ToolVoice-Updater"}


def _ctx():
    # Be lenient about corporate SSL interception on target machines.
    c = ssl.create_default_context()
    return c


def parse_version(v):
    """'v1.2.3' or '1.2.3' -> (1,2,3). Missing parts -> 0."""
    nums = re.findall(r"\d+", v or "")
    parts = [int(x) for x in nums[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def read_local_version(app_dir):
    try:
        with open(os.path.join(app_dir, "version.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {"app_version": "0.0.0", "runtime_version": "0.0.0"}


def fetch_latest_release(owner, repo, timeout=10):
    """Return the GitHub 'latest release' JSON, or None on any failure (offline-safe)."""
    url = API.format(owner=owner, repo=repo)
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _asset_url(release, name_substr):
    for a in release.get("assets", []):
        if name_substr in a.get("name", ""):
            return a.get("browser_download_url"), a.get("name")
    return None, None


def check_for_update(owner, repo, app_dir):
    """
    Returns a dict describing the situation:
      {available, kind, remote_app, remote_runtime, local_app, local_runtime,
       app_zip_url, notes, html_url}
    kind: 'none' | 'app' (hot-swap) | 'runtime' (needs full installer)
    """
    local = read_local_version(app_dir)
    local_app = local.get("app_version", "0.0.0")
    local_runtime = local.get("runtime_version", "0.0.0")

    rel = fetch_latest_release(owner, repo)
    if not rel:
        return {"available": False, "kind": "none", "reason": "offline_or_no_release",
                "local_app": local_app, "local_runtime": local_runtime}

    remote_app = (rel.get("tag_name") or "0.0.0").lstrip("v")

    # Optional version.json asset carries runtime_version; fall back to local.
    remote_runtime = local_runtime
    vurl, _ = _asset_url(rel, "version.json")
    if vurl:
        try:
            req = urllib.request.Request(vurl, headers=_UA)
            with urllib.request.urlopen(req, timeout=10, context=_ctx()) as r:
                meta = json.loads(r.read().decode("utf-8"))
                remote_app = meta.get("app_version", remote_app)
                remote_runtime = meta.get("runtime_version", remote_runtime)
        except Exception:
            pass

    app_zip_url, _ = _asset_url(rel, "app-")

    available = is_newer(remote_app, local_app) or is_newer(remote_runtime, local_runtime)
    if not available:
        kind = "none"
    elif is_newer(remote_runtime, local_runtime):
        kind = "runtime"   # heavy change -> full installer
    else:
        kind = "app"       # light change -> hot-swap app/

    return {
        "available": available,
        "kind": kind,
        "remote_app": remote_app,
        "remote_runtime": remote_runtime,
        "local_app": local_app,
        "local_runtime": local_runtime,
        "app_zip_url": app_zip_url,
        "notes": rel.get("body", ""),
        "html_url": rel.get("html_url", ""),
    }


def download(url, dest, progress=None, timeout=60):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)
    return dest


def apply_app_update(zip_path, app_dir):
    """
    Extract app-*.zip and replace the contents of app_dir atomically-ish.
    The zip is expected to contain the files that live directly under app/.
    Keeps a backup at app_dir + '.bak' until success.
    """
    parent = os.path.dirname(app_dir.rstrip("\\/"))
    staging = tempfile.mkdtemp(prefix="tv_upd_", dir=parent)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(staging)
        # If the zip wrapped everything in a single top folder, descend into it.
        entries = os.listdir(staging)
        if len(entries) == 1 and os.path.isdir(os.path.join(staging, entries[0])):
            staging_root = os.path.join(staging, entries[0])
        else:
            staging_root = staging

        backup = app_dir + ".bak"
        if os.path.exists(backup):
            shutil.rmtree(backup, ignore_errors=True)
        if os.path.exists(app_dir):
            os.rename(app_dir, backup)
        shutil.move(staging_root, app_dir)
        shutil.rmtree(backup, ignore_errors=True)
        return True
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    # quick self-test of version logic
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("2.0") == (2, 0, 0)
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.1.0")
    print("updater self-test OK")
