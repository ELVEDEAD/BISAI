"""
style.py —— 界面主题（夜间 / 日间）与全局样式表

配色由单一强调色 + 中性灰阶构成，整体柔化：圆角、低对比边框、克制的强调色，
避免长时间观测时的视觉疲劳。

    * 夜间（默认）：深灰底、柔和橙强调（原配色归入此主题）
    * 日间：浅灰底、同一强调色系，用于明亮环境

切换主题：`apply_theme("day")` 会更新本模块的调色板常量并重建 `MAIN_QSS`，
同时通知已注册的监听者（各界面据此重建内联样式），实现即时生效。
"""

# ---------------------------------------------------------------- 调色板
NIGHT = {
    "BG_MAIN": "#1f2023",        # 主背景（深灰，非纯黑，降低夜间反差）
    "BG_PANEL": "#27282c",       # 面板 / 侧栏
    "BG_PANEL_LIGHT": "#34363b", # 更浅层（输入框 / hover）
    "ACCENT": "#e6913f",         # 强调色（柔和橙，仅选中 / 激活态）
    "ACCENT_BLUE": "#5a83c4",    # 备选科技蓝
    "TEXT_MAIN": "#dfe0e2",      # 主文字（略降亮度，减轻长时间观测疲劳）
    "TEXT_DIM": "#95999e",       # 次要文字
    "BORDER": "#35373d",         # 细边框
    "HOVER": "#3a3c42",          # hover 背景
    "HOVER_STRONG": "#43454b",   # 树 / 列表 hover
    "TOOLTIP_BG": "#2d2f34",     # 提示框背景
    "TOOLTIP_BORDER": "#4a4d54",
    "SHADOW": "#16171a",
}

DAY = {
    "BG_MAIN": "#f5f4ef",        # 主背景（暖调米白，避免纯白的刺眼感）
    "BG_PANEL": "#fbfaf6",       # 面板 / 侧栏（米白，非纯白）
    "BG_PANEL_LIGHT": "#eeede7", # 更浅层（输入框 / hover）
    "ACCENT": "#cf7d2a",         # 强调色（略降饱和，柔和）
    "ACCENT_BLUE": "#4a78b8",
    "TEXT_MAIN": "#33363b",      # 主文字（深灰，避免纯黑的高对比）
    "TEXT_DIM": "#6d7076",
    "BORDER": "#dcdad2",
    "HOVER": "#eae9e3",
    "HOVER_STRONG": "#e2e1da",
    "TOOLTIP_BG": "#fbfaf6",
    "TOOLTIP_BORDER": "#d3d1c9",
    "SHADOW": "#cdcbc3",
}

THEMES = {"night": NIGHT, "day": DAY}
THEME_KEYS = ["night", "day"]

# 主题名（中文原文，供 i18n.tr 翻译）
THEME_LABELS = {"night": "夜间", "day": "日间"}

_current_theme = "night"
_listeners = []

# ---------------------------------------------------------------- 字体缩放
# 界面字体缩放倍率：1.0 = 默认 12px。设置面板滑块可调 0.8 ~ 1.6。
# 所有 QSS 与内联样式中的字号都应通过 fs() 取整换算，方能随滑块同步缩放。
FONT_SCALE_MIN = 0.8
FONT_SCALE_MAX = 1.6
_font_scale = 1.0


def fs(px: float) -> int:
    """把基准像素字号按当前缩放倍率换算为实际像素（下限 8px）。"""
    return max(8, int(round(float(px) * _font_scale)))


def font_scale() -> float:
    return _font_scale


def apply_font_scale(scale: float):
    """设置界面字体缩放倍率并重建全局样式表、通知监听者重建内联样式。"""
    global _font_scale, MAIN_QSS
    try:
        scale = float(scale)
    except Exception:
        return
    scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
    if abs(scale - _font_scale) < 1e-6:
        return
    _font_scale = scale
    MAIN_QSS = build_qss(THEMES[_current_theme])
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            pass

# 模块级调色板常量（供既有代码 `from ui.style import BG_MAIN` 引用；
# apply_theme 会就地更新这些全局变量）
BG_MAIN = NIGHT["BG_MAIN"]
BG_PANEL = NIGHT["BG_PANEL"]
BG_PANEL_LIGHT = NIGHT["BG_PANEL_LIGHT"]
ACCENT = NIGHT["ACCENT"]
ACCENT_BLUE = NIGHT["ACCENT_BLUE"]
TEXT_MAIN = NIGHT["TEXT_MAIN"]
TEXT_DIM = NIGHT["TEXT_DIM"]
BORDER = NIGHT["BORDER"]
HOVER = NIGHT["HOVER"]
HOVER_STRONG = NIGHT["HOVER_STRONG"]
TOOLTIP_BG = NIGHT["TOOLTIP_BG"]
TOOLTIP_BORDER = NIGHT["TOOLTIP_BORDER"]
SHADOW = NIGHT["SHADOW"]


def palette() -> dict:
    """返回当前主题的调色板字典（供需要动态取色的界面使用）。"""
    return THEMES[_current_theme]


def current_theme() -> str:
    return _current_theme


def add_theme_listener(cb):
    if cb not in _listeners:
        _listeners.append(cb)


def remove_theme_listener(cb):
    if cb in _listeners:
        _listeners.remove(cb)


def apply_theme(name: str):
    """切换主题：更新调色板常量、重建 MAIN_QSS，并通知监听者。"""
    global _current_theme, MAIN_QSS
    if name not in THEMES or name == _current_theme:
        return
    _current_theme = name
    p = THEMES[name]
    globals().update(p)
    MAIN_QSS = build_qss(p)
    for cb in list(_listeners):
        try:
            cb()
        except Exception:
            pass


def build_qss(p: dict) -> str:
    """由调色板构建全局样式表。"""
    return f"""
QWidget {{
    background-color: {p['BG_PANEL']};
    color: {p['TEXT_MAIN']};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: {fs(12)}px;
}}
QMainWindow, QDialog {{
    background-color: {p['BG_MAIN']};
}}
QToolBar {{
    background-color: {p['BG_MAIN']};
    border: none;
    padding: 3px 6px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    color: {p['TEXT_MAIN']};
    padding: 3px 8px;
    border-radius: 4px;
}}
QToolBar QToolButton:hover {{
    background-color: {p['HOVER']};
}}
QMenuBar {{
    background-color: {p['BG_MAIN']};
    border-bottom: 1px solid {p['BORDER']};
}}
QMenu {{
    background-color: {p['BG_PANEL']};
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 18px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {p['ACCENT']};
    color: #ffffff;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
    background-color: {p['BG_PANEL_LIGHT']};
    border: 1px solid {p['BORDER']};
    border-radius: 5px;
    padding: 3px 8px;
    selection-background-color: {p['ACCENT']};
    selection-color: #ffffff;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 1px solid {p['ACCENT']};
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['BG_PANEL']};
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    selection-background-color: {p['ACCENT']};
    selection-color: #ffffff;
    outline: none;
}}
QPushButton {{
    background-color: {p['BG_PANEL_LIGHT']};
    border: 1px solid {p['BORDER']};
    border-radius: 5px;
    padding: 4px 12px;
}}
QPushButton:hover {{
    background-color: {p['HOVER']};
    border: 1px solid {p['TOOLTIP_BORDER']};
}}
QPushButton:pressed, QPushButton:checked {{
    background-color: {p['ACCENT']};
    color: #ffffff;
    border: 1px solid {p['ACCENT']};
}}
QTreeWidget, QListWidget, QTableWidget {{
    background-color: {p['BG_PANEL']};
    border: none;
    outline: none;
    alternate-background-color: {p['BG_PANEL_LIGHT']};
}}
QTreeWidget::item, QListWidget::item {{
    padding: 3px 4px;
    border-radius: 4px;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {p['ACCENT']};
    color: #ffffff;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {p['HOVER_STRONG']};
}}
QHeaderView::section {{
    background-color: {p['BG_PANEL_LIGHT']};
    border: none;
    padding: 4px;
}}
QSplitter::handle {{
    background-color: {p['BORDER']};
}}
QSplitter::handle:horizontal {{
    width: 6px;
}}
QSplitter::handle:vertical {{
    height: 6px;
}}
QSplitter::handle:hover {{
    background-color: {p['ACCENT']};
}}
QTabWidget::pane {{
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {p['BG_PANEL']};
    border: 1px solid {p['BORDER']};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 13px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {p['BG_PANEL_LIGHT']};
    border-bottom: 2px solid {p['ACCENT']};
}}
QTabBar::tab:hover {{
    background-color: {p['HOVER']};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {p['BG_PANEL_LIGHT']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p['TEXT_DIM']};
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: {p['ACCENT']};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['BG_PANEL_LIGHT']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['TOOLTIP_BORDER']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p['BG_PANEL_LIGHT']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QCheckBox, QRadioButton {{
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {p['TOOLTIP_BORDER']};
    border-radius: 4px;
    background: {p['BG_PANEL_LIGHT']};
}}
QCheckBox::indicator:checked {{
    background: {p['ACCENT']};
    border: 1px solid {p['ACCENT']};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1px solid {p['ACCENT']};
}}
QGroupBox {{
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {p['TEXT_DIM']};
}}
QToolTip {{
    background-color: {p['TOOLTIP_BG']};
    color: {p['TEXT_MAIN']};
    border: 1px solid {p['TOOLTIP_BORDER']};
    border-radius: 6px;
    padding: 6px 9px;
    font-size: {fs(12)}px;
    opacity: 245;
}}
QScrollArea {{
    border: none;
}}
QLabel#hudLabel {{
    color: {p['TEXT_DIM']};
    font-size: {fs(11)}px;
}}
"""


MAIN_QSS = build_qss(NIGHT)
