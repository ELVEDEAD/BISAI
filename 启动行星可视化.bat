@echo off
chcp 936 >nul
cd /d "%~dp0"
title 已知行星可视化

set "PY="

REM 1) 本机已装依赖的 Python 3.10（优先）
if exist "C:\Users\ALVE\AppData\Local\Programs\Python\Python310\python.exe" set "PY=C:\Users\ALVE\AppData\Local\Programs\Python\Python310\python.exe"

REM 2) py 启动器（能 import PyQt5 时采用）
if not defined PY (
    py -3 -c "import PyQt5" >nul 2>&1 && set "PY=py -3"
)

REM 3) PATH 中的 python（能 import PyQt5 时采用）
if not defined PY (
    python -c "import PyQt5" >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo [错误] 未找到已安装 PyQt5 等依赖的 Python 环境。
    echo        请先双击 install.bat 安装依赖，再运行本启动器。
    echo.
    pause
    exit /b 1
)

echo 正在启动 已知行星可视化 ...
%PY% main.py

if errorlevel 1 (
    echo.
    echo [启动失败] 请把上方报错信息截图反馈。
    pause
)
