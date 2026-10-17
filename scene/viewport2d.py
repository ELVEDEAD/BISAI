"""
viewport2d.py —— 二维平面视口（俯视黄道面的轨道图）

与三维视口（scene/viewport.py）并列的另一种主视图：
    * 俯视 J2000 黄道面，太阳在原点，天体位置投影到黄道面 (x, y)
    * 画出行星/矮行星轨道椭圆、太阳与各天体标记、天然卫星（拉近后）
    * 时间由共享的 SimulationClock 驱动，与三维视口用法一致
    * 鼠标：拖拽平移 / 滚轮缩放（对准光标）/ 单击选中 / 双击聚焦
    * 对外接口与三维视口保持同名，便于复用右侧各分析面板：
      clock / bodies / stars / selected_name / measure_names /
      focus_body_by_name / set_measure_pair / set_follow / bodySelected 信号

科学诚实性：坐标为开普勒二体近似的黄道面投影（忽略轨道倾角造成的 z 分量），
系外行星位于秒差距级距离，不在此太阳系平面视图内绘制。
"""
import math
import time as _time

import numpy as np
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QPolygonF,
                         QPainterPath, QImage)
from PyQt5.QtWidgets import QWidget

from core.constants import J2000_JD
from core.kepler import elements_to_position, solve_kepler
from core.time_system import SimulationClock
from ui import style
from ui.style import BG_MAIN, ACCENT, ACCENT_BLUE, TEXT_MAIN, TEXT_DIM

# 网格环半径阶梯（自适应：只画像素半径合适的环）
GRID_LADDER_AU = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                  1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 100.0)
MOON_ZOOM_PX_PER_AU = 4000.0    # 每 AU 像素数超过此值才画卫星及其轨道
HIT_PX = 12                     # 单击命中的像素半径
MIN_SCALE = 0.02                # 最远：1 AU 仅 0.02 px（约 3000 AU 视野）
MAX_SCALE = 200000.0            # 最近：1 AU 达 20 万 px（可看清卫星轨道）


def _c(color):
    """(r,g,b) 0–1 或 #hex → QColor"""
    if isinstance(color, str):
        return QColor(color)
    try:
        r, g, b = color
        return QColor(int(max(0.0, min(1.0, r)) * 255),
                      int(max(0.0, min(1.0, g)) * 255),
                      int(max(0.0, min(1.0, b)) * 255))
    except Exception:
        return QColor("#cccccc")


class Viewport2D(QWidget):
    """二维平面视口：俯视黄道面的轨道图"""

    bodySelected = pyqtSignal(object)
    followChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)

        self.clock = SimulationClock()
        self.bodies = []
        self.stars = []
        self.selected_name = None
        self.locked_name = None               # F键锁定
        self.measure_names = []
        self.compare_names = []

        # 显示开关（与三维视口同名，便于工具栏共用）
        self.show_orbits = True
        self.show_labels = True
        self.show_moons = True
        self.show_grid = True
        self.show_nebula = True              # 星云背景（预生成纹理，零运行时 CPU）
        self._nebula_tex = None              # QImage，构造时生成一次

        # 视图状态
        self._center = np.zeros(2)          # 视图中心（AU，黄道面 xy）
        self._scale = 10.0                  # 每 AU 像素数
        self._scale_ready = False
        self._follow_name = None

        # 交互
        self._drag = False
        self._drag_start = None
        self._moved = False

        # 数据缓存
        self._body_pos = None               # (n,3) 绝对黄道坐标
        self._xy = None                     # (n,2) 黄道面投影
        self._orbit = {}                    # {name: (N,2)} 轨道投影
        self._moon_orbit = {}               # {name: (N,2)} 相对母行星轨道投影
        self._index_of = {}
        self._solar_idx = []                # 参与二维绘制的太阳系天体索引

        # 按需渲染（省算力）：空闲降帧率重绘，交互/聚焦天体时恢复满帧。
        # 降帧只改重绘频率，仿真时间仍按真实 dt 推进，运动速度不变。
        self.on_demand = True
        self.render_fps_active = 60
        self.render_fps_idle = 15
        self.fps_limit = 90
        self._active_until = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self._last_tick = _time.perf_counter()

    # ---------- 数据 ----------
    def load_bodies(self, bodies, stars=None):
        self.bodies = list(bodies)
        if stars is not None:
            self.stars = list(stars)
        self._index_of = {b.name: i for i, b in enumerate(self.bodies)}
        self._build_cache()
        self.update()

    # ---------- 星云纹理（预生成，零运行时开销）----------
    def _gen_nebula_texture(self, w=512, h=256):
        """程序化生成星云纹理：多层值噪声 fBm + 银道面增强 + 三色混合。

        只在 _build_cache 时生成一次，后续绘制直接拉伸 blit，CPU 零开销。
        """
        rng = np.random.RandomState(42)

        def _vnoise(w, h, scale, rng):
            gw, gh = w // scale + 2, h // scale + 2
            grid = rng.rand(gw, gh).astype(np.float32)
            x = np.linspace(0, gw - 2, w)
            y = np.linspace(0, gh - 2, h)
            x0 = np.floor(x).astype(int); x1 = np.clip(x0 + 1, 0, gw - 1)
            y0 = np.floor(y).astype(int); y1 = np.clip(y0 + 1, 0, gh - 1)
            sx = x - x0; sy = y - y0
            sx = sx * sx * (3 - 2 * sx)     # smoothstep
            sy = sy * sy * (3 - 2 * sy)
            g = grid
            top = g[x0][:, y0] + (g[x1][:, y0] - g[x0][:, y0]) * sx[:, None]
            bot = g[x0][:, y1] + (g[x1][:, y1] - g[x0][:, y1]) * sx[:, None]
            return top + (bot - top) * sy[None, :]

        # 4 层八度 fBm
        noise = np.zeros((w, h), dtype=np.float32)
        amp = 0.5
        for s in [64, 32, 16, 8]:
            noise += amp * _vnoise(w, h, s, rng)
            amp *= 0.5

        # 银道面增强（中间水平带）
        y = np.linspace(-1, 1, h)
        gal = np.exp(-(y ** 2) * 5.0)
        noise += gal[None, :] * 0.3

        # 颜色分层（反射蓝紫 + 发射红粉 + 尘埃暗云）
        density = np.clip(noise, 0, 1.2) / 1.2
        density = np.power(density, 1.6)

        n2 = _vnoise(w, h, 24, rng)
        refl = np.clip((n2 - 0.22) / 0.26, 0.0, 1.0)       # 反射星云
        emit = np.clip((noise + n2 * 0.25 - 0.36) / 0.22, 0.0, 1.0)  # 发射星云
        dark = np.clip((0.55 - noise) / 0.25, 0.0, 1.0)            # 暗云

        r = density * (0.22 * refl + 0.55 * emit + 0.06 * dark) * 255
        g = density * (0.28 * refl + 0.18 * emit + 0.05 * dark) * 255
        b = density * (0.55 * refl + 0.28 * emit + 0.07 * dark) * 255
        a = density * 0.30 * 255

        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[:, :, 0] = np.clip(r, 0, 255).T
        rgba[:, :, 1] = np.clip(g, 0, 255).T
        rgba[:, :, 2] = np.clip(b, 0, 255).T
        rgba[:, :, 3] = np.clip(a, 0, 255).T

        self._nebula_tex = QImage(rgba.data, w, h, QImage.Format_RGBA8888).copy()

    def _build_cache(self):
        """预生成太阳系天体在黄道面上的轨道投影 + 星云背景纹理（只做一次）"""
        self._gen_nebula_texture()
        self._orbit.clear()
        self._moon_orbit.clear()
        self._solar_idx = []
        for i, b in enumerate(self.bodies):
            bt = b.body_type
            if bt in ("planet_solar", "dwarf", "etno"):
                self._solar_idx.append(i)
                pts = self._sample_planet_orbit(b)
                if pts is not None:
                    self._orbit[b.name] = pts
            elif bt == "moon":
                self._solar_idx.append(i)
                pts = self._sample_moon_orbit(b)
                if pts is not None:
                    self._moon_orbit[b.name] = pts
            elif bt == "star" and b.name == "太阳":
                self._solar_idx.append(i)

    def _sample_planet_orbit(self, body, n=256):
        el = body.elements
        if el is None:
            return None
        a, e, i = el.a, el.e, el.i
        omega = el.varpi - el.Omega
        out = np.empty((n, 2))
        for k in range(n):
            p = elements_to_position(a, e, i, el.Omega, omega, 2.0 * math.pi * k / n)
            out[k, 0] = p[0]
            out[k, 1] = p[1]
        return out

    def _sample_moon_orbit(self, body, n=128):
        if not body.a_au:
            return None
        e = body.e if body.e is not None else 0.0
        try:
            u, v = body._moon_plane_basis()
        except Exception:
            u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        out = np.empty((n, 2))
        for k in range(n):
            E = solve_kepler(2.0 * math.pi * k / n, e)
            xv = body.a_au * (math.cos(E) - e)
            yv = body.a_au * math.sqrt(max(1.0 - e * e, 0.0)) * math.sin(E)
            p = xv * u + yv * v
            out[k, 0] = p[0]
            out[k, 1] = p[1]
        return out

    def _update_positions(self):
        jd = self.clock.jd
        n = len(self.bodies)
        pos = np.zeros((n, 3))
        for i in self._solar_idx:
            try:
                pos[i] = self.bodies[i].position_at_jd(jd)
            except Exception:
                pos[i] = 0.0
        self._body_pos = pos
        self._xy = pos[:, :2]

    # ---------- 时钟 ----------
    def _tick(self):
        now = _time.perf_counter()
        # dt 上限 0.25s：空闲档最低约 15fps（dt≈0.067s），旧的 0.05s 上限会把
        # 仿真时间推进压成 0.75 倍速（天体运动变慢）
        dt = min(0.25, now - self._last_tick)
        self._last_tick = now
        self.clock.update(dt)
        self._update_positions()
        if self._follow_name and self._follow_name in self._index_of:
            i = self._index_of[self._follow_name]
            self._center = self._xy[i].copy()
        self._update_cadence(now)
        self.update()

    # ---------- 按需渲染（帧率调节） ----------
    def _mark_active(self, seconds: float = 3.0):
        """标记「正在交互/关注天体」，在该时间内保持满帧渲染"""
        if self.on_demand:
            self._active_until = max(self._active_until, _time.perf_counter() + seconds)

    def _update_cadence(self, now: float):
        if not self.on_demand:
            fps = self.render_fps_active
        else:
            busy = (now < self._active_until
                    or self._drag
                    or self._follow_name is not None)
            fps = self.render_fps_active if busy else self.render_fps_idle
        if self.fps_limit > 0:
            fps = min(fps, self.fps_limit)
        interval = max(1, int(round(1000.0 / max(1, fps))))
        if interval != self._timer.interval():
            self._timer.setInterval(interval)

    def set_on_demand(self, enabled: bool):
        """开关「按需渲染」；关闭即恢复持续满帧。"""
        self.on_demand = bool(enabled)
        if self.on_demand:
            self._mark_active(3.0)
        else:
            self._timer.setInterval(max(1, int(round(1000.0 / self.render_fps_active))))

    def set_fps_limit(self, fps: int):
        """设置帧率上限（0 = 无限制），即时生效。"""
        self.fps_limit = max(0, int(fps))
        self._update_cadence(_time.perf_counter())

    # ---------- 坐标变换 ----------
    def _to_screen(self, xy):
        w, h = self.width(), self.height()
        sx = w * 0.5 + (xy[0] - self._center[0]) * self._scale
        sy = h * 0.5 - (xy[1] - self._center[1]) * self._scale
        return sx, sy

    def _to_world(self, sx, sy):
        w, h = self.width(), self.height()
        return np.array([(sx - w * 0.5) / self._scale + self._center[0],
                         -(sy - h * 0.5) / self._scale + self._center[1]])

    def _fit_scale(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        return min(w, h) * 0.5 / 32.0      # 默认视野半径约 32 AU

    # ---------- 绘制 ----------
    def _draw_text(self, p, x, y, s, color):
        """带深色描边的文字，避免与轨道线/标记重叠时看不清"""
        p.setPen(QPen(QColor(0x11, 0x11, 0x11)))
        p.drawText(QPointF(x + 1, y + 1), s)
        p.setPen(QPen(color if isinstance(color, QColor) else QColor(color)))
        p.drawText(QPointF(x, y), s)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG_MAIN))

        # 星云背景（预生成纹理，Screen 叠加更像自发光云雾）
        if self.show_nebula and self._nebula_tex is not None:
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            p.drawImage(self.rect(), self._nebula_tex)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        if self._xy is None:
            self._update_positions()
        if not self._scale_ready:
            self._scale = self._fit_scale()
            self._scale_ready = True

        if self.show_grid:
            self._draw_grid(p)
        if self.show_orbits:
            self._draw_orbits(p)
        self._draw_bodies(p)
        self._draw_measure(p)
        self._draw_hud(p)
        p.end()

    def _draw_grid(self, p):
        w, h = self.width(), self.height()
        cx, cy = w * 0.5, h * 0.5
        p.setBrush(Qt.NoBrush)

        # 同心圆（AU 环）
        pen = QPen(QColor(0x33, 0x33, 0x33), 1.0)
        p.setPen(pen)
        label_font = QFont("Microsoft YaHei UI", style.fs(8))
        p.setFont(label_font)
        limit = max(w, h) * 1.6
        for r in GRID_LADDER_AU:
            rp = r * self._scale
            if rp < 18 or rp > limit:
                continue
            p.drawEllipse(QPointF(cx, cy), rp, rp)
            if rp > 34:
                txt = f"{r:g} AU" if r >= 0.01 else f"{r * 1000:g} mAU"
                self._draw_text(p, cx + rp + 3, cy - 3, txt, QColor(0x66, 0x66, 0x66))
                p.setPen(pen)

        # 十字准线（黄道面坐标轴：+x 指向春分点）
        p.setPen(QPen(QColor(0x3a, 0x3a, 0x3a), 1.0, Qt.DashLine))
        p.drawLine(QPointF(0, cy), QPointF(w, cy))
        p.drawLine(QPointF(cx, 0), QPointF(cx, h))
        self._draw_text(p, w - 78, cy - 6, "→ 春分点", QColor(0x6a, 0x6a, 0x6a))

    def _draw_orbits(self, p):
        p.setBrush(Qt.NoBrush)
        # 行星/矮行星轨道
        for name, pts in self._orbit.items():
            i = self._index_of.get(name)
            if i is None:
                continue
            col = _c(self.bodies[i].color)
            col.setAlpha(150 if name == self.selected_name else 90)
            p.setPen(QPen(col, 1.4 if name == self.selected_name else 1.0))
            poly = QPolygonF([QPointF(*self._to_screen(pt)) for pt in pts])
            p.drawPolygon(poly)

        # 卫星轨道（仅在拉近时，相对母行星当前位置绘制）
        if self.show_moons and self._scale > MOON_ZOOM_PX_PER_AU:
            for name, pts in self._moon_orbit.items():
                b = self.bodies[self._index_of[name]]
                pname = getattr(b, "parent_name", "")
                pi = self._index_of.get(pname)
                if pi is None or self._xy is None:
                    continue
                base = self._xy[pi]
                col = _c(b.color)
                col.setAlpha(110)
                p.setPen(QPen(col, 1.0, Qt.DashLine))
                poly = QPolygonF([QPointF(*self._to_screen(base + pt)) for pt in pts])
                p.drawPolygon(poly)

    def _draw_bodies(self, p):
        if self._xy is None:
            return
        w, h = self.width(), self.height()
        show_moons = self.show_moons and self._scale > MOON_ZOOM_PX_PER_AU
        label_font = QFont("Microsoft YaHei UI", style.fs(8))

        # 先画卫星，再画行星，最后画太阳（保证太阳/行星在上层）
        order = sorted(self._solar_idx,
                       key=lambda i: {"moon": 0, "dwarf": 1, "etno": 1,
                                      "planet_solar": 2, "star": 3}.get(
                                          self.bodies[i].body_type, 1))
        for i in order:
            b = self.bodies[i]
            bt = b.body_type
            if bt == "moon" and not show_moons:
                continue
            sx, sy = self._to_screen(self._xy[i])
            if sx < -40 or sx > w + 40 or sy < -40 or sy > h + 40:
                continue
            r = self._marker_radius(b, bt)
            col = _c(b.color)
            is_sel = b.name == self.selected_name
            is_cmp = b.name in self.compare_names

            if is_sel or is_cmp:
                ring = QColor(ACCENT) if is_sel else QColor(ACCENT_BLUE)
                p.setPen(QPen(ring, 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(sx, sy), r + 4.0, r + 4.0)

            p.setPen(QPen(QColor(0x11, 0x11, 0x11), 0.8))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(sx, sy), r, r)

            _show_lbl = (self.show_labels and
                         (is_sel or
                          bt in ("star", "planet_solar") or
                          (bt == "moon" and (is_sel or self._scale > MOON_ZOOM_PX_PER_AU * 2))))
            if _show_lbl:
                p.setFont(label_font)
                self._draw_text(p, sx + r + 3, sy - r - 1, b.name,
                                QColor(ACCENT) if is_sel else QColor(TEXT_MAIN))

        # 测距 A/B 编号
        for slot, nm in zip(("A", "B"), self.measure_names):
            i = self._index_of.get(nm)
            if i is None:
                continue
            sx, sy = self._to_screen(self._xy[i])
            p.setFont(QFont("Microsoft YaHei UI", style.fs(8), QFont.Bold))
            self._draw_text(p, sx + 5, sy + 12, slot, QColor(0x4d, 0xd0, 0xe0))

    def _marker_radius(self, body, bt):
        if bt == "star":
            return 6.5
        if bt == "moon":
            return 2.0
        rk = body.radius_km
        if not rk:
            return 2.5 if bt == "dwarf" else 3.5
        r = 3.2 * (rk / 6371.0) ** 0.33
        return max(2.4, min(9.0, r))

    def _draw_measure(self, p):
        if len(self.measure_names) != 2 or self._xy is None:
            return
        ia = self._index_of.get(self.measure_names[0])
        ib = self._index_of.get(self.measure_names[1])
        if ia is None or ib is None:
            return
        a = self._to_screen(self._xy[ia])
        b = self._to_screen(self._xy[ib])
        p.setPen(QPen(QColor(0x4d, 0xd0, 0xe0), 1.4, Qt.DashLine))
        p.drawLine(QPointF(*a), QPointF(*b))
        d = float(np.linalg.norm(self._body_pos[ia] - self._body_pos[ib]))
        mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
        p.setFont(QFont("Microsoft YaHei UI", style.fs(8)))
        self._draw_text(p, mx + 4, my - 4, f"{d:.4g} AU", QColor(0x4d, 0xd0, 0xe0))

    def _draw_hud(self, p):
        p.setFont(QFont("Microsoft YaHei UI", style.fs(9)))
        dt = self.clock.now_datetime()
        self._draw_text(p, 10, 18, f"二维平面视图（俯视黄道面）　{dt:%Y-%m-%d %H:%M} UTC",
                        QColor(TEXT_DIM))
        self._draw_text(p, 10, 34,
                        f"每 AU ≈ {self._scale:.1f} px　滚轮缩放 · 拖拽平移 · 单击选中 · 双击聚焦",
                        QColor(TEXT_DIM))
        if self._follow_name:
            self._draw_text(p, 10, 50, f"锁定跟随：{self._follow_name}", QColor(ACCENT))
        if self.locked_name is not None:
            self._draw_text(p, 10, 66, f"已锁定：{self.locked_name}（F键解锁）", QColor(ACCENT))
        # 比例尺
        w, h = self.width(), self.height()
        target_px = 120.0
        au = target_px / self._scale
        nice = _nice_number(au)
        bar = nice * self._scale
        x0, y0 = 12.0, h - 14.0
        p.setPen(QPen(QColor(TEXT_DIM), 1.2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + bar, y0))
        p.drawLine(QPointF(x0, y0 - 3), QPointF(x0, y0 + 3))
        p.drawLine(QPointF(x0 + bar, y0 - 3), QPointF(x0 + bar, y0 + 3))
        p.drawText(QPointF(x0 + bar + 6, y0 + 4), f"{nice:g} AU")

    # ---------- 交互 ----------
    def resizeEvent(self, ev):
        if not self._scale_ready:
            self._scale = self._fit_scale()
            self._scale_ready = True
        super().resizeEvent(ev)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_F:
            self._toggle_lock()
            return
        super().keyPressEvent(ev)

    def _toggle_lock(self):
        """F键：锁定/解锁当前选中天体。锁定后点击其他天体不会切换选中。"""
        if self.locked_name is not None:
            self.locked_name = None
        elif self.selected_name is not None:
            self.locked_name = self.selected_name
        self.update()

    def showEvent(self, ev):
        # 窗口隐藏时停表，避免不可见时仍以 60fps 空转
        self._last_tick = _time.perf_counter()
        if not self._timer.isActive():
            self._timer.start(16)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def wheelEvent(self, ev):
        self._mark_active()
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        factor = 1.0022 ** delta
        before = self._to_world(ev.pos().x(), ev.pos().y())
        self._scale = max(MIN_SCALE, min(MAX_SCALE, self._scale * factor))
        after = self._to_world(ev.pos().x(), ev.pos().y())
        self._center += before - after          # 缩放对准光标
        self.update()

    def mousePressEvent(self, ev):
        self._mark_active()
        if ev.button() == Qt.LeftButton:
            self._drag = True
            self._moved = False
            self._drag_start = ev.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag and self._drag_start is not None:
            self._mark_active()
            dx = ev.pos().x() - self._drag_start.x()
            dy = ev.pos().y() - self._drag_start.y()
            if abs(dx) + abs(dy) > 3:
                self._moved = True
            self._center[0] -= dx / self._scale
            self._center[1] += dy / self._scale
            self._drag_start = ev.pos()
            if self._follow_name:               # 手动平移即解除跟随
                self._set_follow(None)
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = False
            self.setCursor(Qt.ArrowCursor)
            if not self._moved:
                self._pick(ev.pos().x(), ev.pos().y())

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            body = self._body_at(ev.pos().x(), ev.pos().y())
            if body is not None:
                self.focus_body_by_name(body.name)

    def _body_at(self, sx, sy):
        if self._xy is None:
            return None
        best, bestd = None, HIT_PX
        for i in self._solar_idx:
            b = self.bodies[i]
            if b.body_type == "moon" and not (
                    self.show_moons and self._scale > MOON_ZOOM_PX_PER_AU):
                continue
            px, py = self._to_screen(self._xy[i])
            d = math.hypot(px - sx, py - sy)
            if d < bestd:
                best, bestd = b, d
        return best

    def _pick(self, sx, sy):
        body = self._body_at(sx, sy)
        if body is not None:
            if self.locked_name is not None and body.name != self.locked_name:
                return  # 锁定状态下点击其他天体不切换
            self.selected_name = body.name
            self.update()
            self.bodySelected.emit(body)

    # ---------- 对外接口（与三维视口同名） ----------
    def focus_body_by_name(self, name):
        i = self._index_of.get(name)
        if i is None:
            return
        self._mark_active(5.0)
        b = self.bodies[i]
        self.selected_name = name
        if b.body_type in ("planet_exo", "host_star", "blackhole",
                           "nearby_star", "interstellar") or (
                b.body_type == "star" and b.name != "太阳"):
            # 系外天体 / 宿主恒星 / 黑洞 不在太阳系平面视图内，仅选中不移动视野
            self.update()
            return
        self._update_positions()
        self._center = self._xy[i].copy()
        self._set_follow(name)
        self.update()

    def set_measure_pair(self, name_a, name_b):
        if name_a and name_b:
            self.measure_names = [name_a, name_b]
        else:
            self.measure_names = []
        self.update()

    def set_follow(self, enabled, body=None):
        if enabled:
            name = body.name if body is not None else self.selected_name
            self._set_follow(name)
        else:
            self._set_follow(None)

    def reset_view(self):
        """复位视野：回到太阳居中的全景"""
        self._center = np.zeros(2)
        self._scale = self._fit_scale()
        self._set_follow(None)
        self.update()

    def zoom_by(self, factor):
        self._scale = max(MIN_SCALE, min(MAX_SCALE, self._scale * factor))
        self.update()

    def _set_follow(self, name):
        if name == self._follow_name:
            return
        self._follow_name = name
        self.followChanged.emit(name is not None)

    # 兼容三维视口的空实现（工具栏若调用则无害）
    def set_solid(self, enabled):
        pass

    def set_axes(self, enabled):
        pass

    def set_orbit_filter(self, solar=True, exo=True, year_range=None):
        pass

    def set_belt(self, enabled=None, count=None):
        pass


def _nice_number(x):
    """取 1/2/5 × 10^n 中不超过 x 的最大者（比例尺用）"""
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    base = 10.0 ** e
    for m in (5.0, 2.0, 1.0):
        if m * base <= x:
            return m * base
    return base