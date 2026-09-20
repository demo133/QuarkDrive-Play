# ============================================================
#  mount-quark.ps1 - mount OpenList(Quark) as a local drive
#  letter via rclone (needs WinFsp installed).
#
#  Usage:
#    powershell -NoProfile -ExecutionPolicy Bypass -File mount-quark.ps1
#        -> mounts openlist:/quark as Z:  (keep the window open)
#    powershell ... -File mount-quark.ps1 -DriveLetter V
#    powershell ... -File mount-quark.ps1 -Unmount
# ============================================================
param(
    [string]$DriveLetter = "Z",
    [int]$BufferMB = 64,
    [int]$ChunkMB = 32,
    [int]$CacheMaxGB = 20,
    [switch]$Unmount
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

if ($Unmount) {
    Get-Process rclone -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "[ok] rclone stopped, drive unmounted."
    exit 0
}

if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
    Write-Host "[err] rclone not found in PATH."
    Write-Host "      Install it with:  winget install Rclone.Rclone"
    Write-Host "      (open a NEW terminal after installing)"
    exit 1
}

# make sure the 'openlist' remote exists
$remotes = @(rclone listremotes 2>$null)
if ($remotes -notcontains "openlist:") {
    $obscured = rclone obscure $OpenListPass
    rclone config create openlist webdav "url=$OpenListUrl/dav" "vendor=other" "user=$OpenListUser" "pass=$obscured" | Out-Null
    Write-Host "[ok] created rclone remote 'openlist'"
}

$cacheDir = Join-Path $env:LOCALAPPDATA "rclone-cache-quark"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$rcArgs = @(
    "mount", ("openlist:" + $MountPath), ($DriveLetter + ":"),
    "--volname", "QuarkDrive",
    "--vfs-cache-mode", "writes",
    "--vfs-read-chunk-size", ("{0}M" -f $ChunkMB),
    "--vfs-read-chunk-size-limit", "1G",
    "--buffer-size", ("{0}M" -f $BufferMB),
    "--dir-cache-time", "15s",
    "--vfs-cache-max-size", ("{0}G" -f $CacheMaxGB),
    "--vfs-cache-max-age", "6h",
    "--cache-dir", $cacheDir,
    "--attr-timeout", "30s",
    "--log-level", "NOTICE"
)

Write-Host ("[mount] openlist:" + $MountPath + "  ->  " + $DriveLetter + ":")
Write-Host  "[info] keep this window open. Close it or press Ctrl+C to unmount."

& rclone @rcArgs
