"""
mpl_backend.py —— matplotlib 统一懒加载入口

所有需要 matplotlib 的 UI 面板一律从本模块导入符号（FigureCanvasQTAgg、
Figure、rcParams、mdates 等），由这里在首次访问时统一完成：

    * 选定 Qt5Agg 后端（必须在任何绘图后端使用之前）
    * 中文字体 + 负号显示的全局 rcParams（原 6 个面板文件各配一遍）
    * 真正触发 matplotlib 导入（约 1s，移出启动关键路径）

启动优化策略：matplotlib 面板模块本身只在对应标签页首次打开（懒 tab）或
splash 后台预热时才被 import，因此 `import ui.mpl_backend` 本身几乎零开销，
matplotlib 的加载成本被推迟到启动画面之后。

用法（面板文件内）：
    from ui.mpl_backend import Figure, FigureCanvasQTAgg
"""
import importlib

_BACKEND_READY = False

# 惰性符号表：面板文件 `from ui.mpl_backend import X` 时按需解析并缓存
_EXPORTS = {
    "Figure": "matplotlib.figure:Figure",
    "FigureCanvasQTAgg": "matplotlib.backends.backend_qt5agg:FigureCanvasQTAgg",
    "NavigationToolbar2QT":
        "matplotlib.backends.backend_qt5agg:NavigationToolbar2QT",
    "rcParams": "matplotlib:rcParams",
    "mdates": "matplotlib.dates",
    "mticker": "matplotlib.ticker",
    "mpatches": "matplotlib.patches",
    "Circle": "matplotlib.patches:Circle",
    "date2num": "matplotlib.dates:date2num",
    "DateFormatter": "matplotlib.dates:DateFormatter",
}


def _ensure_backend():
    """首次调用时选定后端并配置全局 rcParams（幂等）。"""
    global _BACKEND_READY
    if _BACKEND_READY:
        return
    import matplotlib
    matplotlib.use("Qt5Agg")
    from matplotlib import rcParams
    rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    _BACKEND_READY = True


def warmup():
    """预加载 matplotlib 及 Qt 后端（供 splash 后台线程调用，加速首次绘图）。"""
    _ensure_backend()
    importlib.import_module("matplotlib.figure")
    importlib.import_module("matplotlib.backends.backend_qt5agg")
    importlib.import_module("matplotlib.patches")


def __getattr__(name):
    if name in _EXPORTS:
        _ensure_backend()
        spec = _EXPORTS[name]
        if ":" in spec:
            mod_path, attr = spec.split(":", 1)
            value = getattr(importlib.import_module(mod_path), attr)
        else:
            value = importlib.import_module(spec)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")