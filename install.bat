@echo off
chcp 65001 >nul
title 已知行星可视化 - 安装脚本

echo ============================================
echo   已知行星可视化 - 一键安装
echo ============================================
echo.

REM 检测 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] 检测 Python 环境...
python --version
echo.

echo [2/4] 安装依赖库...
pip install PyQt5 numpy pandas matplotlib
if errorlevel 1 (
    echo [警告] 部分依赖可能安装失败，尝试继续...
)
echo.

echo [3/4] 验证数据文件...
if not exist "data\exoplanets_builtin.py" (
    echo [错误] 数据文件缺失，请确认源码完整
    pause
    exit /b 1
)
if not exist "data\solar_system.py" (
    echo [错误] 数据文件缺失，请确认源码完整
    pause
    exit /b 1
)
echo 内置数据文件验证通过
echo.

echo [4/4] 创建启动快捷方式...
echo @echo off > 启动行星可视化.bat
echo cd /d "%%~dp0" >> 启动行星可视化.bat
echo python main.py >> 启动行星可视化.bat
echo.

echo ============================================
echo   安装完成！
echo   双击 "启动行星可视化.bat" 即可运行
echo ============================================
pause