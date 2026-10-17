"""
phenomena_panel.py —— 天象推演面板

在指定日期区间内推演天文事件（冲日 / 合日 / 大距 / 方照 / 行星合相 / 凌日），
结果以表格列出，点击某一行可把主视口时间轴跳转到该事件时刻并聚焦相关天体。

事件由 core/phenomena.py 解析计算（地心视黄经 / 距角），可复现、无随机数。
受 JPL 近似星历精度限制（1800–2050），事件时刻误差约数分钟至数小时；
「凌日」几何敏感，标注为候选事件。
"""
from datetime import datetime, time

from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QDateEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QFrame, QApplication, QMessageBox)

from core import phenomena
from core.time_system import datetime_to_jd
from data.solar_system import EPHEMERIS_VALID_YEARS
from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT

# 观测点可选天体（行星 / 矮行星，默认地球）
OBSERVER_TYPES = ("planet_solar", "dwarf")
# 推演事件类型（顺序即下拉框顺序）
KIND_ORDER = (
    phenomena.KIND_OPPOSITION,
    phenomena.KIND_CONJUNCTION_SUN,
    phenomena.KIND_GREATEST_ELONGATION,
    phenomena.KIND_QUADRATURE,
    phenomena.KIND_CONJUNCTION_PAIR,
    phenomena.KIND_TRANSIT,
)


class PhenomenaPanel(QWidget):
    """天象推演面板（与主视口时间轴联动）"""
    jumpRequested = pyqtSignal(float, str)   # (jd, 需聚焦的天体名，可为空)

    def __init__(self, viewport=None, bodies=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.bodies = list(bodies or (getattr(viewport, "bodies", None) or []))
        self._events = []
        self.setMinimumWidth(300)
        self._build_ui()
        self._sync_kind()
        self._sync_range_to_clock()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("天象推演")
        title.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(15)}px; font-weight: bold;")
        layout.addWidget(title)

        sub = QLabel("在指定日期区间内推演行星天象，点击结果跳转到该时刻")
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #252525;")
        layout.addWidget(line)

        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        form.addWidget(QLabel("观测点:"), 0, 0)
        self.cmb_observer = QComboBox()
        self.cmb_observer.addItems(
            [b.name for b in self.bodies if b.body_type in OBSERVER_TYPES])
        idx = self.cmb_observer.findText(phenomena.OBSERVER_DEFAULT)
        self.cmb_observer.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_observer.setToolTip("计算观测点（默认地球，即地心视位置）")
        self.cmb_observer.currentIndexChanged.connect(self._sync_targets)
        form.addWidget(self.cmb_observer, 0, 1, 1, 2)

        form.addWidget(QLabel("天象类型:"), 1, 0)
        self.cmb_kind = QComboBox()
        for k in KIND_ORDER:
            self.cmb_kind.addItem(phenomena.KIND_LABELS[k], k)
        self.cmb_kind.currentIndexChanged.connect(self._sync_kind)
        form.addWidget(self.cmb_kind, 1, 1, 1, 2)

        form.addWidget(QLabel("目标天体:"), 2, 0)
        self.cmb_target = QComboBox()
        form.addWidget(self.cmb_target, 2, 1, 1, 2)

        self.lbl_pair = QLabel("第二目标:")
        self.cmb_target_b = QComboBox()
        form.addWidget(self.lbl_pair, 3, 0)
        form.addWidget(self.cmb_target_b, 3, 1, 1, 2)

        layout.addLayout(form)

        # 日期区间
        rng = QHBoxLayout()
        rng.setSpacing(4)
        rng.addWidget(QLabel("起:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        rng.addWidget(self.date_from)
        rng.addWidget(QLabel("止:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        rng.addWidget(self.date_to)
        layout.addLayout(rng)

        lo, hi = EPHEMERIS_VALID_YEARS
        self.date_from.setDateRange(QDate(lo, 1, 1), QDate(hi, 12, 31))
        self.date_to.setDateRange(QDate(lo, 1, 1), QDate(hi, 12, 31))

        quick = QHBoxLayout()
        quick.setSpacing(4)
        for _label, _years in (("未来 1 年", 1), ("未来 5 年", 5),
                               ("未来 10 年", 10)):
            btn = QPushButton(_label)
            btn.clicked.connect(lambda _c, y=_years: self._set_span(y))
            quick.addWidget(btn)
        btn_cur = QPushButton("回到当前")
        btn_cur.setToolTip("把起始日期设为时间轴当前日期")
        btn_cur.clicked.connect(self._sync_range_to_clock)
        quick.addWidget(btn_cur)
        layout.addLayout(quick)

        self.btn_run = QPushButton("开始推演")
        self.btn_run.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT}; color: #ffffff; "
            f"border: 1px solid {ACCENT}; padding: 5px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #f28f1f; }}")
        self.btn_run.clicked.connect(self._run)
        layout.addWidget(self.btn_run)

        # 结果表
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["日期时间", "类型", "事件", "详情"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.lbl_status = QLabel("选择类型与日期区间，点击「开始推演」")
        self.lbl_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(self.lbl_status)

        self.lbl_note = QLabel(
            "位置取自 JPL 近似星历（1800–2050），事件时刻误差约数分钟至数小时。\n"
            "「凌日」几何敏感，结果为候选事件，具体时刻与可见性需复核。\n"
            "天然卫星轨道相位为可复现假设值，故不推演卫星食/凌/掩。")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(10)}px;")
        layout.addWidget(self.lbl_note)

    # ---------- 下拉联动 ----------
    def _kind(self) -> str:
        return self.cmb_kind.currentData()

    def _observer(self) -> str:
        return self.cmb_observer.currentText()

    def _sync_kind(self):
        pair = phenomena.needs_pair(self._kind())
        self.lbl_pair.setVisible(pair)
        self.cmb_target_b.setVisible(pair)
        self._sync_targets()

    def _sync_targets(self):
        kind = self._kind()
        obs = self._observer()
        names = [n for n in phenomena.candidates(kind, self.bodies) if n != obs]
        self.cmb_target.clear()
        self.cmb_target.addItems(names)
        if phenomena.needs_pair(kind):
            self.cmb_target_b.clear()
            self.cmb_target_b.addItems(names)

    # ---------- 日期区间 ----------
    def _clock_jd(self):
        vp = self.viewport
        if vp is not None and getattr(vp, "clock", None) is not None:
            return vp.clock.jd
        from core.constants import J2000_JD
        return J2000_JD

    def _sync_range_to_clock(self):
        dt = datetime.now()
        vp = self.viewport
        if vp is not None and getattr(vp, "clock", None) is not None:
            dt = vp.clock.now_datetime()
        lo, hi = EPHEMERIS_VALID_YEARS
        y = min(max(dt.year, lo), hi)
        self.date_from.setDate(QDate(y, 1, 1))
        self.date_to.setDate(QDate(min(y + 5, hi), 12, 31))

    def _set_span(self, years: int):
        lo, hi = EPHEMERIS_VALID_YEARS
        start = self.date_from.date()
        y = min(start.year() + years, hi)
        self.date_to.setDate(QDate(y, start.month(), start.day()))
        if self.date_from.date().year() > hi:
            self.date_from.setDate(QDate(hi, 1, 1))

    def _range_jd(self):
        d0 = self.date_from.date().toPyDate()
        d1 = self.date_to.date().toPyDate()
        jd0 = datetime_to_jd(datetime.combine(d0, time.min))
        jd1 = datetime_to_jd(datetime.combine(d1, time.max))
        return jd0, jd1

    # ---------- 推演 ----------
    def _run(self):
        kind = self._kind()
        tgt = self.cmb_target.currentText() or None
        tgt_b = None
        if phenomena.needs_pair(kind):
            tgt_b = self.cmb_target_b.currentText() or None
        if phenomena.needs_pair(kind) and tgt and tgt == tgt_b:
            QMessageBox.information(self, "天象推演", "请选择两个不同的目标天体。")
            return
        jd0, jd1 = self._range_jd()
        if jd1 <= jd0:
            QMessageBox.information(self, "天象推演", "结束日期需晚于起始日期。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.btn_run.setEnabled(False)
        try:
            events = phenomena.search(kind, self.bodies, jd0, jd1,
                                      target=tgt, target_b=tgt_b,
                                      observer_name=self._observer())
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_run.setEnabled(True)

        self._events = events
        self._fill_table(events)
        if events:
            self.lbl_status.setText(
                f"共 {len(events)} 次事件（观测点：{self._observer()}）")
        else:
            self.lbl_status.setText(
                f"该区间内未推演出「{phenomena.KIND_LABELS.get(kind, kind)}」事件")

    def _fill_table(self, events):
        self.table.blockSignals(True)
        self.table.setRowCount(len(events))
        for r, ev in enumerate(events):
            cells = (ev.datetime_str, ev.kind_label, ev.label, ev.detail)
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setToolTip(ev.note or ev.label)
                if c == 0:
                    item.setForeground(Qt.white)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    def _on_row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        if r < 0 or r >= len(self._events):
            return
        ev = self._events[r]
        focus = ""
        obs = self._observer()
        for name in ev.bodies:
            if name != obs:
                focus = name
                break
        self.jumpRequested.emit(ev.jd, focus)