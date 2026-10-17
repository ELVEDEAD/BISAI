"""
resource.py —— 资源目录解析（源码运行 / PyInstaller onedir 兼容）

统一提供 assets 资源的绝对路径，供启动画面背景、窗口图标等使用。
兼容三种运行形态：
    * 源码运行：项目根目录（ui/ 的上一级）下的 assets/
    * PyInstaller onedir：sys._MEIPASS（_internal 目录）下的 assets/
    * 其他打包形态兜底：exe 同级 assets/
"""
import os
import sys


def resource_dir() -> str:
    """资源根目录（其下应有 assets/ 子目录）。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, "frozen", False):
            base = os.path.dirname(os.path.abspath(sys.executable))
    return base


def asset_path(*parts) -> str:
    """assets 下的资源绝对路径，如 asset_path("app.ico")。"""
    return os.path.join(resource_dir(), "assets", *parts)


def icon_path() -> str:
    """软件图标（橙红色带环行星）绝对路径。"""
    return asset_path("app.ico")