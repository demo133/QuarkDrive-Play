# ============================================================
#  play-url.ps1 - handle a "quarkplay:" link and open it in
#  PotPlayer as an OpenList direct URL.
#
#  quarkplay:/quark/movies/movie.mkv
#      -> http://127.0.0.1:5244/d/movies/movie.mkv  -> PotPlayer
# ============================================================
param([string]$Uri = "")

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

$s = $Uri
if ([string]::IsNullOrWhiteSpace($s)) {
    Write-Host "[usage] quarkplay:/quark/some folder/movie.mkv"
    exit 1
}

# strip the protocol prefix (browser may add 1-3 slashes)
$s = $s -replace '^quarkplay:(/)*', ''

# decode %20 etc.
$s = [uri]::UnescapeDataString($s)

if (-not $s.StartsWith('/')) { $s = '/' + $s }

# NOTE: /d/ links must keep the FULL path (mount path + subpath),
# e.g. quarkplay:/quark/movies/a.mkv -> /d/quark/movies/a.mkv
$enc = ($s.Split('/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
$url = "$OpenListUrl/d$enc"

if (-not (Test-Path $PotPlayerExe)) {
    Write-Host ("[err] PotPlayer not found: " + $PotPlayerExe + "  (edit config.ps1)")
    exit 1
}

Start-Process -FilePath $PotPlayerExe -ArgumentList ('"' + $url + '"')
Write-Host ("[ok] PotPlayer <- " + $url)
