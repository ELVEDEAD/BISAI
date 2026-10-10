"""
build_exe.py —— PyInstaller 打包脚本

生成独立 Windows exe，包含所有源码、数据、依赖。
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "已知行星可视化",
        "--add-data", os.path.join("data", "*.py") + os.pathsep + "data",
        "--add-data", os.path.join("data", "exoplanets.csv") + os.pathsep + "data",
        "--add-data", os.path.join("data", "hipparcos.csv") + os.pathsep + "data",
        "--add-data", os.path.join("core", "*.py") + os.pathsep + "core",
        "--add-data", os.path.join("scene", "*.py") + os.pathsep + "scene",
        "--add-data", os.path.join("ui", "*.py") + os.pathsep + "ui",
        "--hidden-import", "PyQt5.QtOpenGL",
        "--hidden-import", "PyQt5.QtWidgets",
        "--hidden-import", "matplotlib.backends.backend_qt5agg",
        "--icon", os.path.join("assets", "app.ico"),
        "main.py",
    ]
    print("执行 PyInstaller 打包...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)
    print("\n打包完成！exe 文件在 dist/ 目录下")

if __name__ == "__main__":
    build()