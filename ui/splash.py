"""
splash.py —— 启动画面（Splash Screen）

按「软件启动速度优化」需求实现：
    * 程序启动后立即显示（主界面就绪前给用户即时反馈）
    * 底部自绘进度条：圆角 + 渐变填充 + 柔和光晕 + 平滑过渡动画
      （不使用 QProgressBar 默认样式）
    * 进度条上方文字提示当前加载阶段
    * 背景：assets/splash.png（用户后续提供）自适应窗口、保持比例居中；
      无背景图时以「深空渐变 + 固定种子程序化星点」兜底，风格与软件一致
    * 加载完成淡出

线程安全：后台线程通过 `report()`（内部为 Qt 信号）报告进度，
自动排队到主线程重绘，无需加锁。
"""
import math
import os

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import (QPainter, QColor, QLinearGradient, QPainterPath,
                         QFont, QPen, QBrush, QPixmap)
from PyQt5.QtWidgets import QWidget

from ui.resource import resource_dir as _resource_dir

# 背景图查找顺序：专用启动图 → 应用图 → 无（渐变兜底）
_BG_CANDIDATES = ("assets/splash.png", "assets/app.png")

# 进度条动画：显示值向目标值按比例逼近（每帧 16ms）
_ANIM_INTERVAL_MS = 16
_ANIM_FACTOR = 0.28


class SplashScreen(QWidget):
    """启动画面：背景 + 阶段文字 + 自绘进度条 + 完成淡出"""

    # 内部信号：后台线程 report() → 主线程 _on_progress（跨线程自动排队）
    _sig_progress = pyqtSignal(int, str)
    _sig_done = pyqtSignal()

    def __init__(self, width=680, height=440, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(width, height)

        self._target = 0          # 目标进度（0-100）
        self._current = 0.0       # 当前显示进度（动画插值）
        self._stage = ""          # 当前阶段文字
        self._bg = self._load_background(width, height)
        self._fade_timer = None
        self._opacity = 1.0

        # 平滑动画定时器
        self._anim = QTimer(self)
        self._anim.setInterval(_ANIM_INTERVAL_MS)
        self._anim.timeout.connect(self._on_anim_tick)

        # 跨线程信号
        self._sig_progress.connect(self._on_progress)
        self._sig_done.connect(self._on_done)

    # ---------- 背 ----------
    @staticmethod
    def _load_background(w, h):
        """载入背景图（等比放大到窗口、居中裁切）；失败返回 None。"""
        for rel in _BG_CANDIDATES:
            path = os.path.join(_resource_dir(), rel.replace("/", os.sep))
            if os.path.isfile(path):
                pix = QPixmap(path)
                if not pix.isNull() and pix.width() >= 400:
                    # 保持比例覆盖窗口（cover 模式）：短边撑满、居中裁切
                    scaled = pix.scaled(
                        w, h, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
                    x = (scaled.width() - w) // 2
                    y = (scaled.height() - h) // 2
                    return scaled.copy(x, y, w, h)
        return None

    # ---------- 对外接口（任意线程可调用 report / finish） ----------
    def report(self, pct: int, stage: str = ""):
        """报告进度（0-100）与阶段说明。线程安全（信号跨线程自动排队）。"""
        self._sig_progress.emit(int(pct), str(stage))

    def finish(self):
        """加载完成：通知主线程淡出并关闭。线程安全。"""
        self._sig_done.emit()

    # ---------- 主线程槽 ----------
    def _on_progress(self, pct: int, stage: str):
        self._target = max(0, min(100, pct))
        if stage:
            self._stage = stage
        if not self._anim.isActive():
            self._anim.start()
        self.update()

    def _on_done(self):
        self._target = 100
        self._stage = "完成"
        # 等进度条动画到位后开始淡出
        if not self._anim.isActive():
            self._anim.start()

    def _on_anim_tick(self):
        diff = self._target - self._current
        if abs(diff) > 0.15:
            self._current += diff * _ANIM_FACTOR
        else:
            self._current = float(self._target)
        # 目标 100 且动画到位 → 停表；若已 finish 则启动淡出
        if self._current >= 99.95 and self._target >= 100:
            self._anim.stop()
            self._current = 100.0
            self.update()
            if self._fade_timer is None and self._stage == "完成":
                self._start_fade()
        else:
            self.update()

    def _start_fade(self):
        """窗口整体透明度淡出（~350ms）后关闭。"""
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(18)
        self._fade_timer.timeout.connect(self._on_fade_tick)
        self._fade_timer.start()

    def _on_fade_tick(self):
        self._opacity -= 0.06
        if self._opacity <= 0.0:
            self._fade_timer.stop()
            self.close()
        else:
            self.setWindowOpacity(self._opacity)

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        if self._bg is not None:
            p.drawPixmap(0, 0, self._bg)
            # 底部压暗，保证文字/进度条可读
            shade = QLinearGradient(0, h * 0.45, 0, h)
            shade.setColorAt(0.0, QColor(15, 16, 20, 0))
            shade.setColorAt(1.0, QColor(12, 13, 17, 215))
            p.fillRect(QRectF(0, h * 0.45, w, h * 0.55), QBrush(shade))
        else:
            self._paint_fallback_bg(p, w, h)

        self._paint_texts(p, w, h)
        self._paint_progress(p, w, h)

    def _paint_fallback_bg(self, p, w, h):
        """无背景图：深空垂直渐变 + 固定种子程序化星点（可复现）。"""
        grad = QLinearGradient(0, 0, w * 0.2, h)
        grad.setColorAt(0.0, QColor("#14151b"))
        grad.setColorAt(0.55, QColor("#1d1f27"))
        grad.setColorAt(1.0, QColor("#101015"))
        p.fillRect(QRectF(0, 0, w, h), QBrush(grad))

        # 固定伪随机星点（三角函数种子，无 random 模块依赖，可复现）
        for i in range(160):
            t = i * 12.9898
            x = (math.sin(t * 1.7) * 43758.5453) % 1.0
            y = (math.sin(t * 2.3 + 1.7) * 24634.6345) % 1.0
            r = 0.5 + ((math.sin(t * 3.1) * 19349.63) % 1.0) * 1.3
            alpha = 60 + int(((math.sin(t * 4.7) * 9387.11) % 1.0) * 150)
            p.setPen(QPen(QColor(220, 225, 235, alpha), r, Qt.SolidLine,
                          Qt.RoundCap))
            p.drawPoint(x * w, y * h)
        # 一抹强调色氛围光（左上角淡淡的橙晕）
        glow = QColor(230, 145, 63, 26)
        for k in range(5):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(230, 145, 63, 5))
            p.drawEllipse(QRectF(-60 - k * 46, -70 - k * 50,
                                 240 + k * 92, 240 + k * 100))

    def _paint_texts(self, p, w, h):
        # 标题（左下）
        p.setPen(QColor("#e8e9ec"))
        f = QFont("Microsoft YaHei", pointSize=19)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(28, h - 128, w - 56, 34),
                   int(Qt.AlignLeft | Qt.AlignVCenter), "Astrarium")
        # 副标题
        p.setPen(QColor("#9aa0a8"))
        f2 = QFont("Microsoft YaHei", pointSize=9)
        p.setFont(f2)
        p.drawText(QRectF(28, h - 92, w - 56, 20),
                   int(Qt.AlignLeft | Qt.AlignVCenter),
                   "Planetary Visualization · 太阳系 / 系外行星 / 科研计算")

        # 阶段文字（进度条上方）+ 百分比（右侧）
        p.setPen(QColor("#c9ccd2"))
        f3 = QFont("Microsoft YaHei", pointSize=9)
        p.setFont(f3)
        stage = self._stage or "正在启动…"
        p.drawText(QRectF(28, h - 60, w - 130, 18),
                   int(Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine), stage)
        p.setPen(QColor("#e6913f"))
        p.drawText(QRectF(w - 100, h - 60, 72, 18),
                   int(Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine),
                   f"{int(round(self._current))}%")

    def _paint_progress(self, p, w, h):
        """自绘进度条：圆角槽 + 渐变填充 + 柔和光晕。"""
        bar_w = w - 56
        bar_h = 10
        x, y = 28, h - 36
        r = bar_h / 2.0
        frac = max(0.0, min(1.0, self._current / 100.0))

        # 槽（深色内嵌感）
        slot_path = QPainterPath()
        slot_path.addRoundedRect(QRectF(x, y, bar_w, bar_h), r, r)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor(20, 21, 26, 200))
        p.drawPath(slot_path)

        if frac <= 0.001:
            return
        fill_w = max(bar_h, bar_w * frac)

        # 光晕（外扩多层半透明描边）
        for k in range(4):
            glow = QPainterPath()
            pad = 2.0 + k * 2.4
            glow.addRoundedRect(
                QRectF(x - pad * 0.4, y - pad * 0.5,
                       fill_w + pad * 0.8, bar_h + pad), r + pad * 0.5,
                r + pad * 0.5)
            p.setPen(QPen(QColor(230, 145, 63, 10 - k * 2), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPath(glow)

        # 填充（橙→浅橙渐变）
        fill = QLinearGradient(x, y, x, y + bar_h)
        fill.setColorAt(0.0, QColor("#f0b060"))
        fill.setColorAt(1.0, QColor("#d97f2e"))
        fill_path = QPainterPath()
        fill_path.addRoundedRect(QRectF(x, y, fill_w, bar_h), r, r)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(fill_path)

        # 高光（上缘细亮线，增强质感）
        hl = QLinearGradient(x, y, x, y + bar_h * 0.5)
        hl.setColorAt(0.0, QColor(255, 255, 255, 90))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        hl_path = QPainterPath()
        hl_path.addRoundedRect(QRectF(x + 1, y + 1, fill_w - 2, bar_h * 0.5 - 1),
                               r * 0.5, r * 0.5)
        p.setBrush(QBrush(hl))
        p.drawPath(hl_path)
