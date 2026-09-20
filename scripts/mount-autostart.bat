@echo off
rem Auto-mount Quark as a drive letter at logon (hidden window).
rem Requires: WinFsp + rclone installed, OpenList running.
rem 1) Press Win+R, type  shell:startup  , press Enter
rem 2) Put a shortcut to this .bat into the folder that opens
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0mount-quark.ps1"
