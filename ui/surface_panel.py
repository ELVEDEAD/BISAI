"""
surface_panel.py —— 地表视角（第一人称全景）

把「站在某颗行星/卫星表面、某时刻向四周望去」的景象画成一张全景图：
    * 天空底色由太阳高度角决定（白昼蔚蓝 → 晨昏橙红 → 夜晚深蓝近黑）
    * 背景亮星按视星等画成柔和的模糊光晕点（近地平处因大气消光变暗，白昼隐没）
    * 太阳 / 月球按真实视直径画成圆盘，行星与矮行星按亮度画成光点
    * 地平线以下为静态地形剪影：不逐帧渲染，仅在切换天体/经纬度时按种子生成一次
      （对应用户要求：地形只需「在那一时段、那一小块区域」渲染，不要求实时）

几何与物理全部由 core/surface.py 给出：
    观测点局部地平系（天顶/北向/东向）由天体自转轴 + 自转周期 + 表面经纬度确定，
    目标方向 = 目标位置 − 观测点位置，再投影为高度角 / 方位角。
亮度用标准视星等公式（以太阳 1 AU 处 −26.74 为基准），不做任何「看起来更亮」的
人为放大。

科学诚实性
----------
* 地球自转相位取 GMST，与「地面视角」标签页自洽；其他天体本初子午线角常数项未收录，
  取可复现假设 W(J2000)=0（只影响经度零点，不影响星空相对运动）；
* 未建模大气折射、光行差、行星相位（月相/金星位相一律按整圆盘示意）；
* 地形剪影为程序化示意，非实测地形，不代表该天体真实地貌。
"""
import math
import random
import zlib

from datetime import datetime, timedelta

from PyQt5.QtCore import Qt, QDate, QTime, QPointF
from PyQt5.QtGui import (QPainter, QColor, QRadialGradient, QLinearGradient,
                         QPen, QBrush, QFont, QPolygonF)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QDateEdit,
                             QTimeEdit, QCheckBox, QScrollArea, QFileDialog,
                             QFrame, QDoubleSpinBox)

from core import surface as S
from core import observer as O
from core.time_system import datetime_to_jd
from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT
from ui.widgets import make_searchable, resolve_combo_text

# 视野（水平视场角，度）
FOV_CHOICES = [("60°（望远）", 60.0), ("90°（标准）", 90.0),
               ("120°（广角）", 120.0), ("180°（超广角）", 180.0)]

# 天空底色关键帧：(太阳高度角°, 天顶色, 地平色)
_SKY_ANCHORS = [
    (-18.0, (5, 7, 16), (16, 20, 34)),
    (-6.0, (18, 26, 48), (90, 60, 60)),
    (0.0, (40, 60, 95), (205, 140, 90)),
    (10.0, (58, 102, 158), (150, 183, 220)),
]

# 地形风格 → (振幅°, 地表色)
_TERRAIN_STYLE = {
    "hills": (3.0, (34, 38, 28)),
    "craters": (2.2, (44, 42, 40)),
    "dunes": (1.6, (60, 46, 32)),
    "clouds": (0.5, (58, 62, 70)),
}
_DEFAULT_TERRAIN = (2.4, (40, 40, 40))

_CARDINALS = [(0.0, "N"), (45.0, "NE"), (90.0, "E"), (135.0, "SE"),
              (180.0, "S"), (225.0, "SW"), (270.0, "W"), (315.0, "NW")]


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _sky_colors(sun_alt):
    """由太阳高度角给出 (天顶色, 地平色)（0–255）"""
    if sun_alt is None:
        sun_alt = -30.0
    if sun_alt <= _SKY_ANCHORS[0][0]:
        return _SKY_ANCHORS[0][1], _SKY_ANCHORS[0][2]
    if sun_alt >= _SKY_ANCHORS[-1][0]:
        return _SKY_ANCHORS[-1][1], _SKY_ANCHORS[-1][2]
    for i in range(len(_SKY_ANCHORS) - 1):
        a0, a1 = _SKY_ANCHORS[i], _SKY_ANCHORS[i + 1]
        if a0[0] <= sun_alt <= a1[0]:
            t = (sun_alt - a0[0]) / (a1[0] - a0[0])
            return _lerp3(a0[1], a1[1], t), _lerp3(a0[2], a1[2], t)
    return _SKY_ANCHORS[-1][1], _SKY_ANCHORS[-1][2]


def _darkness(sun_alt) -> float:
    """夜空程度：白昼 0，天文夜 1（用于星空可见度）"""
    if sun_alt is None:
        return 1.0
    if sun_alt >= 0.0:
        return 0.0
    if sun_alt <= -12.0:
        return 1.0
    return -sun_alt / 12.0


def _qcolor(c, alpha=255):
    """天体颜色（0–1 或 0–255）→ QColor"""
    try:
        r, g, b = float(c[0]), float(c[1]), float(c[2])
    except (TypeError, ValueError, IndexError):
        r = g = b = 0.9
    if r <= 1.0 and g <= 1.0 and b <= 1.0:
        r, g, b = r * 255.0, g * 255.0, b * 255.0
    cl = lambda v: int(max(0.0, min(255.0, v)))
    return QColor(cl(r), cl(g), cl(b), alpha)


def _brightness(mag, limit=6.0, span=7.0) -> float:
    """视星等 → 0–1 亮度（越亮越接近 1；暗于 limit 归 0）"""
    if mag is None:
        return 0.0
    return max(0.0, min(1.0, (limit - float(mag)) / span))


def _terrain_params(style, seed):
    """静态地形剪影参数（正弦叠加，确定性、可复现）"""
    amp, color = _TERRAIN_STYLE.get(style, _DEFAULT_TERRAIN)
    rng = random.Random(int(seed) & 0x7FFFFFFF)
    comps = [(rng.uniform(0.2, 1.0), rng.uniform(1.0, 6.0), rng.uniform(0.0, 2 * math.pi))
             for _ in range(5)]
    return {"amp": amp, "color": color, "comps": comps}


def _terrain_alt(params, az_deg) -> float:
    """给定方位角处的地平线抬升角（度，恒为正的小量）"""
    th = math.radians(az_deg)
    s = sum(w * math.sin(f * th + ph) for w, f, ph in params["comps"])
    tot = sum(w for w, _f, _p in params["comps"]) or 1.0
    return params["amp"] * (0.5 + 0.5 * (s / tot) * 0.6)


class _PanoramaCanvas(QWidget):
    """全景画布：绘制天空/星空/地形/天体，支持拖拽环视与滚轮改视场"""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setMinimumHeight(300)
        self._drag = None

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        try:
            self.panel.paint_panorama(p, self.width(), self.height())
        except Exception as ex:                      # 绘制异常不崩溃
            p.fillRect(self.rect(), QColor(20, 20, 24))
            p.setPen(QColor(208, 138, 90))
            p.drawText(self.rect(), Qt.AlignCenter, f"绘制失败：{ex}")

    def mousePressEvent(self, ev):
        self._drag = ev.pos()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            dx = ev.x() - self._drag.x()
            dy = ev.y() - self._drag.y()
            self.panel.pan_by(dx, dy, self.width(), self.height())
            self._drag = ev.pos()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def wheelEvent(self, ev):
        self.panel.cycle_fov(1 if ev.angleDelta().y() > 0 else -1)


class SurfacePanel(QWidget):
    """地表视角面板（第一人称全景 + 观测读数）"""

    def __init__(self, viewport=None, bodies=None, stars=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.bodies = list(bodies or (getattr(viewport, "bodies", None) or []))
        self.stars = list(stars if stars is not None
                          else (getattr(viewport, "stars", None) or []))
        self.capable = S.surface_capable_bodies(self.bodies)
        self._dirty = True
        self._terrain_cache = {}
        self._az_center = 0.0
        self._alt_center = 12.0
        self._hfov = 120.0
        self._view = {"snapshot": [], "sun_alt": None, "az_center": 0.0,
                      "alt_center": 12.0, "hfov": 120.0, "terrain": None,
                      "selected_name": None, "body_name": "", "darkness": 1.0}
        self.setMinimumWidth(300)
        self._build_ui()
        self._sync_from_clock()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        head = QLabel("地表视角")
        head.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(15)}px; font-weight: bold;")
        layout.addWidget(head)

        sub = QLabel("站在选定星球表面向四周望去：天空底色随太阳高度变化，"
                     "亮星为柔和光晕，太阳/月球按视直径成盘，地平线为静态地形剪影")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel("天体:"), 0, 0)
        self.cmb_body = QComboBox()
        self.cmb_body.addItems([b.name for b in self.capable])
        make_searchable(self.cmb_body, "搜索星球…")
        self.cmb_body.lineEdit().returnPressed.connect(self._on_body_pick)
        self.cmb_body.activated.connect(self._on_body_pick)
        self.cmb_body.setToolTip(
            "选择要站上去的星球（行星 / 矮行星 / 天然卫星，可输入名称搜索）。\n"
            "仅列出具备自转轴数据、能定出地平坐标系的天体。")
        grid.addWidget(self.cmb_body, 0, 1)

        grid.addWidget(QLabel("地点:"), 1, 0)
        self.cmb_city = QComboBox()
        self.cmb_city.addItems([c[0] for c in O.CITIES])
        make_searchable(self.cmb_city, "搜索城市…")
        self.cmb_city.lineEdit().returnPressed.connect(self._on_city_pick)
        self.cmb_city.activated.connect(self._on_city_pick)
        self.cmb_city.setToolTip("仅地球可选：预设观测城市（决定经纬度与当地时刻）")
        grid.addWidget(self.cmb_city, 1, 1)

        grid.addWidget(QLabel("纬度:"), 2, 0)
        self.spin_lat = QDoubleSpinBox()
        self.spin_lat.setRange(-90.0, 90.0)
        self.spin_lat.setDecimals(1)
        self.spin_lat.setSuffix("°")
        self.spin_lat.setToolTip("观测点纬度：+ 北纬 / − 南纬，决定天极高度与星空倾斜")
        self.spin_lat.valueChanged.connect(self._on_coord_changed)
        grid.addWidget(self.spin_lat, 2, 1)

        grid.addWidget(QLabel("经度:"), 3, 0)
        self.spin_lon = QDoubleSpinBox()
        self.spin_lon.setRange(-180.0, 180.0)
        self.spin_lon.setDecimals(1)
        self.spin_lon.setSuffix("°")
        self.spin_lon.setToolTip("观测点经度：+ 东经 / − 西经，决定当地恒星时（星空转角）")
        self.spin_lon.valueChanged.connect(self._on_coord_changed)
        grid.addWidget(self.spin_lon, 3, 1)

        grid.addWidget(QLabel("日期:"), 4, 0)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDateRange(QDate(1800, 1, 1), QDate(2050, 12, 31))
        self.date_edit.dateChanged.connect(self._on_time_changed)
        grid.addWidget(self.date_edit, 4, 1)

        grid.addWidget(QLabel("时刻:"), 5, 0)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.timeChanged.connect(self._on_time_changed)
        grid.addWidget(self.time_edit, 5, 1)

        grid.addWidget(QLabel("视野:"), 6, 0)
        self.cmb_fov = QComboBox()
        for label, val in FOV_CHOICES:
            self.cmb_fov.addItem(label, val)
        self.cmb_fov.setCurrentIndex(2)
        self.cmb_fov.setToolTip("水平视场角（滚轮也可切换）；在画面上拖拽可环视四周")
        self.cmb_fov.currentIndexChanged.connect(self._on_fov_changed)
        grid.addWidget(self.cmb_fov, 6, 1)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.chk_follow = QCheckBox("跟随时间轴")
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip(
            "勾选后日期/时刻随主视口时间轴自动更新（推荐）；\n"
            "取消后可固定某时某地，独立于时间轴查看。")
        self.chk_follow.toggled.connect(self._on_follow_toggled)
        row.addWidget(self.chk_follow, 1)
        self.btn_now = QPushButton("此刻")
        self.btn_now.setToolTip("把日期/时刻设为时间轴当前时刻")
        self.btn_now.clicked.connect(self._sync_from_clock)
        row.addWidget(self.btn_now)
        self.chk_labels = QCheckBox("标签")
        self.chk_labels.setChecked(True)
        self.chk_labels.toggled.connect(lambda _on: self.canvas.update())
        row.addWidget(self.chk_labels)
        self.chk_grid = QCheckBox("网格")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(lambda _on: self.canvas.update())
        row.addWidget(self.chk_grid)
        layout.addLayout(row)

        self.canvas = _PanoramaCanvas(self)
        layout.addWidget(self.canvas, 3)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #252525;")
        layout.addWidget(line)

        self.tbl_host = QWidget()
        self.tbl_grid = QGridLayout(self.tbl_host)
        self.tbl_grid.setContentsMargins(2, 2, 2, 2)
        self.tbl_grid.setVerticalSpacing(3)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.tbl_host)
        area.setFrameShape(QFrame.NoFrame)
        area.setMinimumHeight(120)
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
            "说明：位置取自 JPL 近似星历（1800–2050）；地球自转相位取 GMST，"
            "其他天体本初子午线角取可复现假设值（只影响经度零点）。"
            "未建模大气折射与行星相位；地形剪影为程序化示意，非实测地貌。")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(10)}px;")
        layout.addWidget(self.lbl_note)

        self._on_body_pick()

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

    def set_body(self, body):
        """由详情面板按钮调用：切到该天体的地表视角（不支持则返回 False）"""
        if body is None:
            return False
        idx = self.cmb_body.findText(body.name)
        if idx < 0:
            return False
        self.cmb_body.setCurrentIndex(idx)
        self._on_body_pick()
        return True

    def refresh(self):
        self._dirty = False
        body = self._current_body()
        jd = self._local_jd()
        lat = self.spin_lat.value()
        lon = self.spin_lon.value()

        snap = S.surface_snapshot(body, jd, lat, lon, self.bodies, self.stars)
        sun_alt = S.sun_altitude(body, jd, lat, lon, self.bodies)
        style = S.SURFACE_PRESETS.get(body.name, ("", "hills"))[1]
        seed = (zlib.crc32(body.name.encode("utf-8")) * 7919
                + int(round(lat)) * 131 + int(round(lon)))
        key = (body.name, round(lat, 1), round(lon, 1))
        if key not in self._terrain_cache:
            self._terrain_cache[key] = _terrain_params(style, seed)
        sel = getattr(self.viewport, "selected_name", None)

        self._view = {
            "snapshot": snap,
            "sun_alt": sun_alt,
            "az_center": self._az_center,
            "alt_center": self._alt_center,
            "hfov": self._hfov,
            "terrain": self._terrain_cache[key],
            "selected_name": sel,
            "body_name": body.name,
            "darkness": _darkness(sun_alt),
        }
        self.canvas.update()
        self._fill_info(body, snap, sun_alt, lat, lon)

    # ---------- 交互 ----------
    def pan_by(self, dx, dy, w, h):
        if w <= 0 or h <= 0:
            return
        ppd = w / max(self._hfov, 1e-6)
        self._az_center = (self._az_center - dx / ppd) % 360.0
        self._alt_center = max(-25.0, min(75.0, self._alt_center + dy / ppd))
        self._view["az_center"] = self._az_center
        self._view["alt_center"] = self._alt_center
        self.canvas.update()

    def cycle_fov(self, step):
        idx = (self.cmb_fov.currentIndex() + (1 if step > 0 else -1)) % self.cmb_fov.count()
        self.cmb_fov.setCurrentIndex(idx)

    # ---------- 控件回调 ----------
    def _current_body(self):
        nm = resolve_combo_text(self.cmb_body)
        b = next((x for x in self.capable if x.name == nm), None)
        if b is None and self.capable:
            b = self.capable[0]
        return b

    def _on_body_pick(self):
        body = self._current_body()
        if body is None:
            return
        nm = resolve_combo_text(self.cmb_body)
        if self.cmb_body.currentText().strip() != nm:
            self.cmb_body.setEditText(nm)
        lat, lon = S.default_lat_lon(body)
        is_earth = (body.name == "地球")
        self.cmb_city.setEnabled(is_earth)
        for w in (self.spin_lat, self.spin_lon):
            w.blockSignals(True)
        self.spin_lat.setValue(lat)
        self.spin_lon.setValue(lon)
        for w in (self.spin_lat, self.spin_lon):
            w.blockSignals(False)
        if is_earth:
            idx = self.cmb_city.findText("上海", Qt.MatchFixedString)
            if idx >= 0:
                self.cmb_city.blockSignals(True)
                self.cmb_city.setCurrentIndex(idx)
                self.cmb_city.blockSignals(False)
        self.refresh()

    def _on_city_pick(self):
        nm = resolve_combo_text(self.cmb_city)
        if self.cmb_city.currentText().strip() != nm:
            self.cmb_city.setEditText(nm)
        city = next((c for c in O.CITIES if c[0] == nm), None)
        if city is None:
            return
        for w in (self.spin_lat, self.spin_lon):
            w.blockSignals(True)
        self.spin_lat.setValue(city[1])
        self.spin_lon.setValue(city[2])
        for w in (self.spin_lat, self.spin_lon):
            w.blockSignals(False)
        self.refresh()

    def _on_coord_changed(self, *_):
        self.refresh()

    def _on_time_changed(self, *_):
        if not self.chk_follow.isChecked():
            self.refresh()

    def _on_fov_changed(self):
        self._hfov = float(self.cmb_fov.currentData() or 120.0)
        self._view["hfov"] = self._hfov
        self.canvas.update()

    def _on_follow_toggled(self, on):
        self.date_edit.setEnabled(not on)
        self.time_edit.setEnabled(not on)
        if on:
            self._sync_from_clock()
        else:
            self.refresh()

    def _tz(self) -> float:
        """地球取所选城市时区；其他天体无时区概念，按 UTC 处理"""
        if self._current_body() is not None and self._current_body().name == "地球":
            nm = resolve_combo_text(self.cmb_city)
            city = next((c for c in O.CITIES if c[0] == nm), None)
            if city:
                return city[3]
        return 0.0

    def _sync_from_clock(self):
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
        dt = datetime.combine(self.date_edit.date().toPyDate(),
                              self.time_edit.time().toPyTime())
        return datetime_to_jd(dt) - self._tz() / 24.0

    def _clock_text(self, jd) -> str:
        dt = O.local_datetime(jd, self._tz()) + timedelta(seconds=30)
        return dt.strftime("%Y-%m-%d %H:%M")

    # ---------- 绘制 ----------
    def paint_panorama(self, p, w, h):
        v = self._view
        if w <= 0 or h <= 0:
            return
        hfov = max(v["hfov"], 1.0)
        ppd = w / hfov
        az_c = v["az_center"]
        alt_c = v["alt_center"]
        sun_alt = v["sun_alt"]
        dark = v["darkness"]

        top_c, hor_c = _sky_colors(sun_alt)
        horizon_y = h / 2.0 + alt_c * ppd

        def sx(az):
            d = ((az - az_c + 180.0) % 360.0) - 180.0
            return w / 2.0 + d * ppd

        def sy(alt):
            return h / 2.0 - (alt - alt_c) * ppd

        # 天空底色（地平线以上渐变；地平线以下被地形覆盖）
        grad = QLinearGradient(0, 0, 0, max(horizon_y, 1.0))
        grad.setColorAt(0.0, QColor(*[int(c) for c in top_c]))
        grad.setColorAt(1.0, QColor(*[int(c) for c in hor_c]))
        p.fillRect(self.canvas.rect(), QColor(*[int(c) for c in hor_c]))
        p.fillRect(0, 0, w, int(max(horizon_y, 1.0)), QBrush(grad))

        # 太阳在地平线附近时，于其方位叠加暖色辉光
        sun = next((o for o in v["snapshot"] if o["kind"] == "sun"), None)
        if sun is not None and sun["alt"] > -8.0:
            self._draw_sun_glow(p, sx(sun["az"]), sy(sun["alt"]), w, h, sun_alt)

        # 高度角网格
        if self.chk_grid.isChecked():
            self._draw_grid(p, w, h, sx, sy, ppd)

        # 背景亮星（柔和模糊光晕点）
        self._draw_stars(p, v, sx, sy, ppd, dark)

        # 静态地形剪影（地平线以下）
        self._draw_terrain(p, v, w, h, sx, sy, az_c, ppd, hor_c)

        # 太阳 / 月球 / 行星 / 矮行星
        self._draw_bodies(p, v, sx, sy, ppd, dark)

        # 方位标注与 HUD
        self._draw_cardinals(p, v, w, h, sx, horizon_y)
        self._draw_hud(p, v, w, h)

    # ---- 分步绘制 ----
    def _draw_sun_glow(self, p, x, y, w, h, sun_alt):
        strength = max(0.0, min(1.0, (sun_alt + 8.0) / 18.0))
        if strength <= 0.01:
            return
        R = max(w, h) * 0.9
        g = QRadialGradient(QPointF(x, y), R)
        warm = QColor(255, 190, 120)
        g.setColorAt(0.0, QColor(warm.red(), warm.green(), warm.blue(), int(120 * strength)))
        g.setColorAt(0.35, QColor(warm.red(), warm.green(), warm.blue(), int(45 * strength)))
        g.setColorAt(1.0, QColor(warm.red(), warm.green(), warm.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(x, y), R, R)

    def _draw_grid(self, p, w, h, sx, sy, ppd):
        pen = QPen(QColor(255, 255, 255, 26))
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for alt in (15.0, 30.0, 45.0, 60.0, 75.0):
            y = sy(alt)
            if 0.0 <= y <= h:
                p.drawLine(0, int(y), w, int(y))
                p.setPen(QPen(QColor(200, 200, 200, 60)))
                p.drawText(4, int(y) - 3, f"{int(alt)}°")
                p.setPen(pen)
        for az in range(0, 360, 30):
            x = sx(az)
            if 0.0 <= x <= w:
                p.drawLine(int(x), 0, int(x), h)

    def _draw_stars(self, p, v, sx, sy, ppd, dark):
        if dark <= 0.02:
            return
        p.setPen(Qt.NoPen)
        for o in v["snapshot"]:
            if o["kind"] != "star":
                continue
            if o["alt"] <= 0.0:
                continue
            b = _brightness(o["mag"], limit=5.5, span=6.5)
            if b <= 0.03:
                continue
            atm = min(1.0, o["alt"] / 12.0)          # 近地平大气消光
            alpha = b * dark * (0.25 + 0.75 * atm)
            if alpha <= 0.02:
                continue
            x, y = sx(o["az"]), sy(o["alt"])
            if x < -30 or x > self.canvas.width() + 30:
                continue
            col = _qcolor(o["color"])
            core = 1.0 + 2.4 * b
            glow = core * 4.2
            g = QRadialGradient(QPointF(x, y), glow)
            g.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(),
                                     int(235 * alpha)))
            g.setColorAt(0.35, QColor(col.red(), col.green(), col.blue(),
                                      int(90 * alpha)))
            g.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(x, y), glow, glow)

    def _draw_terrain(self, p, v, w, h, sx, sy, az_c, ppd, hor_c):
        params = v["terrain"]
        base = params["color"]
        poly = QPolygonF()
        x = -3.0
        step = 3.0
        while x <= w + 3.0:
            az = az_c + (x - w / 2.0) / ppd
            alt_t = _terrain_alt(params, az)
            poly.append(QPointF(x, sy(alt_t)))
            x += step
        poly.append(QPointF(w + 3.0, h + 3.0))
        poly.append(QPointF(-3.0, h + 3.0))
        grad = QLinearGradient(0, sy(0.0), 0, h)
        lite = (min(255, base[0] + 26), min(255, base[1] + 26), min(255, base[2] + 26))
        grad.setColorAt(0.0, QColor(*lite))
        grad.setColorAt(1.0, QColor(max(0, base[0] - 14), max(0, base[1] - 14),
                                    max(0, base[2] - 14)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPolygon(poly)
        # 地平雾线
        p.setPen(QPen(QColor(hor_c[0], hor_c[1], hor_c[2], 90), 1))
        p.drawLine(0, int(sy(0.0)), w, int(sy(0.0)))

    def _draw_bodies(self, p, v, sx, sy, ppd, dark):
        labels = self.chk_labels.isChecked()
        for o in v["snapshot"]:
            if o["kind"] == "star" or o["alt"] <= 0.0:
                continue
            x, y = sx(o["az"]), sy(o["alt"])
            if x < -60 or x > self.canvas.width() + 60:
                continue
            kind = o["kind"]
            col = _qcolor(o["color"])
            b = _brightness(o["mag"], limit=8.0, span=10.0)
            sel = (o["name"] == v["selected_name"])

            if kind == "sun":
                core = max(o["ang_diam"] * ppd / 2.0, 7.0)
                glow = core * 6.0
                self._blob(p, x, y, glow, QColor(255, 236, 190), 190)
                self._blob(p, x, y, core * 1.6, QColor(255, 245, 220), 230)
                p.setBrush(QColor(255, 252, 240))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, y), core, core)
            elif kind == "moon":
                core = max(o["ang_diam"] * ppd / 2.0, 4.0)
                self._blob(p, x, y, core * 3.0, QColor(220, 226, 235), int(150 * max(dark, 0.3)))
                p.setBrush(QColor(232, 236, 242))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, y), core, core)
            else:
                if b <= 0.02:
                    continue
                core = 1.6 + 3.4 * b
                self._blob(p, x, y, core * 3.6, col, int(170 * min(1.0, b + 0.3)))
                p.setBrush(col)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, y), core, core)

            if sel:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(ACCENT), 1.6))
                p.drawEllipse(QPointF(x, y), core + 5.0, core + 5.0)

            if labels or sel:
                p.setPen(QColor(ACCENT) if sel else QColor(225, 225, 225))
                f = QFont("Microsoft YaHei UI", style.fs(8))
                f.setBold(sel)
                p.setFont(f)
                p.drawText(QPointF(x + 7.0, y - 6.0), o["name"])

    def _blob(self, p, x, y, R, color, alpha):
        if R <= 0.5:
            return
        g = QRadialGradient(QPointF(x, y), R)
        g.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), int(alpha)))
        g.setColorAt(0.4, QColor(color.red(), color.green(), color.blue(),
                                 int(alpha * 0.35)))
        g.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(x, y), R, R)

    def _draw_cardinals(self, p, v, w, h, sx, horizon_y):
        p.setFont(QFont("Microsoft YaHei UI", style.fs(8)))
        for az, name in _CARDINALS:
            x = sx(az)
            if x < 8 or x > w - 8:
                continue
            main = len(name) == 1
            p.setPen(QColor(235, 235, 235, 200) if main else QColor(190, 190, 190, 150))
            p.drawText(QPointF(x - 6.0, horizon_y - 6.0), name)

    def _draw_hud(self, p, v, w, h):
        p.setFont(QFont("Microsoft YaHei UI", style.fs(9)))
        p.setPen(QColor(235, 235, 235, 220))
        p.drawText(8, 18, f"{v['body_name']} 地表　{v['az_center']:.0f}° / "
                          f"{v['alt_center']:+.0f}°　视场 {v['hfov']:.0f}°")
        sa = v["sun_alt"]
        if sa is None:
            txt = "太阳高度：未知"
        else:
            txt = f"太阳高度：{sa:+.1f}°"
        p.setPen(QColor(200, 200, 200, 200))
        p.drawText(8, 34, txt)

    # ---------- 读数表 ----------
    def _fill_info(self, body, snap, sun_alt, lat, lon):
        while self.tbl_grid.count():
            item = self.tbl_grid.takeAt(0)
            wdg = item.widget()
            if wdg:
                wdg.deleteLater()

        above = [o for o in snap if o["alt"] > 0.0]
        rows = []
        if sun_alt is None:
            rows.append(("太阳高度角", "未知（缺该天体自转数据）"))
        else:
            state = ("白昼" if sun_alt > 0 else
                     ("暮光" if sun_alt > -6 else
                      ("天文暮光" if sun_alt > -18 else "夜晚")))
            rows.append(("太阳高度角", f"{sun_alt:+.2f}°（{state}）"))
        rows.append(("地平上方天体", f"{len(above)} 个（含背景亮星）"))
        rows.append(("观测点", f"{lat:+.2f}°, {lon:+.2f}°　当地 {self._clock_text(self._local_jd())}"))

        bright = [o for o in above if o["kind"] != "star"][:6]
        if bright:
            for o in bright:
                rows.append((o["name"], f"高度 {o['alt']:+.1f}°　方位 {o['az']:.1f}°　"
                                        f"视星等 {o['mag']:+.2f}"))
        else:
            rows.append(("地平上方", "此刻地平线以上没有行星/太阳"))

        star_up = [o for o in above if o["kind"] == "star"]
        if star_up:
            top = star_up[0]
            rows.append(("最亮背景星", f"{top['name']}（视星等 {top['mag']:+.2f}，"
                                       f"高度 {top['alt']:+.1f}°）"))

        for i, (k, val) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
            vl = QLabel(str(val))
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(11)}px;")
            self.tbl_grid.addWidget(kl, i, 0, Qt.AlignTop)
            self.tbl_grid.addWidget(vl, i, 1, Qt.AlignTop)
        self.tbl_grid.setColumnStretch(1, 1)

        self.lbl_status.setText(f"{body.name} 地表　地平线上方天体 {len(above)} 个")

    # ---------- 导出 ----------
    def _export_png(self):
        body = self._current_body()
        dt = O.local_datetime(self._local_jd(), self._tz())
        default = f"地表视角_{body.name if body else '未知'}_{dt.strftime('%Y%m%d_%H%M')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "导出地表视角", default,
                                              "PNG 图片 (*.png)")
        if path:
            self.canvas.grab().save(path, "PNG")