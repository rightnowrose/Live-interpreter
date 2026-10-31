@echo off
setlocal
cd /d "%~dp0"
echo Opening Edge extension manager and the extension folder...
start "" msedge.exe "edge://extensions/"
start "" explorer "%~dp0."
echo.
echo 1. Enable Developer mode (开发者模式).
echo 2. Click "Load unpacked" (加载解压缩的扩展).
echo 3. Select this folder: %~dp0
echo 4. Pin "RoseSI - Tab Audio" and click it on the target tab.
pause
