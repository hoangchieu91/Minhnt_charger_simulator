@echo off
echo Đang tắt toàn bộ tiến trình simulator...
powershell -Command "Get-Process | Where-Object { $_.Path -like '*Minhnt_charger_simulator*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
taskkill /F /IM python.exe /T 2>nul
echo Đã dọn dẹp sạch sẽ.
pause
