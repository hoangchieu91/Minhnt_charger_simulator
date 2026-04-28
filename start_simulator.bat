@echo off
title Charger Simulator Suite
color 0A

echo ====================================================
echo Khởi động Charger Simulator Suite
echo - Modbus Multi-Slave (COM37, ID 2-7)
echo - DLT645 Meter Simulator (COM29)
echo ====================================================

cd /d "D:\00_Code\Minhnt_charger_simulator"

:: Start Modbus Simulator
start "Modbus Multi-Slave" python modbus_multi_slave.py

:: Start DLT645 Simulator
start "DLT645 Simulator" python dlt645_sim_com29.py

echo Simulators are running in separate windows.
pause
