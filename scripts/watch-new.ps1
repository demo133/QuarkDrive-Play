# ============================================================
#  watch-new.ps1 - scan OpenList(Quark) for new video files,
#  build a playlist and launch PotPlayer.
#
#  Usage (run in PowerShell):
#    powershell -NoProfile -ExecutionPolicy Bypass -File watch-new.ps1
#    powershell ... -File watch-new.ps1 -Watch      keep polling forever
#    powershell ... -File watch-new.ps1 -NoOpen     build playlist only
#    powershell ... -File watch-new.ps1 -Hours 48   custom "new" window
# ============================================================
param(
    [switch]$Watch,
    [switch]$NoOpen,
    [int]$Hours = -1
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

if ($Hours -lt 0) { $Hours = $HoursWindow }
$ExtList = @($VideoExt) | ForEach-Object { $_.ToLowerInvariant() }

function Get-OpenListToken {
    $body = @{ username = $OpenListUser; password = $OpenListPass } | ConvertTo-Json
    $r = Invoke-RestMethod -Method Post -Uri "$OpenListUrl/api/auth/login" `
         -Body $body -ContentType "application/json"
    if ($r.code -ne 200) { throw ("Login failed: " + $r.message) }
    return $r.data.token
}

function Get-DirList([string]$Token, [string]$Path, [bool]$Refresh) {
    $body = @{ path = $Path; page = 1; per_page = 0; refresh = $Refresh } | ConvertTo-Json
    $hdr = @{ Authorization = $Token }
    $r = Invoke-RestMethod -Method Post -Uri "$OpenListUrl/api/fs/list" `
         -Headers $hdr -Body $body -ContentType "application/json"
    if ($r.code -ne 200) { throw ("List failed [$Path]: " + $r.message) }
    if ($null -eq $r.data.content) { return @() }
    return @($r.data.content)
}

function Get-VideoFiles([string]$Token, [string]$Path, [int]$Depth) {
    $found = @()
    if ($Depth -gt $MaxDepth) { return $found }
    try {
        $items = Get-DirList $Token $Path $false
    }
    catch {
        # retry once with cache refresh; if it still fails, skip this folder
        try {
            $items = Get-DirList $Token $Path $true
        }
        catch {
            Write-Host ("[skip] cannot list " + $Path + " -> " + $_.Exception.Message)
            return $found
        }
    }
    foreach ($it in $items) {
        $child = $Path.TrimEnd('/') + '/' + $it.name
        if ($it.is_dir) {
            $found += Get-VideoFiles $Token $child ($Depth + 1)
        }
        else {
            $ext = [System.IO.Path]::GetExtension($it.name).ToLowerInvariant()
            if ($ExtList -contains $ext) {
                $found += [pscustomobject]@{
                    path     = $child
                    name     = $it.name
                    size     = [int64]$it.size
                    sign     = [string]$it.sign
                    modified = [string]$it.modified
                }
            }
        }
    }
    return $found
}

function Format-PlayUrl([pscustomobject]$Item) {
    # /d/ links must contain the FULL path (mount path + subpath), e.g.
    # /d/quark/movies/a.mkv for a storage mounted at /quark
    $rel = $Item.path
    if (-not $rel.StartsWith('/')) { $rel = '/' + $rel }
    $enc = ($rel.Split('/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
    $url = "$OpenListUrl/d$enc"
    if ($Item.sign) { $url += "?sign=" + [uri]::EscapeDataString($Item.sign) }
    return $url
}

function Invoke-Scan {
    $token = Get-OpenListToken

    $all = @()
    foreach ($d in $ScanDirs) { $all += Get-VideoFiles $token $d 0 }

    # load seen-state (text file, one "modified<TAB>path" per line; PS 5.1 safe)
    $state = @{}
    if (Test-Path $StateFile) {
        foreach ($line in (Get-Content $StateFile -Encoding UTF8)) {
            $p = $line.Split("`t", 2)
            if ($p.Count -eq 2 -and $p[1]) { $state[$p[1]] = $p[0] }
        }
    }

    $cutoff = (Get-Date).AddHours(-1 * $Hours)
    $newItems = @()
    foreach ($f in $all) {
        $isNew = $false
        if (-not $state.ContainsKey($f.path)) { $isNew = $true }
        elseif ($state[$f.path] -ne $f.modified) { $isNew = $true }
        if ($f.modified) {
            try {
                $mtime = [datetime]::Parse($f.modified)
                if ($mtime -ge $cutoff) { $isNew = $true }
            } catch { }
        }
        if ($isNew) { $newItems += $f }
    }

    # refresh state
    $lines = @()
    foreach ($f in $all) { $lines += ($f.modified + "`t" + $f.path) }
    [System.IO.File]::WriteAllLines($StateFile, $lines, (New-Object System.Text.UTF8Encoding($true)))

    if ($newItems.Count -gt 0) {
        $pl = @("#EXTM3U")
        foreach ($f in $newItems) {
            $pl += "#EXTINF:-1," + $f.name
            $pl += (Format-PlayUrl $f)
        }
        [System.IO.File]::WriteAllLines($PlaylistFile, $pl, (New-Object System.Text.UTF8Encoding($true)))
        Write-Host ("[ok] new videos: " + $newItems.Count + "   playlist: " + $PlaylistFile)
        if (-not $NoOpen) {
            if (Test-Path $PotPlayerExe) {
                Start-Process -FilePath $PotPlayerExe -ArgumentList ('"' + $PlaylistFile + '"')
                Write-Host "[ok] launched PotPlayer"
            }
            else {
                Write-Host ("[warn] PotPlayer not found: " + $PotPlayerExe + "  (edit config.ps1)")
            }
        }
    }
    else {
        Write-Host ("[ok] no new videos (scanned " + $all.Count + " video files)")
    }
}

try {
    if ($Watch) {
        Write-Host ("[watch] polling every " + $PollSeconds + "s. Press Ctrl+C to stop.")
        while ($true) {
            try { Invoke-Scan } catch { Write-Host ("[err] " + $_.Exception.Message) }
            Start-Sleep -Seconds $PollSeconds
        }
    }
    else {
        Invoke-Scan
    }
}
catch {
    Write-Host ("[err] " + $_.Exception.Message)
    exit 1
}
