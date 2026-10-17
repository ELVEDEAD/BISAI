"""
sky_panel.py —— 观测者地面视角（星空图）

把「站在某地、某时刻抬头看到的天空」画成一张俯视天球图：
    * 方位角绕圈（正北在上，正东在左，符合抬头看天的习惯）
    * 天顶在圆心，地平在圆周边
    * 太阳视运动轨迹（当日日轨线）与当前太阳位置
    * 各行星、矮行星与背景亮星的地平坐标

下方给出当日太阳事件（日出/日落/中天/昼长 + 三档暮光），极昼极夜单独标注。

位置由 core/observer.py 解析计算：赤道坐标 (RA/Dec) 经当地恒星时转到地平坐标。
科学诚实性：行星位置取自 JPL 近似星历（1800–2050），高度角误差约 arcmin 级；
未逐点建模大气折射，日出/日落采用标准折射修正 −0.833°；天然卫星相位为假设值，
位置无预测意义，故不参与绘制。
"""
import numpy as np

from datetime import datetime, timedelta

from PyQt5.QtCore import Qt, QDate, QTime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QDateEdit,
                             QTimeEdit, QCheckBox, QScrollArea, QFileDialog,
                             QFrame)
from ui.mpl_backend import FigureCanvasQTAgg, Figure

from core import observer as O
from core.time_system import datetime_to_jd
from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT
from ui.widgets import make_searchable, resolve_combo_text

MPL_BG = "#252526"
MPL_AX = "#1b1b1b"
MPL_GRID = "#3a3a3a"

# 天体类别 → 绘制半径（pt）
_MARK_SIZE = {"sun": 11.0, "planet_solar": 6.0, "dwarf": 4.5, "star": 3.0}


class SkyPanel(QWidget):
    """观测者地面视角面板（星空图 + 当日太阳事件）"""

    def __init__(self, viewport=None, bodies=None, stars=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.bodies = list(bodies or (getattr(viewport, "bodies", None) or []))
        self.stars = list(stars if stars is not None
                          else (getattr(viewport, "stars", None) or []))
        self._dirty = True
        self.setMinimumWidth(300)
        self._build_ui()
        self._sync_from_clock()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        head = QLabel("地面视角")
        head.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(15)}px; font-weight: bold;")
        layout.addWidget(head)

        sub = QLabel("站在选定地点抬头看天：行星、太阳与亮星的地平坐标，"
                     "含当日日轨线与升落时刻")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel("地点:"), 0, 0)
        self.cmb_city = QComboBox()
        self.cmb_city.addItems([c[0] for c in O.CITIES])
        make_searchable(self.cmb_city, "搜索城市…")
        self.cmb_city.lineEdit().returnPressed.connect(self._on_city_pick)
        self.cmb_city.activated.connect(self._on_city_pick)
        self.cmb_city.setToolTip(
            "观测地点（预设城市，可输入名称搜索）。\n"
            "纬度决定星空朝向，经度决定当地恒星时；含赤道与极地样本。")
        grid.addWidget(self.cmb_city, 0, 1)

        grid.addWidget(QLabel("日期:"), 1, 0)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDateRange(QDate(1800, 1, 1), QDate(2050, 12, 31))
        self.date_edit.dateChanged.connect(self._on_time_changed)
        grid.addWidget(self.date_edit, 1, 1)

        grid.addWidget(QLabel("时刻:"), 2, 0)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.timeChanged.connect(self._on_time_changed)
        grid.addWidget(self.time_edit, 2, 1)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.chk_follow = QCheckBox("跟随时间轴")
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip(
            "勾选后日期/时刻随主视口时间轴自动更新（推荐）；\n"
            "取消后可固定某地某时的星空，独立于时间轴查看。")
        self.chk_follow.toggled.connect(self._on_follow_toggled)
        row.addWidget(self.chk_follow, 1)
        self.btn_now = QPushButton("此刻")
        self.btn_now.setToolTip("把日期/时刻设为时间轴当前时刻")
        self.btn_now.clicked.connect(self._sync_from_clock)
        row.addWidget(self.btn_now)
        layout.addLayout(row)

        # 星空图
        self.fig = Figure(figsize=(4, 4), dpi=100, facecolor=MPL_BG)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(280)
        layout.addWidget(self.canvas, 3)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #252525;")
        layout.addWidget(line)

        # 太阳事件表
        self.tbl_host = QWidget()
        self.tbl_grid = QGridLayout(self.tbl_host)
        self.tbl_grid.setContentsMargins(2, 2, 2, 2)
        self.tbl_grid.setVerticalSpacing(3)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.tbl_host)
        area.setFrameShape(QFrame.NoFrame)
        area.setMinimumHeight(110)
        layout.addWidget(area, 2)

        foot = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        foot.addWidget(self.lbl_status, 1)
        btn_png = QPushButton("导出 PNG")
        btn_png.clicked.connect(self._export_png)
        foot.addWidget(btn_png)
        layout.addLayout(foot)

        self.lbl_note = QLabel(
            "说明：位置取自 JPL 近似星历（1800–2050），高度角误差约 arcmin 级；"
            "未逐点建模大气折射，日出/日落采用 −0.833° 标准判据（含折射 34′ 与日面半径 16′）；"
            "天然卫星相位为假设值，位置无预测意义，故不绘制。")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(10)}px;")
        layout.addWidget(self.lbl_note)

    # ---------- 首次显示 ----------
    def showEvent(self, ev):
        super().showEvent(ev)
        if self._dirty:
            self.refresh()

    # ---------- 外部入口 ----------
    def tick(self):
        """由主窗口 UI 定时器调用：跟随时间轴时刷新"""
        if self.chk_follow.isChecked():
            self._sync_from_clock()

    def set_city(self, name: str):
        idx = self.cmb_city.findText(name, Qt.MatchFixedString)
        if idx >= 0:
            self.cmb_city.setCurrentIndex(idx)
            self.refresh()

    def refresh(self):
        self._dirty = False
        self._redraw()
        self._fill_events()

    # ---------- 地点/时间 ----------
    def _city(self):
        nm = resolve_combo_text(self.cmb_city)
        return next((c for c in O.CITIES if c[0] == nm), O.CITIES[0])

    def _tz(self) -> float:
        return self._city()[3]

    def _on_city_pick(self):
        nm = resolve_combo_text(self.cmb_city)
        if self.cmb_city.currentText().strip() != nm:
            self.cmb_city.setEditText(nm)
        self.refresh()

    def _on_time_changed(self, *_):
        if not self.chk_follow.isChecked():
            self.refresh()

    def _on_follow_toggled(self, on):
        self.date_edit.setEnabled(not on)
        self.time_edit.setEnabled(not on)
        if on:
            self._sync_from_clock()
        else:
            self.refresh()

    def _sync_from_clock(self):
        """从主视口时钟取当前时刻，换算到所选地点的当地日期/时刻"""
        vp = self.viewport
        jd = vp.clock.jd if (vp is not None and getattr(vp, "clock", None)) else None
        if jd is None:
            jd = datetime_to_jd(datetime.now())
        dt = O.local_datetime(jd, self._tz())
        self.date_edit.blockSignals(True)
        self.time_edit.blockSignals(True)
        self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
        self.time_edit.setTime(QTime(dt.hour, dt.minute))
        self.date_edit.blockSignals(False)
        self.time_edit.blockSignals(False)
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def _local_jd(self) -> float:
        """面板当前「当地日期 + 时刻」对应的 UTC 儒略日"""
        dt = datetime.combine(self.date_edit.date().toPyDate(),
                              self.time_edit.time().toPyTime())
        return datetime_to_jd(dt) - self._tz() / 24.0

    # ---------- 绘制星空图 ----------
    def _redraw(self):
        name, lat, lon, tz = self._city()
        jd = self._local_jd()
        self.fig.clear()
        ax = self.fig.add_subplot(111, projection="polar")
        try:
            self._plot_sky(ax, jd, lat, lon)
        except Exception as ex:                    # 数据异常 → 提示，不崩溃
            ax.clear()
            ax.text(0.5, 0.5, f"绘图失败：{ex}", ha="center", va="center",
                    color="#d08a5a", transform=ax.transAxes)
        self.fig.tight_layout(pad=0.6)
        self.canvas.draw_idle()
        self._status(name, lat, lon, tz, jd)

    def _plot_sky(self, ax, jd, lat, lon):
        # 俯视天球：正北在上、正东在左（抬头观星习惯）
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(1)
        ax.set_facecolor(MPL_AX)
        ax.set_ylim(0, 90)
        ax.set_yticks([0, 30, 60, 90])
        ax.set_yticklabels(["天顶", "60°", "30°", "地平"], fontsize=7,
                           color=TEXT_DIM)
        ax.set_xticks(np.deg2rad([0, 45, 90, 135, 180, 225, 270, 315]))
        ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                           fontsize=8, color=TEXT_DIM)
        ax.grid(True, color=MPL_GRID, lw=0.5, alpha=0.7)
        ax.spines["polar"].set_color(MPL_GRID)

        # 日轨线（整日太阳视运动）
        noon_utc = O.utc_jd_of_local_noon(jd, self._tz())
        az, alt = O.sun_path(noon_utc, lat, lon, self.bodies)
        if az is not None:
            r = np.where(alt >= 0.0, 90.0 - alt, np.nan)
            ax.plot(np.deg2rad(az), r, color="#e8b04b", lw=1.4, alpha=0.85,
                    label="太阳日轨", zorder=2)

        # 当前天体的地平坐标
        snap = O.sky_snapshot(jd, lat, lon, self.bodies, self.stars)
        sel = getattr(self.viewport, "selected_name", None)
        n_above = 0
        k = 0
        for o in snap:
            if o["alt"] < 0.0:
                continue
            n_above += 1
            r = 90.0 - o["alt"]
            th = np.deg2rad(o["az"])
            color = o.get("color") or "#dddddd"
            if isinstance(color, (list, tuple)):
                color = tuple(float(c) for c in color)
            ms = _MARK_SIZE.get(o["kind"], 3.0)
            if o["kind"] == "star":
                ms = max(1.8, min(4.5, float(o.get("size", 3.0)) * 0.7))
            hl = o["name"] == sel
            ax.plot([th], [r], marker="o", ms=ms * (1.6 if hl else 1.0),
                    color=color, mec="#ffffff" if hl else "#111111",
                    mew=1.4 if hl else 0.5, zorder=5 if hl else 4)
            if o["kind"] != "star" or hl:
                # 交错上下偏移，缓解密集区标签重叠
                dy = 8 if (k % 2 == 0) else -13
                ax.annotate(o["name"], (th, r), textcoords="offset points",
                            xytext=(0, dy), ha="center", fontsize=7,
                            color=ACCENT if hl else TEXT_MAIN, zorder=6)
                k += 1

        ax.set_title(f"{self._city()[0]}　当地 {self._clock_text(jd)}",
                     color=TEXT_MAIN, fontsize=10, pad=12)
        if n_above <= 1:
            ax.text(0.5, 0.02, "（此刻地平线上方天体很少，可切换时刻查看）",
                    ha="center", fontsize=7, color=TEXT_DIM,
                    transform=ax.transAxes)

    def _clock_text(self, jd) -> str:
        dt = O.local_datetime(jd, self._tz()) + timedelta(seconds=30)
        return dt.strftime("%Y-%m-%d %H:%M")

    # ---------- 太阳事件表 ----------
    def _fill_events(self):
        while self.tbl_grid.count():
            item = self.tbl_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        name, lat, lon, tz = self._city()
        jd = self._local_jd()
        noon_utc = O.utc_jd_of_local_noon(jd, tz)
        ev = O.sun_events(noon_utc, lat, lon, self.bodies)

        rows = []
        if not ev:
            rows.append(("太阳事件", "数据不足，无法计算"))
        elif ev.get("polar_day"):
            rows.append(("极昼", "当日太阳始终在地平线上（无日出/日落）"))
            rows.append(("太阳中天", self._fmt_jd(ev.get("transit"), tz)))
            rows.append(("最大高度角", f"{ev.get('max_alt', float('nan')):+.1f}°"))
        elif ev.get("polar_night"):
            rows.append(("极夜", "当日太阳始终在地平线下方（无日出/日落）"))
            rows.append(("太阳中天", self._fmt_jd(ev.get("transit"), tz)))
            rows.append(("最大高度角", f"{ev.get('max_alt', float('nan')):+.1f}°"))
        else:
            rows.append(("日出", self._fmt_jd(ev.get("rise"), tz)))
            rows.append(("中天", self._fmt_jd(ev.get("transit"), tz)))
            rows.append(("日落", self._fmt_jd(ev.get("set"), tz)))
            rows.append(("昼长", f"{ev.get('day_hours', 0.0):.2f} 小时"))
            rows.append(("正午高度角", f"{ev.get('max_alt', float('nan')):+.1f}°"))
        for label, _lvl in O.TWILIGHT_LEVELS:
            pair = ev.get(label) if ev else None
            if pair and (pair[0] or pair[1]):
                rows.append((label, f"{self._fmt_jd(pair[0], tz)} ~ "
                                    f"{self._fmt_jd(pair[1], tz)}"))
            elif ev:
                rows.append((label, "无（太阳未降至该高度）"))

        rows.append(("观测点坐标", f"{lat:+.2f}°, {lon:+.2f}°　时区 UTC{tz:+.0f}"))

        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
            vl = QLabel(str(v))
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(11)}px;")
            self.tbl_grid.addWidget(kl, i, 0, Qt.AlignTop)
            self.tbl_grid.addWidget(vl, i, 1, Qt.AlignTop)
        self.tbl_grid.setColumnStretch(1, 1)

    def _fmt_jd(self, jd, tz) -> str:
        if jd is None:
            return "—"
        return (O.local_datetime(jd, tz) + timedelta(seconds=30)).strftime("%H:%M")

    def _status(self, name, lat, lon, tz, jd):
        snap = O.sky_snapshot(jd, lat, lon, self.bodies, self.stars)
        above = sum(1 for o in snap if o["alt"] >= 0.0)
        self.lbl_status.setText(f"{name}　地平线上方天体 {above} 个")

    # ---------- 导出 ----------
    def _export_png(self):
        name, _lat, _lon, _tz = self._city()
        dt = O.local_datetime(self._local_jd(), self._tz())
        default = f"星空图_{name}_{dt.strftime('%Y%m%d_%H%M')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "导出星空图", default,
                                              "PNG 图片 (*.png)")
        if path:
            self.fig.savefig(path, dpi=160, facecolor=MPL_BG)