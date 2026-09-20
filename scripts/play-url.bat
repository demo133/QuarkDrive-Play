@echo off
rem QuarkPlay protocol handler -> play-url.ps1 -> PotPlayer
rem This file is referenced by register-quarkplay.reg.
rem If you move the scripts folder, update register-quarkplay.reg accordingly.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0play-url.ps1" "%~1"
