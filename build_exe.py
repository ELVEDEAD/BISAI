"""
build_exe.py —— PyInstaller 打包脚本

生成独立 Windows exe（--onedir 目录模式），包含所有源码、数据、依赖。
排除与运行无关的大型包（torch/tensorboard 等），避免依赖分析递归超限与体积膨胀。

启动优化（相对旧版 --onefile）：
    * onedir 免去每次启动解包整个程序到 %TEMP%（数百 MB、耗时数秒~十几秒），
      exe 双击后直接进入启动画面；
    * assets 打包进包内，启动画面可用背景图、窗口图标可加载 app.ico；
    * scipy / matplotlib 仍随包分发（按需懒加载，运行时才导入）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 与本软件运行无关、但会拖入巨大依赖树的模块（按需增删）
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "tensorboard", "tensorflow",
    "tkinter", "pytest", "IPython", "jupyter", "notebook", "PySide6",
    "PySide2", "PyQt6", "wx", "_ssl_ca_certs",
]


def build():
    # 依赖树较深（scipy/matplotlib），提高解释器递归上限防分析崩溃
    sys.setrecursionlimit(6000)
    import PyInstaller.__main__

    args = [
        "--onedir",
        "--windowed",
        "--name", "Astrarium",
        "--add-data", os.path.join("data", "*.py") + os.pathsep + "data",
        "--add-data", os.path.join("data", "exoplanets.csv") + os.pathsep + "data",
        "--add-data", os.path.join("data", "hipparcos.csv") + os.pathsep + "data",
        "--add-data", os.path.join("core", "*.py") + os.pathsep + "core",
        "--add-data", os.path.join("scene", "*.py") + os.pathsep + "scene",
        "--add-data", os.path.join("ui", "*.py") + os.pathsep + "ui",
        "--add-data", os.path.join("assets", "app.png") + os.pathsep + "assets",
        "--add-data", os.path.join("assets", "app.ico") + os.pathsep + "assets",

        "--hidden-import", "PyQt5.QtOpenGL",
        "--hidden-import", "PyQt5.QtWidgets",
        "--hidden-import", "matplotlib.backends.backend_qt5agg",
        "--hidden-import", "scipy.optimize",
        "--hidden-import", "scipy.signal",
        "--icon", os.path.join("assets", "app.ico"),
        "--noconfirm",
        "--clean",
        "main.py",
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]

    # 启动画面专用背景图（用户提供后自动随包分发；缺省用 app.png/渐变兜底）
    splash_png = os.path.join("assets", "splash.png")
    if os.path.isfile(splash_png):
        args += ["--add-data", splash_png + os.pathsep + "assets"]

    print("执行 PyInstaller 打包...")
    print(" ".join(args))
    PyInstaller.__main__.run(args)
    print("\n打包完成！程序目录在 dist/Astrarium/ 下（exe + _internal）")


if __name__ == "__main__":
    build()