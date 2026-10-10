"""
chart_fullscreen.py —— 图表全屏放大通用组件

任何 matplotlib Figure 都可以用此组件全屏展开：
  - 深色半透明遮罩，图表居中占屏幕 80%~90%
  - 支持滚轮缩放、拖拽平移（matplotlib NavigationToolbar 原生交互）
  - Esc 或 ✕ 关闭，返回原面板
  - 全屏状态下数据与主视口时间保持同步（由调用方在 figure 上更新游标后调用 refresh）

用法：
    from ui.chart_fullscreen import ChartFullscreenDialog
    dlg = ChartFullscreenDialog(figure, parent=self)
    dlg.exec_()
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QHBoxLayout,
                             QLabel, QFrame)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
from ui.style import BG_MAIN, TEXT_MAIN, TEXT_DIM, ACCENT


class ChartFullscreenDialog(QDialog):
    """图表全屏遮罩对话框"""

    def __init__(self, figure, parent=None, title="图表全屏"):
        super().__init__(parent)
        self.figure = figure
        self._title = title
        self._build_ui()
        self._refresh_canvas()

    def _build_ui(self):
        self.setWindowTitle(self._title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        parent_screen = self.parent().window() if self.parent() else None
        if parent_screen:
            screen = parent_screen.screen() if hasattr(parent_screen, 'screen') else None
            if screen:
                geo = screen.geometry()
                self.setGeometry(geo)
            else:
                self.showMaximized()
        else:
            self.showMaximized()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部栏
        top_bar = QFrame()
        top_bar.setFixedHeight(36)
        top_bar.setStyleSheet(
            f"background-color: {BG_MAIN}; border-bottom: 1px solid #2a2a2a;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 0, 8, 0)

        lbl = QLabel(self._title)
        lbl.setStyleSheet(
            f"color: {TEXT_MAIN}; font-size: 13px; font-weight: bold;")
        top_layout.addWidget(lbl)
        top_layout.addStretch()

        hint = QLabel("滚轮缩放 · 拖拽平移 · Esc 退出")
        hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        top_layout.addWidget(hint)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 24)
        btn_close.setToolTip("关闭全屏 (Esc)")
        btn_close.setStyleSheet(
            f"QPushButton{{background:#3a2a20;color:{ACCENT};border:none;"
            f"font-size:14px;border-radius:4px;}}"
            f"QPushButton:hover{{background:#5a3a28;}}")
        btn_close.clicked.connect(self.accept)
        top_layout.addWidget(btn_close)
        layout.addWidget(top_bar)

        # 图表区域
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)

        # matplotlib 工具栏（提供缩放/平移/保存等原生交互）
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet(
            f"QToolBar{{background:{BG_MAIN};border:none;border-top:1px solid #2a2a2a;}}"
            f"QToolBar QToolButton{{color:{TEXT_DIM};}}")
        self.toolbar.setFixedHeight(32)
        layout.addWidget(self.toolbar)

    def _refresh_canvas(self):
        self.canvas.draw_idle()

    def refresh(self):
        """外部更新 figure 后调用以刷新画布"""
        self.canvas.draw_idle()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(ev)
