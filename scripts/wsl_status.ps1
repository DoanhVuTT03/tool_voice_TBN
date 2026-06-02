# wsl_status.ps1 — report setup state for the launcher.
# Prints one line: STATE=<engine>|<distro>|<bootstrap>
#   engine    : yes | no
#   distro    : yes | no
#   bootstrap : yes | no | na
# NOTE: PowerShell variable names are case-insensitive, so state vars must NOT
# collide with the $Distro parameter (that bug clobbered the distro name).
param([string]$Distro = "Ubuntu-22.04")

$env:WSL_UTF8 = "1"
$ErrorActionPreference = "SilentlyContinue"
$sEngine = "no"; $sDistro = "no"; $sBootstrap = "na"

$null = wsl.exe --status 2>$null
if ($LASTEXITCODE -eq 0) { $sEngine = "yes" }

if ($sEngine -eq "yes") {
  $null = wsl.exe -d $Distro -u root -- true 2>$null
  if ($LASTEXITCODE -eq 0) { $sDistro = "yes" }
}

if ($sDistro -eq "yes") {
  $sBootstrap = "no"
  $null = wsl.exe -d $Distro -u root -- test -f /opt/toolvoice/.stage_model 2>$null
  if ($LASTEXITCODE -eq 0) { $sBootstrap = "yes" }
}

Write-Output ("STATE={0}|{1}|{2}" -f $sEngine, $sDistro, $sBootstrap)
