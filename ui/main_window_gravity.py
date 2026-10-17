"""
main_window_gravity.py —— 「引力系统」模式窗口（时空弯曲网格）

把引力 / 时空弯曲用一张网格直观画出来：天体按 M/r 引力势把所在处的黄道面网格压出凹陷，
质量越大、距离越近，凹陷越深（相对深度为真实值），整体深度按网格格距自动归一化，
因此任意缩放级别下都清晰可见。

布局：
    ┌──────────────────────────────────────────────────────┐
    │ 顶部工具栏：凹陷来源 | 凹陷强度 | 网格密度 | 显示开关 │
    ├──────────┬──────────────────────────┬────────────────┤
    │ 天体树   │      引力网格视口        │ 引力信息       │
    ├──────────┴──────────────────────────┴────────────────┤
    │ 时间轴（底部）                                       │
    └──────────────────────────────────────────────────────┘

与 3D / 2D 视图共用同一套数据与时间系统；工具栏「切换模式」返回启动器。
"""
import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QSplitter, QCheckBox, QLabel, QComboBox,
                             QToolBar, QAction, QDialog, QTextEdit)

from scene.viewport import Viewport
from ui import dark_titlebar
from ui.resource import icon_path
from ui.style import BG_PANEL, BORDER, TEXT_MAIN, TEXT_DIM, ACCENT
from ui.timeline import Timeline
from ui.tree_panel import TreePanel
from data.loader import BODY_TYPE_LABELS

# 初始视距取 30 AU：网格格距恰好落在 10 AU 档，整张网格覆盖 ±120 AU 的太阳系
_INIT_DIST = 30.0


class GravityWindow(QMainWindow):
    """引力系统窗口：以弯曲网格呈现天体引力势"""

    def __init__(self, bodies, stars):
        super().__init__()
        self.bodies = bodies
        self.stars = stars
        self._switch_cb = None
        self._selected = None
        self.setWindowTitle("Astrarium —— 引力系统（时空弯曲网格）")
        self.setWindowIcon(QIcon(icon_path()))
        self.resize(1400, 900)

        self._build_ui()
        self._connect_signals()
        self._start_timers()
        self._refresh_info()

    def set_switch_callback(self, cb):
        """由启动器注入「切换模式」回调"""
        self._switch_cb = cb

    # ---------- 组装 ----------
    def _build_ui(self):
        self.addToolBar(self._build_toolbar())

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        self.tree_panel = TreePanel(self.bodies)
        splitter.addWidget(self.tree_panel)

        self.viewport = Viewport()
        self.viewport.load_bodies(self.bodies, self.stars)
        self._configure_viewport()
        splitter.addWidget(self.viewport)

        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setFrameShape(QTextEdit.NoFrame)
        self.info.setMinimumWidth(300)
        self.info.setStyleSheet(
            f"background-color:{BG_PANEL}; color:{TEXT_MAIN};"
            f"border-left:1px solid {BORDER}; padding:10px;")
        splitter.addWidget(self.info)

        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([220, 760, 320])
        splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter, 1)

        self.timeline = Timeline(self.viewport.clock)
        lay.addWidget(self.timeline)

        self.setCentralWidget(central)

    def _configure_viewport(self):
        """把通用三维视口切到「引力网格」专用配置"""
        vp = self.viewport
        vp.gravity_mode = True
        vp.show_grid = True
        vp.show_orbits = False
        vp.show_trails = False
        vp.show_belt = False
        vp.show_moons = False
        vp.show_rings = False
        vp.show_axes = False
        vp.show_nebula = True
        vp.show_stars = True
        vp.real_scale = False
        vp.set_solid(True)
        vp.gravity_names = None          # 默认：全部天体（真实 M/r）
        vp.gravity_cells = 96
        vp.gravity_scale = 1.0
        vp.camera.distance = _INIT_DIST
        vp.camera.set_view(35.0, 28.0)   # 略俯视黄道面，方便看凹陷

    def _build_toolbar(self):
        tb = QToolBar("引力工具栏")
        tb.setMovable(False)

        tb.addWidget(QLabel("  凹陷来源: "))
        self.cmb_source = QComboBox()
        self.cmb_source.addItems(["全部天体（真实 M/r）", "仅选中天体（自动放大）"])
        self.cmb_source.setToolTip(
            "全部天体：所有有质量天体一起下陷，相对深度为真实 M/r（太阳主导）\n"
            "仅选中天体：只画当前选中天体的凹陷，并自动放大到醒目深度，便于单独观察")
        self.cmb_source.currentIndexChanged.connect(self._on_source)
        tb.addWidget(self.cmb_source)

        tb.addWidget(QLabel("  凹陷强度: "))
        self.cmb_scale = QComboBox()
        for _label, _val in (("浅", 0.5), ("中", 1.0), ("深", 1.8), ("极深", 3.0)):
            self.cmb_scale.addItem(_label, _val)
        self.cmb_scale.setCurrentIndex(1)
        self.cmb_scale.setToolTip("凹陷的视觉深度倍率（相对深度比例不受影响）")
        self.cmb_scale.currentIndexChanged.connect(self._on_scale)
        tb.addWidget(self.cmb_scale)

        tb.addWidget(QLabel("  网格密度: "))
        self.cmb_cells = QComboBox()
        for _label, _val in (("标准", 64), ("高", 96), ("极高", 128), ("超精细", 192)):
            self.cmb_cells.addItem(_label, _val)
        self.cmb_cells.setCurrentIndex(1)
        self.cmb_cells.setToolTip("网格分辨率，越高凹陷越平滑（顶点数按平方增长）")
        self.cmb_cells.currentIndexChanged.connect(self._on_cells)
        tb.addWidget(self.cmb_cells)

        tb.addSeparator()

        self.chk_follow = QCheckBox("锁定跟随")
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip("相机焦点锁定到选中天体，天体随时间移动时凹陷始终在视野内")
        self.chk_follow.toggled.connect(self._on_follow)
        tb.addWidget(self.chk_follow)

        self.chk_nebula = QCheckBox("星云")
        self.chk_nebula.setChecked(True)
        self.chk_nebula.toggled.connect(self._on_nebula)
        tb.addWidget(self.chk_nebula)

        self.chk_stars = QCheckBox("背景星")
        self.chk_stars.setChecked(True)
        self.chk_stars.toggled.connect(self._on_stars)
        tb.addWidget(self.chk_stars)

        self.chk_solid = QCheckBox("实体球")
        self.chk_solid.setChecked(True)
        self.chk_solid.toggled.connect(self._on_solid)
        tb.addWidget(self.chk_solid)

        self.chk_ondemand = QCheckBox("按需渲染")
        self.chk_ondemand.setChecked(True)
        self.chk_ondemand.setToolTip(
            "省算力：空闲时降到低帧率重绘，拖动/缩放/选中天体时自动恢复满帧。\n"
            "引力网格为静态示意，低帧率下依然平滑；关闭则始终满帧")
        # 工具栏在视口创建之前构建，故用 lambda 惰性取 self.viewport
        self.chk_ondemand.toggled.connect(lambda on: self.viewport.set_on_demand(on))
        tb.addWidget(self.chk_ondemand)

        tb.addSeparator()

        act_reset = QAction("重置视角", self)
        act_reset.triggered.connect(self._reset_view)
        tb.addAction(act_reset)

        act_help = QAction("帮助", self)
        act_help.triggered.connect(self._show_help)
        tb.addAction(act_help)

        act_switch = QAction("切换模式", self)
        act_switch.setToolTip("返回模式选择（3D / 2D / 引力系统）")
        act_switch.triggered.connect(self._switch_mode)
        tb.addAction(act_switch)

        act_settings = QAction("设置", self)
        act_settings.setToolTip("打开设置面板（显示模式、帧率限制等）")
        act_settings.triggered.connect(self._show_settings)
        tb.addAction(act_settings)

        return tb

    def _connect_signals(self):
        self.tree_panel.bodyClicked.connect(self._select)
        self.viewport.bodySelected.connect(self._on_viewport_select)
        self.timeline.dateChanged.connect(lambda _jd: self.viewport.update())

    def _start_timers(self):
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self.timeline.tick)
        self._ui_timer.start(500)

    def showEvent(self, ev):
        dark_titlebar.apply_dark_titlebar(self)
        if not self._ui_timer.isActive():
            self._ui_timer.start(500)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._ui_timer.stop()
        super().hideEvent(ev)

    # ---------- 交互 ----------
    def _on_viewport_select(self, body):
        self.tree_panel.select_body(body.name)
        self._select(body)

    def _select(self, body):
        """选中天体：更新信息面板；「仅选中天体」模式下切换凹陷来源；聚焦相机"""
        self._selected = body
        vp = self.viewport
        vp._mark_active(5.0)             # 选中即恢复满帧，凹陷/相机动画流畅
        vp.selected_name = body.name
        if self.cmb_source.currentIndex() == 1:
            vp.gravity_names = {body.name}
        pos = body.position_at_jd(vp.clock.jd)
        vp.camera.focus_on(pos)          # 聚焦到适中视距（不按天体半径贴脸）
        if self.chk_follow.isChecked():
            vp.set_follow(True, body)
        self._refresh_info()
        vp.update()

    def _on_source(self, idx):
        vp = self.viewport
        if idx == 0:
            vp.gravity_names = None
        else:
            name = (self._selected.name if self._selected is not None
                    else self._default_name())
            vp.gravity_names = {name} if name else None
        vp.update()

    def _on_scale(self):
        self.viewport.gravity_scale = self.cmb_scale.currentData()
        self.viewport.update()

    def _on_cells(self):
        self.viewport.gravity_cells = self.cmb_cells.currentData()
        self.viewport.update()

    def _on_follow(self, on):
        self.viewport.set_follow(on, self._selected)

    def _on_nebula(self, on):
        self.viewport.show_nebula = on
        self.viewport.update()

    def _on_stars(self, on):
        self.viewport.show_stars = on
        self.viewport.update()

    def _on_solid(self, on):
        self.viewport.set_solid(on)

    def _reset_view(self):
        self.viewport.set_follow(False)
        self.chk_follow.setChecked(False)
        self.viewport.camera.snap_focus(np.zeros(3), _INIT_DIST)
        self.viewport.camera.set_view(35.0, 28.0)
        self.viewport.update()

    def _default_name(self):
        b = next((x for x in self.bodies if x.body_type == "star"), None)
        return b.name if b else None

    def _switch_mode(self):
        if self._switch_cb is not None:
            self._switch_cb()

    def _show_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=self, viewport=self.viewport)
        dlg.exec_()

    # ---------- 信息面板 ----------
    def _refresh_info(self):
        b = self._selected
        if b is None:
            self.info.setHtml(
                "<p style='color:%s;line-height:1.6'>"
                "在左侧天体树中选择一颗天体，或直接在视口中点击，<br>"
                "即可查看它把时空网格压出的凹陷。</p>"
                "<hr><p style='color:%s;line-height:1.6'>"
                "网格按 <b>M/r</b> 引力势下陷：<br>"
                "质量越大、距离越近，凹陷越深。黑洞的凹陷极深。</p>"
                % (TEXT_DIM, TEXT_DIM))
            return

        kind = BODY_TYPE_LABELS.get(b.body_type, b.body_type)
        me = getattr(b, "mass_earth", None)
        ms = getattr(b, "mass_solar", None)
        rows = [f"<h3 style='color:{ACCENT};margin:2px 0'>{b.name}</h3>",
                f"<p style='color:{TEXT_MAIN};margin:2px 0'>类型：{kind}</p>"]
        if me:
            rows.append(f"<p style='color:{TEXT_MAIN};margin:2px 0'>质量：{me:,.6g} 地球质量</p>")
        if ms:
            rows.append(f"<p style='color:{TEXT_MAIN};margin:2px 0'>质量：{ms:.6g} 太阳质量</p>")
        if not me and not ms:
            rows.append(f"<p style='color:{TEXT_DIM};margin:2px 0'>质量：未知（不参与下陷）</p>")
        # 黑洞特殊说明
        if b.body_type == "blackhole":
            rs_km = getattr(b, "radius_km", None)
            if rs_km:
                rows.append(f"<p style='color:{TEXT_MAIN};margin:2px 0'>史瓦西半径：{rs_km:,.3g} km</p>")
            bh_type = getattr(b, "bh_type", "")
            if bh_type:
                rows.append(f"<p style='color:{TEXT_MAIN};margin:2px 0'>类型：{bh_type}</p>")
        rows.append("<hr>")
        rows.append(
            f"<p style='color:{TEXT_DIM};line-height:1.6'>"
            "网格按 <b>M/r</b> 引力势下陷：质量越大、距离越近，凹陷越深。<br>"
            "相对深度为真实值，整体深度按网格格距自动归一化，"
            "因此任何缩放级别下都清晰可见。</p>"
            f"<p style='color:{TEXT_DIM};line-height:1.6'>"
            "提示：把「凹陷来源」切到「仅选中天体」，可把这颗天体的凹陷单独放大观察；"
            "拖动底部时间轴，凹陷会随天体运动而移动。</p>"
            f"<p style='color:{TEXT_DIM};line-height:1.6'>"
            "网格中心跟随相机焦点：聚焦到黑洞或远方恒星时，网格也会移到该处，"
            "便于观察其引力井形状。</p>")
        self.info.setHtml("".join(rows))

    # ---------- 帮助 ----------
    def _show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("引力系统 —— 使用说明")
        dlg.resize(560, 460)
        lay = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(f"""
<h2 style="color:{ACCENT};">引力系统 —— 时空弯曲网格</h2>
<p style="line-height:1.6">用一张网格把引力 / 时空弯曲画出来：天体把所在处的网格压出凹陷，
质量越大、距离越近，凹陷越深。这是广义相对论「大质量天体弯曲时空」的经典示意图。</p>

<h3>凹陷深度怎么来的</h3>
<table>
<tr><td><b>深度公式</b></td><td>每个网格顶点按 Σ <b>M / r</b> 累加（M 为天体质量，r 为到该顶点的距离）</td></tr>
<tr><td><b>相对深度</b></td><td>真实比例：太阳的凹陷远深于行星（太阳约 33 万倍地球质量）</td></tr>
<tr><td><b>整体深度</b></td><td>按当前网格格距自动归一化，缩放时凹陷始终可见；可用「凹陷强度」再乘倍率</td></tr>
<tr><td><b>软化长度</b></td><td>取网格格距的 3 倍：避免天体正中心出现无穷深的尖刺，并让井壁跨越多格平滑过渡
（软化长度不足时井壁只落在一两格内，会呈折棱/锯齿）</td></tr>
<tr><td><b>网格密度</b></td><td>每轴格数（标准 64 / 高 96 / 极高 128 / 超精细 192）：越高井壁越平滑，顶点数按平方增长</td></tr>
</table>

<h3>操作</h3>
<table>
<tr><td><b>凹陷来源</b></td><td>全部天体（真实 M/r）／仅选中天体（把该天体的凹陷自动放大，便于单独观察）</td></tr>
<tr><td><b>选中天体</b></td><td>点左侧天体树，或直接在视口中点击；相机随之聚焦</td></tr>
<tr><td><b>锁定跟随</b></td><td>相机焦点锁定选中天体，随时间移动时凹陷不跑出视野</td></tr>
<tr><td><b>中键拖拽 / 滚轮</b></td><td>旋转 / 缩放（Blender 式视角）</td></tr>
<tr><td><b>底部时间轴</b></td><td>播放 / 倍速 / 日期跳转，观察凹陷随天体运动变化</td></tr>
<tr><td><b>按需渲染</b></td><td>省算力开关（默认开）：空闲时降到低帧率重绘，拖动/缩放/选中时自动恢复满帧。网格为静态示意，低帧率下依然平滑</td></tr>
</table>

<p style="color:{TEXT_DIM};">说明：网格为示意，不代表真实时空度规；系外行星距离太阳系为秒差距量级，不参与本网格。</p>
""")
        lay.addWidget(text)
        dlg.exec_()