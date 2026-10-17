"""
display_mode.py —— 窗口显示模式公共应用器

设置面板的 5 档显示模式（窗口 / 无边框窗口 / 无边框全屏 / 独占全屏 /
最大化窗口）原先只在会话内即时生效，不持久化。本模块把应用逻辑从
ui/settings_dialog.py 提取为公共函数，供两处共用：

    * ui/settings_dialog.py —— 用户在设置里切换档位（即时生效 + 写配置）
    * ui/launcher.py —— 打开主窗口时按已保存档位启动（默认最大化窗口）

默认档位为「最大化窗口」：既占满屏幕，又保留标题栏的最小化/最大化/关闭
按钮（无边框/独占全屏会连标题栏一起隐藏，关闭入口随之丢失）。

注意：切换窗口状态时必须先 setWindowFlags(Qt.Window) 再 show*()，
否则从无边框状态切回时会残留 FramelessWindowHint。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QGuiApplication

from ui import dark_titlebar

# 合法档位（与 ui/settings_dialog.DISPLAY_MODES 的 key 一致）
MODES = ("windowed", "borderless_windowed", "borderless_fullscreen",
         "exclusive_fullscreen", "maximized")


def apply_display_mode(win, mode, monitor_index=None):
    """把窗口切到指定显示档位并前置；随后重应用深色标题栏。

    monitor_index 仅对无边框全屏有效：指定铺满哪块显示器（默认主屏）。
    """
    if win is None or mode not in MODES:
        return
    # 只有边框状态真正变化时才重建窗口（对可见窗口重复 setWindowFlags
    # 会触发原生窗口销毁重建，造成闪烁）
    want_frameless = mode in ("borderless_windowed", "borderless_fullscreen")
    has_frameless = bool(win.windowFlags() & Qt.FramelessWindowHint)
    if want_frameless != has_frameless:
        win.setWindowFlags((Qt.FramelessWindowHint | Qt.Window)
                           if want_frameless else Qt.Window)
    if mode == "windowed":
        win.showNormal()
    elif mode == "borderless_windowed":
        win.showNormal()
    elif mode == "borderless_fullscreen":
        scr = QGuiApplication.primaryScreen()
        if monitor_index is not None:
            screens = QGuiApplication.screens()
            idx = min(monitor_index, len(screens) - 1)
            scr = screens[idx]
        geo = scr.geometry()
        win.setGeometry(geo)
        win.show()
    elif mode == "exclusive_fullscreen":
        win.setWindowFlags(Qt.Window)
        win.showFullScreen()
    elif mode == "maximized":
        win.setWindowFlags(Qt.Window)
        win.showMaximized()
    win.activateWindow()
    win.raise_()
    # setWindowFlags 重建原生窗口后 DWM 深色标题栏属性丢失，重应用
    dark_titlebar.apply_dark_titlebar(win)