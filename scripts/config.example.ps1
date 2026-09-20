# ============================================================
#  config.example.ps1 - copy this file to config.ps1 and fill in
#  your own values. config.ps1 is git-ignored (holds credentials).
# ============================================================

# --- OpenList (Alist/OpenList server) ---
$OpenListUrl  = "http://127.0.0.1:5244"   # OpenList web address
$OpenListUser = "admin"
$OpenListPass = "YOUR_OPENLIST_PASSWORD"  # your OpenList admin password
$MountPath    = "/quark"                  # mount path of the Quark storage in OpenList

# --- Which folders to scan for new videos (paths inside OpenList) ---
$ScanDirs = @("/quark")

# --- PotPlayer ---
# Typical installs:
#   C:\Program Files\PotPlayer\PotPlayerMini64.exe
#   C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe
$PotPlayerExe = "C:\Program Files\PotPlayer\PotPlayerMini64.exe"

# --- "New video" rules ---
$HoursWindow = 24      # files modified within the last N hours count as new
$PollSeconds = 60      # watch mode: rescan interval
$MaxDepth    = 4       # how deep to recurse into folders

# --- Output files (next to the scripts) ---
$StateFile    = "$PSScriptRoot\seen-videos.txt"
$PlaylistFile = "$PSScriptRoot\new-videos.m3u"

# --- Video extensions treated as playable ---
$VideoExt = @(".mp4",".mkv",".ts",".m2ts",".avi",".mov",".wmv",".flv",".webm",".m4v",".rmvb")
