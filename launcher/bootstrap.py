"""
First-run helpers for Tool Voice (stdlib-only).
- ensure_model(): download the OpenAudio S1-mini checkpoint from HuggingFace.
- runtime_ready(): check the portable Python runtime exists.

Kept dependency-free so it can run from the frozen launcher before the
heavy runtime/torch environment exists.
"""
import os
import ssl
import urllib.request

# The official HF model (fishaudio/openaudio-s1-mini) is GATED (download needs a
# token + accepted license), so we host the same files on the project's own
# GitHub Release and pull them from there (public, no auth, each file < 2GB).
# model_base_url example:
#   https://github.com/<owner>/<repo>/releases/download/model-v1
DEFAULT_BASE = "https://github.com/REPLACE_OWNER/REPLACE_REPO/releases/download/model-v1"

# (filename, approx_bytes) — approx sizes only used for a friendly progress total.
MODEL_FILES = [
    ("config.json", 1_000),
    ("special_tokens.json", 130_000),
    ("tokenizer.tiktoken", 2_600_000),
    ("codec.pth", 1_870_000_000),
    ("model.pth", 1_740_000_000),
]


def _ctx():
    return ssl.create_default_context()


def runtime_ready(runtime_dir):
    return os.path.exists(os.path.join(runtime_dir, ".runtime_ok")) and \
           os.path.exists(os.path.join(runtime_dir, "python.exe"))


def model_ready(model_dir):
    need = ["codec.pth", "model.pth", "config.json", "tokenizer.tiktoken", "special_tokens.json"]
    return all(os.path.exists(os.path.join(model_dir, n)) for n in need)


def _download_one(url, dest, on_bytes=None, timeout=60):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "ToolVoice"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                if on_bytes:
                    on_bytes(len(chunk))
    os.replace(tmp, dest)


def ensure_model(model_dir, base_url, progress=None):
    """
    Download missing model files into model_dir from <base_url>/<filename>.
    progress(done_bytes, total_bytes, current_name) is called periodically.
    Returns True when all files are present.
    """
    os.makedirs(model_dir, exist_ok=True)
    base_url = base_url.rstrip("/")
    total = sum(sz for _, sz in MODEL_FILES)
    done = [0]

    for name, _approx in MODEL_FILES:
        dest = os.path.join(model_dir, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            # already there; count it toward progress
            done[0] += os.path.getsize(dest)
            if progress:
                progress(done[0], total, name)
            continue
        url = base_url + "/" + name

        def _cb(n, _name=name):
            done[0] += n
            if progress:
                progress(done[0], total, _name)

        _download_one(url, dest, on_bytes=_cb)

    return model_ready(model_dir)


if __name__ == "__main__":
    import sys
    md = sys.argv[1] if len(sys.argv) > 1 else "models/openaudio-s1-mini"
    base = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BASE

    def p(done, total, name):
        pct = 100 * done / total if total else 0
        sys.stdout.write("\r%5.1f%%  %-20s" % (pct, name))
        sys.stdout.flush()

    ok = ensure_model(md, base, progress=p)
    print("\nmodel_ready:", ok)
