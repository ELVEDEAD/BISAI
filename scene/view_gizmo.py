"""
view_gizmo.py —— Blender 风格视角导航轴（View Gizmo）

3D 视口右上角叠加的 XYZ 轴向导航球：
- X 红 / Y 绿 / Z 蓝，正端点带字母、负端点小圆点，均可点击
- 姿态实时跟随主相机（轨道/飞行模式通用），与主渲染共用同一套
  屏幕基向量（look_at_matrix 的 right/up/fwd），保证轴向无镜像/反向
- 点击端点 → 发 axisClicked("+x"/"-x"/...) → viewport 切轴向视角（平滑动画）
- 独立 QWidget 叠加层：局部 update() 只重绘自身，不触发主场景重绘；
  子控件天然拦截鼠标/滚轮事件，Gizmo 上操作不会误触发主视图旋转缩放

命中规则（需求 3.3）：
- 端点命中按"离鼠标最近且未超出其半径"为准
- 正负端点投影重叠时优先命中正方向端点
- 某轴几乎正对/背对屏幕（两端点屏幕距离过小）时负端点隐藏，防止误点
"""
import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from core.i18n import tr

# 常量（px）
SIZE = 96              # 控件边长（需求 2.1：整体直径约 80~100）
AXIS_LEN = 34          # 轴线长度（中心 → 端点圆心）
TIP_R = 9.0            # 正端点半径
TIP_R_HOVER = 11.0     # 正端点悬停放大半径
NEG_R = 4.5            # 负端点半径
HIT_PAD = 2.0          # 命中判定额外容差（px）
HIDE_NEG_AT = 0.22     # 轴屏幕投影长度低于该值时隐藏负端点
MARGIN = 14            # 距视口右上角边距（需求 2.1：12~16px）

_AXIS_VEC = {
    "x": np.array([1.0, 0.0, 0.0]),
    "y": np.array([0.0, 1.0, 0.0]),
    "z": np.array([0.0, 0.0, 1.0]),
}
_AXIS_COLOR = {
    "x": QColor(0xd6, 0x3d, 0x3d),     # X 红
    "y": QColor(0x6c, 0xa8, 0x4d),     # Y 绿
    "z": QColor(0x4d, 0x76, 0xb8),     # Z 蓝
}
_TIP_TEXT = {
    ("x", 1): "侧视图（+X 轴）", ("x", -1): "侧视图（-X 轴）",
    ("y", 1): "侧视图（+Y 轴）", ("y", -1): "侧视图（-Y 轴）",
    ("z", 1): "俯视图（+Z 轴）", ("z", -1): "仰视图（-Z 轴）",
}


class ViewGizmo(QWidget):
    """视角导航轴叠加控件（父控件必须是 Viewport）"""

    axisClicked = pyqtSignal(str)      # "+x"/"-x"/"+y"/"-y"/"+z"/"-z"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SIZE, SIZE)
        # 透明叠加：不擦除背景（否则会在 GL 视口上留矩形底色）
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)    # 悬停高亮（无需按键）
        self.setToolTip(tr("视角导航轴：点击 X/Y/Z 切换轴向视角"))
        self._hover = None             # 当前悬停端点 (axis, sign)
        # 姿态缓存（上一帧的屏幕基向量；变化超阈值才重绘自身）
        self._basis = None             # (right, up, fwd) 世界系单位向量
        # 各端点屏幕位置缓存：{"x": (pos端, neg端或None, 轴屏幕方向, 深度)}
        self._tips = {}

    # ---------- 姿态同步 ----------
    def sync_pose(self, camera):
        """每帧由视口调用：从相机取屏幕基向量，姿态变化才局部重绘。

        只做 9 个浮点的比较 + 自身 update()（重绘 96×px 小区域），
        不触发父 GL 视口的任何重绘（需求 2.3 性能约束）。"""
        fwd = camera.forward_dir()
        right = np.cross(fwd, (0.0, 0.0, 1.0))
        n = float(np.linalg.norm(right))
        right = right / n if n > 1e-9 else np.array((1.0, 0.0, 0.0))
        up = np.cross(right, fwd)
        basis = (right, up, fwd)
        if self._basis is not None:
            ok = all(np.allclose(a, b, atol=1e-4) for a, b in zip(basis, self._basis))
            if ok:
                return
        self._basis = basis
        self._compute_tips()
        self.update()

    def _compute_tips(self):
        """把三个世界轴投影到屏幕，缓存端点位置/深度/可见性。"""
        right, up, fwd = self._basis
        cx = cy = SIZE / 2.0
        self._tips = {}
        for axis, vec in _AXIS_VEC.items():
            sx = float(np.dot(vec, right))
            sy = float(np.dot(vec, up))
            depth = float(np.dot(vec, fwd))      # >0 指向屏幕内（远侧）
            slen = float(np.hypot(sx, sy))
            # Qt 屏幕 y 向下：世界轴朝屏幕上方 → 画布 y 取负
            pos = QPointF(cx + sx * AXIS_LEN, cy - sy * AXIS_LEN)
            neg = QPointF(cx - sx * AXIS_LEN, cy + sy * AXIS_LEN)
            # 轴几乎正对/背对屏幕（两端点屏幕距离过小）→ 负端点隐藏
            neg_vis = slen >= HIDE_NEG_AT
            self._tips[axis] = dict(pos=pos, neg=neg, neg_vis=neg_vis,
                                    depth=depth)

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        if not self._tips:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = SIZE / 2.0
        # 半透明底色圆盘（轻量、不突兀）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0x1d, 0x1d, 0x1d, 90))
        p.drawEllipse(QPointF(cx, cy), SIZE / 2.0 - 2.0, SIZE / 2.0 - 2.0)
        # 深度排序：指向屏幕内（depth>0，远侧）的先画、更淡；朝相机的后画、实色
        order = sorted(self._tips, key=lambda a: -self._tips[a]["depth"])
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        for axis in order:
            t = self._tips[axis]
            color = _AXIS_COLOR[axis]
            near = t["depth"] < 0.0            # 该轴正端朝向相机 → 近侧
            # 轴线（远侧半透明、近侧实色，营造立体感）
            line_c = QColor(color)
            line_c.setAlpha(255 if near else 95)
            pen = QPen(line_c, 2.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx, cy), t["pos"])
            # 正端点（带字母；悬停高亮放大）
            hovered = self._hover == (axis, 1)
            r = TIP_R_HOVER if hovered else TIP_R
            tip_c = QColor(color)
            if hovered:
                tip_c = tip_c.lighter(130)
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.setBrush(tip_c)
            p.drawEllipse(t["pos"], r, r)
            if not near:
                # 远侧正端点字母降透明度，与整体层次一致
                p.setPen(QColor(255, 255, 255, 170))
            else:
                p.setPen(QColor(255, 255, 255, 255))
            p.drawText(t["pos"], axis.upper())
            # 负端点（小圆点，无字母；近侧时实色、远侧淡化；隐藏时不画）
            if t["neg_vis"]:
                neg_c = QColor(color)
                neg_c.setAlpha(200 if not near else 120)
                neg_hover = self._hover == (axis, -1)
                if neg_hover:
                    neg_c = neg_c.lighter(130)
                p.setPen(Qt.NoPen)
                p.setBrush(neg_c)
                p.drawEllipse(t["neg"], NEG_R + (1.5 if neg_hover else 0.0),
                              NEG_R + (1.5 if neg_hover else 0.0))
        # 中心点
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0xe8, 0xe8, 0xe8, 200))
        p.drawEllipse(QPointF(cx, cy), 2.6, 2.6)
        p.end()

    # ---------- 命中检测 ----------
    def hit_test(self, x: float, y: float):
        """返回命中的端点 key（如 "+x"）；无命中返回 None。

        规则（需求 3.3）：离鼠标最近且未超出半径；正负重叠时正方向优先。"""
        pt = QPointF(x, y)
        hits = []
        for axis, t in self._tips.items():
            r_pos = (TIP_R_HOVER if self._hover == (axis, 1) else TIP_R) + HIT_PAD

            d_pos = _dist(pt, t["pos"])
            if d_pos <= r_pos:
                hits.append(("+" + axis, d_pos))
            if t["neg_vis"]:
                d_neg = _dist(pt, t["neg"])
                if d_neg <= NEG_R + HIT_PAD:
                    hits.append(("-" + axis, d_neg))
        if not hits:
            return None
        pos_hits = [h for h in hits if h[0].startswith("+")]
        if pos_hits:
            return min(pos_hits, key=lambda h: h[1])[0]
        return min(hits, key=lambda h: h[1])[0]

    # ---------- 事件 ----------
    def mouseMoveEvent(self, ev):
        key = self.hit_test(ev.x(), ev.y())
        hover = None
        if key:
            hover = (key[1], 1 if key[0] == "+" else -1)
        if hover != self._hover:
            self._hover = hover
            if hover:
                self.setToolTip(tr(_TIP_TEXT[hover]))
            else:
                self.setToolTip(tr("视角导航轴：点击 X/Y/Z 切换轴向视角"))
            self.update()
        ev.accept()

    def mousePressEvent(self, ev):
        key = self.hit_test(ev.x(), ev.y())
        if key:
            self.axisClicked.emit(key)
        # 空白圆盘区域：不做任何操作，仅拦截（不穿透到主视图）
        ev.accept()

    def leaveEvent(self, ev):
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        # Gizmo 上滚轮不触发主视图缩放（需求 3.6）
        ev.accept()

    # ---------- 布局 ----------
    def reposition(self):
        """贴到父视口右上角（视口 resize 时由 resizeGL 调用）。"""
        if self.parent() is not None:
            self.move(self.parent().width() - SIZE - MARGIN, MARGIN)
            self.raise_()

    def set_shown(self, shown: bool):
        """设置开关（设置面板「显示 3D 视角导航轴」）。隐藏后快捷键仍可用。"""
        self.setVisible(bool(shown))


def _dist(a: QPointF, b: QPointF) -> float:
    return float(((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5)