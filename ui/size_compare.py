"""
size_compare.py —— 天体尺寸对比工具（模块 M）

用户"搜索某个行星想看它多大"的直接满足：
并排展示真实直径比例的圆（选中天体 vs 地球 / 木星 / 太阳），
标注真实直径数值；比例悬殊时自动分图（各自比例尺，避免不可见）。
"""
import math
import numpy as np

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
                             QLabel, QPushButton)
from ui.mpl_backend import FigureCanvasQTAgg, Figure
from core.constants import R_EARTH_KM, R_JUPITER_KM, R_SUN_KM
from ui.style import TEXT_MAIN, TEXT_DIM
from ui.chart_fullscreen import ChartFullscreenDialog

MPL_BG = "#252526"
MPL_AX = "#2b2b2b"

REF_BODIES = [
    ("地球", R_EARTH_KM),
    ("木星", R_JUPITER_KM),
    ("太阳", R_SUN_KM),
]


class SizeCompareDialog(QDialog):
    """尺寸对比对话框"""

    def __init__(self, body, parent=None):
        super().__init__(parent)
        self.body = body
        self.setWindowTitle(f"尺寸对比 —— {body.name}")
        self.resize(760, 480)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("对比对象:"))
        self.combo = QComboBox()
        for name, _ in REF_BODIES:
            self.combo.addItem(name)
        self.combo.setCurrentIndex(0)
        self.combo.currentTextChanged.connect(self._redraw)
        top.addWidget(self.combo)
        top.addStretch()
        top.addWidget(QLabel("真实直径（km）以真实比例并排展示"))
        btn_fs = QPushButton("放大")
        btn_fs.setToolTip("全屏查看对比图（滚轮缩放、拖拽平移、Esc 退出）")
        btn_fs.clicked.connect(self._fullscreen)
        top.addWidget(btn_fs)
        layout.addLayout(top)

        self.fig = Figure(facecolor=MPL_BG)
        self.canvas = FigureCanvasQTAgg(self.fig)
        layout.addWidget(self.canvas, 1)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(f"color: {TEXT_MAIN};")
        layout.addWidget(self.lbl_info)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        self._redraw()

    def _fullscreen(self):
        dlg = ChartFullscreenDialog(self.fig, parent=self, title=f"尺寸对比 —— {self.body.name}（全屏）")
        dlg.exec_()
        self.canvas.draw_idle()

    def _redraw(self, *_):
        ref_name, ref_radius = REF_BODIES[self.combo.currentIndex()]
        r_self = self.body.radius_km
        self.fig.clear()
        if not r_self:
            ax = self.fig.add_subplot(111)
            ax.set_facecolor(MPL_AX)
            ax.text(0.5, 0.5, "该天体半径数据未知，无法对比",
                    ha="center", va="center", color=TEXT_DIM, fontsize=12)
            ax.set_axis_off()
            self.lbl_info.setText(f"{self.body.name}: 半径未知")
            self.canvas.draw_idle()
            return
        ratio = r_self / ref_radius
        if ratio > 40 or ratio < 1 / 40:
            # 比例悬殊：分两幅图（各自比例尺，避免小的不可见）
            ax1 = self.fig.add_subplot(121)
            ax2 = self.fig.add_subplot(122)
            self._draw_pair(ax1, self.body.name, r_self, 1.0, color="#4fa3d1")
            self._draw_pair(ax2, ref_name, ref_radius, 1.0, color="#e8b04b")
            ax1.set_title(f"{self.body.name}\n直径 {r_self * 2:,.0f} km",
                          color=TEXT_MAIN, fontsize=9)
            ax2.set_title(f"{ref_name}\n直径 {ref_radius * 2:,.0f} km",
                          color=TEXT_MAIN, fontsize=9)
            note = (f"比例悬殊（{max(ratio, 1 / ratio):.0f}:1），已分图展示（各自比例尺不同）；"
                    f"{self.body.name} 直径为 {ref_name} 的 {ratio:.4g} 倍")
        else:
            ax = self.fig.add_subplot(111)
            self._draw_side_by_side(ax, self.body.name, r_self, ref_name, ref_radius)
            note = f"{self.body.name} 直径 {r_self * 2:,.0f} km，为 {ref_name} 的 {ratio:.4g} 倍（同一比例尺）"
        self.lbl_info.setText(note)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _circle(self, ax, x, r_km, color):
        """按 km 半径画圆（x 中心，单位=km）"""
        import matplotlib.patches as mpatches
        c = mpatches.Circle((x, 0), r_km, color=color, alpha=0.85, ec="none")
        ax.add_patch(c)

    def _draw_pair(self, ax, name, r_km, scale, color):
        ax.set_facecolor(MPL_AX)
        self._circle(ax, 0, r_km, color)
        pad = r_km * 1.4
        ax.set_xlim(-pad, pad)
        ax.set_ylim(-pad, pad)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#404040")

    def _draw_side_by_side(self, ax, n1, r1, n2, r2):
        ax.set_facecolor(MPL_AX)
        gap = max(r1, r2) * 2.4
        self._circle(ax, -gap / 2, r1, "#4fa3d1")
        self._circle(ax, gap / 2, r2, "#e8b04b")
        pad = max(r1, r2) * 1.8
        ax.set_xlim(-gap / 2 - pad, gap / 2 + pad)
        ax.set_ylim(-pad, pad)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(-gap / 2, -max(r1, r2) * 1.25, f"{n1}\n直径 {r1 * 2:,.0f} km",
                ha="center", va="top", color=TEXT_MAIN, fontsize=9)
        ax.text(gap / 2, -max(r1, r2) * 1.25, f"{n2}\n直径 {r2 * 2:,.0f} km",
                ha="center", va="top", color=TEXT_MAIN, fontsize=9)
        for spine in ax.spines.values():
            spine.set_color("#404040")