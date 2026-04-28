@echo off
echo Starting MinhNt Charger Simulator...
start python modbus_multi_slave.py
timeout /t 5
start http://localhost:5000
exit
