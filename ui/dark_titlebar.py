"""
dark_titlebar.py —— Windows 原生标题栏深色化

软件界面为 Blender 风格深灰主题，而 Windows 默认标题栏是浅色（白底黑字），
视觉冲突明显。本模块通过 DWM（Desktop Window Manager）把原生标题栏切到
系统深色（接近 #202020），与软件主题协调。

* Windows 11 与 Win10 build 18985+ 用属性 20；更早的 Win10（17763+）用 19
* DWM 只提供深/浅开关，无法自定义任意颜色
* 非 Windows 平台或调用失败时静默跳过，不影响任何功能
* setWindowFlags() 会销毁并重建原生窗口，DWM 属性随之丢失——
  显示模式切换后须重新应用（ui/display_mode.apply_display_mode 已内置）
"""
import ctypes
from ctypes import byref, c_int


def apply_dark_titlebar(widget):
    """把窗口的原生标题栏切到深色（幂等，可在每次 showEvent 调用）。"""
    try:
        hwnd = int(widget.winId())
        value = c_int(1)
        for attr in (20, 19):
            r = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, byref(value), ctypes.sizeof(value))
            if r == 0:
                break
    except Exception:
        pass  # 非 Windows 或调用失败时静默跳过，不影响功能