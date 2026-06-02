<#
  bootstrap_runtime.ps1
  Builds a fully self-contained, relocatable Python runtime for Tool Voice.
  This is exactly what runs on a target machine on first launch (no system Python needed).

  Layout produced:
    <RuntimeDir>\
      python.exe, python311.dll, python311._pth, Lib\site-packages\ ...  (embeddable + deps)
      repo\tools\            (server code, run via `python -m tools.api_server`)
      repo\fish_speech\      (model code; also importable from site-packages)
      .runtime_ok            (marker written only on full success)
#>
[CmdletBinding()]
param(
  [string]$RuntimeDir = "D:\Tool_voice\ToolVoiceApp\build_output\runtime",
  [string]$RepoSrc    = "D:\Tool_voice\fish_speech_native",
  [string]$TkBundle   = "D:\Tool_voice\ToolVoiceApp\tk_bundle",
  [string]$PyEmbedUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
  [string]$TorchIndex = "https://download.pytorch.org/whl/cu124"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster downloads
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# Clean / create
if (Test-Path $RuntimeDir) { Remove-Item -Recurse -Force $RuntimeDir }
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$tmp = Join-Path $env:TEMP ("tv_rt_" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Step "1/6 Download python embeddable"
$zip = Join-Path $tmp "pyembed.zip"
Invoke-WebRequest -Uri $PyEmbedUrl -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $RuntimeDir -Force

Step "2/6 Configure ._pth (enable site-packages + repo)"
$pth = Get-ChildItem $RuntimeDir -Filter "python*._pth" | Select-Object -First 1
@"
python311.zip
.
Lib\site-packages
repo

import site
"@ | Set-Content -Path $pth.FullName -Encoding ascii
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir "Lib\site-packages") | Out-Null

Step "3/6 Bootstrap pip"
$py = Join-Path $RuntimeDir "python.exe"
$getpip = Join-Path $tmp "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
& $py $getpip --no-warn-script-location
& $py -m pip install --upgrade pip wheel setuptools --no-warn-script-location

Step "4/6 Install PyTorch (CUDA) - large download"
& $py -m pip install torch torchaudio --index-url $TorchIndex --no-warn-script-location

Step "5/6 Install fish-speech + deps from source"
# Install (non-editable) so fish_speech lands in site-packages and is relocatable.
& $py -m pip install "$RepoSrc" --no-warn-script-location
& $py -m pip install ormsgpack pyrootutils --no-warn-script-location

Step "6/6 Place .project-root marker for pyrootutils"
# tools/api_server.py calls pyrootutils.setup_root(__file__, indicator='.project-root').
# pip installs both `tools` and `fish_speech` into site-packages, so drop the marker
# in site-packages/ — find_root() walks up from site-packages/tools/ and finds it there.
$sitePkgs = Join-Path $RuntimeDir "Lib\site-packages"
New-Item -ItemType File -Path (Join-Path $sitePkgs ".project-root") -Force | Out-Null

Step "7/7 Add tkinter (embeddable Python ships without it) from tk_bundle"
# tk_bundle/ is shipped with the app: dll\ (_tkinter.pyd, tcl86t.dll, tk86t.dll), lib\tkinter, tcl\
if (Test-Path $TkBundle) {
  Copy-Item (Join-Path $TkBundle "dll\*") $RuntimeDir -Force
  Copy-Item (Join-Path $TkBundle "lib\tkinter") (Join-Path $sitePkgs "tkinter") -Recurse -Force
  Copy-Item (Join-Path $TkBundle "tcl") (Join-Path $RuntimeDir "tcl") -Recurse -Force
} else {
  Write-Host "WARNING: tk_bundle not found at $TkBundle - GUI may fail to start." -ForegroundColor Yellow
}

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue

# Verify torch imports under the embeddable python
Step "VERIFY torch under runtime"
& $py -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

"ok" | Set-Content -Path (Join-Path $RuntimeDir ".runtime_ok") -Encoding ascii
Write-Host "`nRUNTIME BUILD DONE -> $RuntimeDir" -ForegroundColor Green
