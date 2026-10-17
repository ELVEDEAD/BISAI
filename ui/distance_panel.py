"""
distance_panel.py —— 测距 / 光行时间工具（模块 N）

选择任意两个天体（太阳 / 行星 / 矮行星 / 天然卫星），实时显示：
    - 当前距离（AU / km / 光年，按量级自适应 + 三档同时给出）
    - 光行时间（光走完这段距离需要多久，从微秒到年自动换算）
    - 相对速度（km/s）
    - 两个天体的精度等级（科学诚实性）
可勾选“主视口连线”，在主视口 A/B 之间画一条青蓝色连线（随天体移动实时更新）。

读数与视口时间轴同步：拖动底部时间轴，距离与光行时间实时变化。
光行时间换算常数见 core/constants.py（c = 299792458 m/s，1 AU = 1.495978707e11 m）。
"""
import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QCheckBox, QFrame)

from core.constants import (format_distance, format_light_time, AU_KM, LY_AU,
                            PARSEC_AU, GRADE_DESCRIPTION)
from data.loader import BODY_TYPE_LABELS
from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT
from ui.widgets import make_searchable, resolve_combo_text

# 测距可选天体：太阳系内（含天然卫星）。系外行星在光年量级，单列意义不大。
MEASURE_TYPES = ("star", "planet_solar", "dwarf", "moon")


class DistancePanel(QWidget):
    """测距 / 光行时间面板（与主视口时间同步）"""

    def __init__(self, viewport=None, bodies=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.bodies = bodies or (getattr(viewport, "bodies", None) or [])
        self._items = [b for b in self.bodies if b.body_type in MEASURE_TYPES]
        self._body_a = None
        self._body_b = None
        self.setMinimumWidth(280)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(200)
        self._refresh()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("测距 / 光行时间")
        title.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(15)}px; font-weight: bold;")
        layout.addWidget(title)

        sub = QLabel("选择两个天体，实时显示距离与光传播所需时间")
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #252525;")
        layout.addWidget(line)

        pick = QGridLayout()
        pick.setHorizontalSpacing(6)
        pick.setVerticalSpacing(4)
        pick.addWidget(QLabel("天体 A:"), 0, 0)
        self.combo_a = QComboBox()
        self.combo_a.setMinimumWidth(120)
        self.combo_a.addItems([b.name for b in self._items])
        make_searchable(self.combo_a, "搜索天体 A…")
        pick.addWidget(self.combo_a, 0, 1)
        pick.addWidget(QLabel("天体 B:"), 1, 0)
        self.combo_b = QComboBox()
        self.combo_b.setMinimumWidth(120)
        self.combo_b.addItems([b.name for b in self._items])
        make_searchable(self.combo_b, "搜索天体 B…")
        pick.addWidget(self.combo_b, 1, 1)

        btn_swap = QPushButton("A ⇄ B")
        btn_swap.clicked.connect(self._swap)
        pick.addWidget(btn_swap, 0, 2, 1, 1)
        btn_a = QPushButton("选中→A")
        btn_a.setToolTip("把主视口当前选中的天体设为 A")
        btn_a.clicked.connect(lambda: self._use_selected("a"))
        pick.addWidget(btn_a, 1, 2, 1, 1)

        btn_b = QPushButton("选中→B")
        btn_b.setToolTip("把主视口当前选中的天体设为 B")
        btn_b.clicked.connect(lambda: self._use_selected("b"))
        pick.addWidget(btn_b, 2, 2, 1, 1)

        self.chk_link = QCheckBox("主视口连线")
        self.chk_link.setToolTip("在主视口 A/B 两天体之间画一条青蓝色连线")
        self.chk_link.toggled.connect(self._sync_link)
        pick.addWidget(self.chk_link, 2, 0, 1, 2)

        layout.addLayout(pick)

        # 主要读数
        self.lbl_dist = QLabel("—")
        self.lbl_dist.setStyleSheet(
            f"color: {ACCENT}; font-size: {style.fs(20)}px; font-weight: bold;")
        layout.addWidget(self.lbl_dist)

        self.lbl_light = QLabel("光行时间 —")
        self.lbl_light.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(13)}px;")
        layout.addWidget(self.lbl_light)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: #252525;")
        layout.addWidget(line2)

        # 明细
        self.grid = QGridLayout()
        self.grid.setVerticalSpacing(3)
        layout.addLayout(self.grid)

        self.lbl_note = QLabel(
            "光行时间 = 距离 ÷ 光速（c = 299792458 m/s）。\n"
            "例如日地平均距离约 1 AU，光需约 8 分 19 秒。\n"
            "读数与底部时间轴同步：拖动时间轴即可看到距离随时间变化。")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(self.lbl_note)
        layout.addStretch()

    # ---------- 逻辑 ----------
    def _body_by_name(self, name):
        return next((b for b in self._items if b.name == name), None)

    def _swap(self):
        ia, ib = self.combo_a.currentIndex(), self.combo_b.currentIndex()
        self.combo_a.setCurrentIndex(ib)
        self.combo_b.setCurrentIndex(ia)
        self._refresh()

    def _use_selected(self, slot):
        vp = self.viewport
        name = getattr(vp, "selected_name", None) if vp else None
        if not name:
            return
        combo = self.combo_a if slot == "a" else self.combo_b
        idx = combo.findText(name)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self._refresh()

    def _sync_link(self, on):
        vp = self.viewport
        if vp is None:
            return
        if on and self._body_a and self._body_b:
            vp.set_measure_pair(self._body_a.name, self._body_b.name)
        else:
            vp.set_measure_pair(None, None)

    def _jd(self):
        vp = self.viewport
        if vp is not None and getattr(vp, "clock", None) is not None:
            return vp.clock.jd
        from core.constants import J2000_JD
        return J2000_JD

    def _refresh(self):
        a = self._body_by_name(resolve_combo_text(self.combo_a))
        b = self._body_by_name(resolve_combo_text(self.combo_b))
        if a is None or b is None or a is b:
            self.lbl_dist.setText("请选择两个不同的天体")
            self.lbl_light.setText("")
            self._clear_grid()
            return
        self._body_a, self._body_b = a, b

        jd = self._jd()
        pa = np.asarray(a.position_at_jd(jd), dtype=np.float64)
        pb = np.asarray(b.position_at_jd(jd), dtype=np.float64)
        d_au = float(np.linalg.norm(pa - pb))

        self.lbl_dist.setText(format_distance(d_au))
        self.lbl_light.setText(f"光行时间  {format_light_time(d_au)}")

        try:
            va = np.asarray(a.velocity_at_jd(jd), dtype=np.float64)
            vb = np.asarray(b.velocity_at_jd(jd), dtype=np.float64)
            vrel = float(np.linalg.norm(va - vb))
            v_txt = f"{vrel:,.3f} km/s"
        except Exception:
            v_txt = "未知"

        rows = [
            ("距离（AU）", f"{d_au:.6g} AU"),
            ("距离（km）", f"{d_au * AU_KM:,.0f} km"),
            ("距离（光年）", f"{d_au / LY_AU:.4g} 光年"),
            ("距离（秒差距）", f"{d_au / PARSEC_AU:.4g} pc"),
            ("相对速度", v_txt),
            ("A 精度等级", self._grade_text(a)),
            ("B 精度等级", self._grade_text(b)),
        ]
        self._fill_grid(rows)

        if self.chk_link.isChecked():
            self.viewport.set_measure_pair(a.name, b.name)

    def _grade_text(self, body):
        return f"{body.grade}（{BODY_TYPE_LABELS.get(body.body_type, body.body_type)}）"

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _fill_grid(self, rows):
        self._clear_grid()
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {TEXT_DIM};")
            vl = QLabel(str(v))
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setStyleSheet(f"color: {TEXT_MAIN};")
            vl.setWordWrap(True)
            self.grid.addWidget(kl, i, 0, Qt.AlignTop)
            self.grid.addWidget(vl, i, 1, Qt.AlignTop)
        self.grid.setColumnStretch(1, 1)
