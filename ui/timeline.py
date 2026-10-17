"""
timeline.py —— 底部时间轴控件（模块 I）

功能：
- 播放/暂停/倒放按钮
- 9 档倍速滑块（实时×1 ~ 100年/秒）
- 当前仿真日期显示 + 日期跳转（双模式：日历点选 / 手动输入微调）
- JPL 星历适用范围指示（1800–2050）
- 与 SimulationClock 双向绑定
"""
from datetime import datetime, date as _date

from PyQt5.QtCore import Qt, pyqtSignal, QDate
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
                             QSlider, QLabel, QLineEdit, QFrame,
                             QCalendarWidget, QSpinBox, QToolButton, QSizePolicy)

from core.time_system import SimulationClock, SPEED_STEPS, jd_to_datetime, datetime_to_jd
from data.solar_system import EPHEMERIS_VALID_YEARS
from ui import style
from core.i18n import tr


class Timeline(QWidget):
    """底部时间轴：播放控制 + 倍速 + 日期跳转"""
    dateChanged = pyqtSignal(float)   # jd 变化（跳转时发射）

    def __init__(self, clock: SimulationClock, parent=None):
        super().__init__(parent)
        self.clock = clock
        self.setFixedHeight(56)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 播放/暂停
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(36)
        self.btn_play.setToolTip(tr("播放 / 暂停（空格键）"))
        self.btn_play.clicked.connect(self._toggle_play)
        layout.addWidget(self.btn_play)

        # 倒放
        self.btn_reverse = QPushButton("◀◀")
        self.btn_reverse.setFixedWidth(36)
        self.btn_reverse.setToolTip(tr("倒放 / 正放切换"))
        self.btn_reverse.clicked.connect(self._toggle_reverse)
        layout.addWidget(self.btn_reverse)

        # 倍速滑块
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setMinimum(0)
        self.slider_speed.setMaximum(len(SPEED_STEPS) - 1)
        self.slider_speed.setValue(self.clock.speed_index)
        self.slider_speed.setFixedWidth(160)
        self.slider_speed.setToolTip(tr("时间倍速"))
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        layout.addWidget(self.slider_speed)

        self.lbl_speed = QLabel(SPEED_STEPS[self.clock.speed_index][0])
        self.lbl_speed.setFixedWidth(80)
        self.lbl_speed.setStyleSheet(f"color: {style.palette()['TEXT_DIM']};")
        layout.addWidget(self.lbl_speed)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {style.palette()['BORDER']};")
        layout.addWidget(sep)

        # 当前日期
        self.lbl_date = QLabel("")
        self.lbl_date.setStyleSheet(
            f"color: {style.palette()['TEXT_MAIN']}; font-size: {style.fs(13)}px; font-weight: bold;")
        self.lbl_date.setMinimumWidth(120)
        layout.addWidget(self.lbl_date)

        # 日期跳转（双模式：日历点选 + 手动输入微调）
        self._lbl_jump = QLabel(tr("跳转:"))
        layout.addWidget(self._lbl_jump)

        self.btn_calendar = QPushButton(tr("日历"))
        self.btn_calendar.setFixedWidth(48)
        self.btn_calendar.setToolTip(tr("点击弹出日历面板，选择目标日期"))
        self.btn_calendar.clicked.connect(self._toggle_calendar)
        layout.addWidget(self.btn_calendar)

        self.spn_year = QSpinBox()
        self.spn_year.setRange(1800, 2100)
        self.spn_year.setPrefix("")
        self.spn_year.setFixedWidth(62)
        self.spn_year.setToolTip(tr("年"))
        layout.addWidget(self.spn_year)
        layout.addWidget(QLabel("-"))
        self.spn_month = QSpinBox()
        self.spn_month.setRange(1, 12)
        self.spn_month.setFixedWidth(38)
        layout.addWidget(self.spn_month)
        layout.addWidget(QLabel("-"))
        self.spn_day = QSpinBox()
        self.spn_day.setRange(1, 31)
        self.spn_day.setFixedWidth(38)
        layout.addWidget(self.spn_day)

        self.btn_jump = QPushButton(tr("跳转"))
        self.btn_jump.setFixedWidth(48)
        self.btn_jump.clicked.connect(self._jump_from_spin)
        layout.addWidget(self.btn_jump)

        self.btn_today = QPushButton(tr("今天"))
        self.btn_today.setFixedWidth(48)
        self.btn_today.setToolTip(tr("跳转到当前真实日期"))
        self.btn_today.clicked.connect(self._jump_today)
        layout.addWidget(self.btn_today)

        # 日历弹出面板（默认隐藏）
        self._calendar_popup = None

        layout.addStretch()

        # 星历范围提示
        self.lbl_ephem = QLabel("")
        self.lbl_ephem.setStyleSheet(f"color: {style.palette()['TEXT_DIM']}; font-size: {style.fs(10)}px;")
        layout.addWidget(self.lbl_ephem)

    # ---------- 操作 ----------
    def _toggle_play(self):
        self.clock.toggle_play()
        self._refresh()

    def _toggle_reverse(self):
        self.clock.reverse()
        self._refresh()

    def _on_speed_changed(self, idx):
        self.clock.speed_index = idx
        self.lbl_speed.setText(
            ("-" if self.clock.direction < 0 else "") + SPEED_STEPS[idx][0])
        self._refresh_ephem()

    def _jump_from_spin(self):
        try:
            y = self.spn_year.value()
            m = self.spn_month.value()
            d = self.spn_day.value()
            dt = datetime(y, m, d)
            self.clock.jump_to_datetime(dt)
            self.dateChanged.emit(self.clock.jd)
            self._refresh()
        except ValueError:
            pass

    def _jump_to_date(self, dt):
        self.clock.jump_to_datetime(dt)
        self.dateChanged.emit(self.clock.jd)
        self._refresh()

    def _jump_today(self):
        self.clock.jump_to_datetime(datetime.now())
        self.dateChanged.emit(self.clock.jd)
        self._refresh()

    def _toggle_calendar(self):
        if self._calendar_popup is not None:
            self._calendar_popup.close()
            return
        cal = QCalendarWidget(self)
        cal.setWindowFlags(Qt.Popup)
        cal.setGridVisible(True)
        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        p = style.palette()
        cal.setStyleSheet(
            f"QCalendarWidget{{background:{p['BG_PANEL']};color:{p['TEXT_MAIN']};}}"
            f"QCalendarWidget QToolButton{{color:{p['TEXT_MAIN']};}}"
            f"QCalendarWidget QAbstractItemView{{selection-background-color:{p['ACCENT']};}}")
        now = self.clock.now_datetime()
        cal.setSelectedDate(QDate(now.year, now.month, now.day))
        cal.setMinimumDate(QDate(1800, 1, 1))
        cal.setMaximumDate(QDate(2100, 12, 31))
        pos = self.btn_calendar.mapToGlobal(
            self.btn_calendar.rect().bottomLeft())
        cal.move(pos)
        cal.clicked.connect(lambda qd: self._on_calendar_pick(qd))
        cal.aboutToHide.connect(self._close_calendar)
        self._calendar_popup = cal
        cal.show()

    def _on_calendar_pick(self, qd):
        dt = datetime(qd.year(), qd.month(), qd.day())
        self.spn_year.setValue(dt.year)
        self.spn_month.setValue(dt.month)
        self.spn_day.setValue(dt.day)
        self._jump_to_date(dt)
        self._close_calendar()

    def _close_calendar(self):
        if self._calendar_popup is not None:
            self._calendar_popup.deleteLater()
            self._calendar_popup = None

    # ---------- 刷新 ----------
    def _refresh(self):
        if self.clock.playing:
            self.btn_play.setText("▶")
            self.btn_play.setToolTip(tr("暂停（空格键）"))
        else:
            self.btn_play.setText("❚❚")
            self.btn_play.setToolTip(tr("播放（空格键）"))
        sign = "-" if self.clock.direction < 0 else ""
        self.lbl_speed.setText(sign + SPEED_STEPS[self.clock.speed_index][0])
        self.slider_speed.blockSignals(True)
        self.slider_speed.setValue(self.clock.speed_index)
        self.slider_speed.blockSignals(False)
        self._refresh_date()
        self._refresh_ephem()

    def _refresh_date(self):
        dt = self.clock.now_datetime()
        self.lbl_date.setText(dt.strftime("%Y-%m-%d"))
        if not self.spn_year.hasFocus():
            self.spn_year.blockSignals(True)
            self.spn_year.setValue(dt.year)
            self.spn_year.blockSignals(False)
        if not self.spn_month.hasFocus():
            self.spn_month.blockSignals(True)
            self.spn_month.setValue(dt.month)
            self.spn_month.blockSignals(False)
        if not self.spn_day.hasFocus():
            self.spn_day.blockSignals(True)
            self.spn_day.setValue(dt.day)
            self.spn_day.blockSignals(False)

    def _refresh_ephem(self):
        year = self.clock.now_datetime().year
        lo, hi = EPHEMERIS_VALID_YEARS
        p = style.palette()
        if year < lo or year > hi:
            self.lbl_ephem.setText(tr("⚠ 超出星历范围 ({lo}–{hi})").format(lo=lo, hi=hi))
            self.lbl_ephem.setStyleSheet(f"color: {p['ACCENT']}; font-size: {style.fs(10)}px;")
        else:
            self.lbl_ephem.setText(tr("星历范围: {lo}–{hi}").format(lo=lo, hi=hi))
            self.lbl_ephem.setStyleSheet(f"color: {p['TEXT_DIM']}; font-size: {style.fs(10)}px;")

    def tick(self):
        """由主窗口定时器调用：刷新日期显示（不重发信号）"""
        self._refresh_date()
        self._refresh_ephem()

    # ---------- 语言 / 主题 ----------
    def retranslate(self):
        """语言变化：重建本控件的文字与提示。"""
        self.btn_play.setToolTip(tr("播放 / 暂停（空格键）"))
        self.btn_reverse.setToolTip(tr("倒放 / 正放切换"))
        self.slider_speed.setToolTip(tr("时间倍速"))
        self._lbl_jump.setText(tr("跳转:"))
        self.btn_calendar.setText(tr("日历"))
        self.btn_calendar.setToolTip(tr("点击弹出日历面板，选择目标日期"))
        self.spn_year.setToolTip(tr("年"))
        self.btn_jump.setText(tr("跳转"))
        self.btn_today.setText(tr("今天"))
        self.btn_today.setToolTip(tr("跳转到当前真实日期"))
        self._refresh()

    def restyle(self):
        """主题变化：重建依赖调色板的内联样式。"""
        p = style.palette()
        self.lbl_speed.setStyleSheet(f"color: {p['TEXT_DIM']};")
        self.lbl_date.setStyleSheet(
            f"color: {p['TEXT_MAIN']}; font-size: {style.fs(13)}px; font-weight: bold;")
        self.lbl_ephem.setStyleSheet(f"color: {p['TEXT_DIM']}; font-size: {style.fs(10)}px;")
        self._refresh_ephem()