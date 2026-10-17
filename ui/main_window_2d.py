"""
main_window_2d.py —— 二维平面视图窗口

与三维主窗口（ui/main_window.py）并列的第二种主视图：
    ┌──────────────────────────────────────────────────────┐
    │ 顶部工具栏：搜索 | 显示开关 | 视野控制 | 帮助/切换模式 │
    ├──────────┬──────────────────────────┬────────────────┤
    │ 天体树   │   二维平面视口（俯视）   │ 详情/对比/…    │
    ├──────────┴──────────────────────────┴────────────────┤
    │ 时间轴（底部）                                       │
    └──────────────────────────────────────────────────────┘

右侧分析面板与三维窗口完全复用（二维视口实现了同名接口）。
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QSplitter,
                             QLineEdit, QCheckBox, QLabel, QTabWidget,
                             QDialog, QTextEdit, QToolBar, QAction)

from scene.viewport2d import Viewport2D
from ui import dark_titlebar
from ui.resource import icon_path
from ui.style import TEXT_DIM
from ui.timeline import Timeline
from ui.tree_panel import TreePanel
from ui.detail_panel import DetailPanel
from ui.distance_panel import DistancePanel
from ui.phenomena_panel import PhenomenaPanel
from ui.surface_panel import SurfacePanel
from ui.ai_panel import AIPanel
from ui.lazy_tabs import LazyTabManager
from core.i18n import tr


class MainWindow2D(QMainWindow):
    """二维平面视图窗口：俯视黄道面的轨道图"""

    def __init__(self, bodies, stars, on_switch_mode=None):
        super().__init__()
        self.bodies = bodies
        self.stars = stars
        self._on_switch_mode = on_switch_mode
        self.setWindowTitle("Astrarium —— 二维平面视图（俯视黄道面）")
        self.setWindowIcon(QIcon(icon_path()))
        self.resize(1400, 900)

        self._build_ui()
        self._connect_signals()
        self._start_timers()

    # ---------- 组装 ----------
    def _build_ui(self):
        self.addToolBar(self._build_toolbar())

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        self.tree_panel = TreePanel(self.bodies)
        splitter.addWidget(self.tree_panel)

        self.viewport = Viewport2D()
        self.viewport.load_bodies(self.bodies, self.stars)
        splitter.addWidget(self.viewport)

        right_tabs = QTabWidget()
        self.detail_panel = DetailPanel(self.viewport)
        right_tabs.addTab(self.detail_panel, "详情")
        # matplotlib 面板懒加载：首次切入标签页或代码访问时才构造
        self._lazy = LazyTabManager(right_tabs)
        self._lazy.add_lazy_tab("compare", "对比分析",
                                lambda: self._new_mpl_panel("compare"),
                                self._on_mpl_panel_created)
        self.distance_panel = DistancePanel(self.viewport, self.bodies)
        right_tabs.addTab(self.distance_panel, "测距")
        self.phenomena_panel = PhenomenaPanel(self.viewport, self.bodies)
        right_tabs.addTab(self.phenomena_panel, "天象推演")
        self._lazy.add_lazy_tab("exo_obs", "观测特征",
                                lambda: self._new_mpl_panel("exo_obs"),
                                self._on_mpl_panel_created)
        self._lazy.add_lazy_tab("sci", "科研计算",
                                lambda: self._new_mpl_panel("sci"),
                                self._on_mpl_panel_created)
        self._lazy.add_lazy_tab("sky", "地面视角",
                                lambda: self._new_mpl_panel("sky"),
                                self._on_mpl_panel_created)
        self.surface_panel = SurfacePanel(self.viewport, self.bodies, self.stars)
        right_tabs.addTab(self.surface_panel, "地表视角")
        self.ai_panel = AIPanel()
        right_tabs.addTab(self.ai_panel, tr("天文助手"))
        self.detail_panel.surface_panel = self.surface_panel
        self.detail_panel.right_tabs = right_tabs
        splitter.addWidget(right_tabs)

        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([220, 720, 440])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter, 1)

        self.timeline = Timeline(self.viewport.clock)
        main_layout.addWidget(self.timeline)

        self.setCentralWidget(central)

    def _build_toolbar(self):
        tb = QToolBar("二维工具栏")
        tb.setMovable(False)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索天体…")
        self.search_box.setMaximumWidth(200)
        self.search_box.returnPressed.connect(self._search_body)
        tb.addWidget(QLabel("  搜索: "))
        tb.addWidget(self.search_box)

        tb.addSeparator()

        self.chk_orbits = QCheckBox("轨道线")
        self.chk_orbits.setChecked(True)
        self.chk_orbits.toggled.connect(self._toggle_orbits)
        tb.addWidget(self.chk_orbits)

        self.chk_labels = QCheckBox("标签")
        self.chk_labels.setChecked(True)
        self.chk_labels.toggled.connect(self._toggle_labels)
        tb.addWidget(self.chk_labels)

        self.chk_grid = QCheckBox("网格")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self._toggle_grid)
        tb.addWidget(self.chk_grid)

        self.chk_nebula = QCheckBox("星云")
        self.chk_nebula.setChecked(True)
        self.chk_nebula.setToolTip("显示背景星云（程序化生成，零运行时 CPU 开销）")
        self.chk_nebula.toggled.connect(self._toggle_nebula)
        tb.addWidget(self.chk_nebula)

        self.chk_ondemand = QCheckBox("按需渲染")
        self.chk_ondemand.setChecked(True)
        self.chk_ondemand.setToolTip(
            "省算力：空闲时降到低帧率重绘，拖动/缩放/选中聚焦天体时自动恢复满帧。\n"
            "关闭则始终满帧渲染。运动速度不受影响（时间仍按真实 dt 推进）")
        self.chk_ondemand.toggled.connect(self._toggle_on_demand)
        tb.addWidget(self.chk_ondemand)

        self.chk_moons = QCheckBox("卫星")
        self.chk_moons.setChecked(True)
        self.chk_moons.setToolTip("显示天然卫星及其轨道\n（需拉近到行星系，每 AU 像素数足够大时才出现）")
        self.chk_moons.toggled.connect(self._toggle_moons)
        tb.addWidget(self.chk_moons)

        self.chk_follow = QCheckBox("锁定跟随")
        self.chk_follow.setChecked(False)
        self.chk_follow.setToolTip(
            "开启后视图中心每帧锁定到被聚焦天体，天体移动也不会跑出视野\n"
            "聚焦任意天体（搜索/树/双击）会自动开启；手动平移会自动解除")
        self.chk_follow.toggled.connect(self._toggle_follow)
        tb.addWidget(self.chk_follow)

        tb.addSeparator()

        act_reset = QAction("复位视野", self)
        act_reset.setToolTip("回到太阳居中的全景视野")
        act_reset.triggered.connect(lambda: self.viewport.reset_view())
        tb.addAction(act_reset)

        act_zin = QAction("放大", self)
        act_zin.triggered.connect(lambda: self.viewport.zoom_by(1.6))
        tb.addAction(act_zin)

        act_zout = QAction("缩小", self)
        act_zout.triggered.connect(lambda: self.viewport.zoom_by(1.0 / 1.6))
        tb.addAction(act_zout)

        tb.addSeparator()

        act_help = QAction("帮助 (F1)", self)
        act_help.setShortcut("F1")
        act_help.triggered.connect(self._show_help)
        tb.addAction(act_help)

        act_switch = QAction("切换模式", self)
        act_switch.setToolTip("返回模式选择（3D / 2D）")
        act_switch.triggered.connect(self._switch_mode)
        tb.addAction(act_switch)

        act_settings = QAction("设置", self)
        act_settings.setToolTip("打开设置面板（显示模式、帧率限制等）")
        act_settings.triggered.connect(self._show_settings)
        tb.addAction(act_settings)

        return tb

    def _connect_signals(self):
        self.tree_panel.bodyClicked.connect(self._on_tree_click)
        self.tree_panel.systemClicked.connect(self._on_system_click)
        self.viewport.bodySelected.connect(self._on_viewport_select)
        self.viewport.followChanged.connect(self._on_follow_changed)
        self.timeline.dateChanged.connect(self._on_date_jump)
        self.phenomena_panel.jumpRequested.connect(self._on_phenomena_jump)

    def _start_timers(self):
        # sky_panel.tick 在面板懒创建后连接
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self.timeline.tick)
        self._ui_timer.timeout.connect(self.surface_panel.tick)
        self._ui_timer.start(500)

    # ---------- matplotlib 面板懒加载 ----------
    def _new_mpl_panel(self, key):
        """按需 import 并构造 matplotlib 面板（import 放函数内，避免启动即加载）"""
        if key == "compare":
            from ui.compare_panel import ComparePanel
            return ComparePanel(self.viewport.clock, self.bodies)
        if key == "exo_obs":
            from ui.exo_obs_panel import ExoObsPanel
            return ExoObsPanel(self.viewport, self.bodies)
        if key == "sci":
            from ui.sci_panel import SciPanel
            return SciPanel()
        if key == "sky":
            from ui.sky_panel import SkyPanel
            return SkyPanel(self.viewport, self.bodies, self.stars)
        raise KeyError(key)

    def _on_mpl_panel_created(self, key, panel):
        """面板懒创建完成后的依赖注入 / 信号连接"""
        if key == "compare":
            self.detail_panel.compare_panel = panel
        elif key == "exo_obs":
            self.detail_panel.exo_obs_panel = panel
            body = getattr(self.detail_panel, "_body", None)
            if body is not None:
                panel.set_body(body)
        elif key == "sky":
            self.detail_panel.sky_panel = panel
            self._ui_timer.timeout.connect(panel.tick)
        # sci 面板无外部依赖

    def showEvent(self, ev):
        dark_titlebar.apply_dark_titlebar(self)
        if not self._ui_timer.isActive():
            self._ui_timer.start(500)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._ui_timer.stop()
        super().hideEvent(ev)

    # ---------- 事件 ----------
    def _on_tree_click(self, body):
        self.viewport.focus_body_by_name(body.name)
        self.detail_panel.show_body(body)
        exo = self._lazy.get("exo_obs")
        if exo is not None:
            exo.set_body(body)
        self.viewport.update()

    def _on_system_click(self, group):
        self.detail_panel.show_system(group)

    def _on_viewport_select(self, body):
        self.detail_panel.show_body(body)
        self.tree_panel.select_body(body.name)
        exo = self._lazy.get("exo_obs")
        if exo is not None:
            exo.set_body(body)
        self.viewport.focus_body_by_name(body.name)
        self._set_ai_context(body)

    def _set_ai_context(self, body):
        """把当前选中天体告知「天文助手」，使回答更贴合画面。"""
        if body is None or not getattr(self, "ai_panel", None):
            return
        try:
            from data.loader import BODY_TYPE_LABELS
            name = getattr(body, "name", "") or ""
            btype = getattr(body, "body_type", "") or ""
            kind = BODY_TYPE_LABELS.get(btype, btype)
            parts = ["当前选中天体：%s（%s）" % (name, kind)] if kind else \
                    ["当前选中天体：%s" % name]
            host = getattr(body, "host", "")
            if host:
                parts.append("宿主：%s" % host)
            if getattr(body, "a_au", None):
                parts.append("轨道半长轴：%.3f AU" % body.a_au)
            if getattr(body, "period_days", None):
                parts.append("公转周期：%.2f 天" % body.period_days)
            if getattr(body, "radius_km", None):
                parts.append("半径：%.0f km" % body.radius_km)
            if getattr(body, "mass_earth", None):
                parts.append("质量：%.3f 地球质量" % body.mass_earth)
            if getattr(body, "dist_pc", None):
                parts.append("距离：%.2f pc" % body.dist_pc)
            if getattr(body, "disc_year", None):
                parts.append("发现年份：%d" % body.disc_year)
            self.ai_panel.set_context("；".join(parts))
        except Exception:
            pass

    def _on_date_jump(self, jd):
        self.viewport.update()
        sky = self._lazy.get("sky")
        if sky is not None:
            sky._sync_from_clock()
        self.surface_panel._sync_from_clock()

    def _on_phenomena_jump(self, jd, focus_name):
        self.viewport.clock.jump_to(jd)
        self.timeline._refresh()
        if focus_name:
            body = next((b for b in self.bodies if b.name == focus_name), None)
            if body is not None:
                self.viewport.focus_body_by_name(body.name)
                self.detail_panel.show_body(body)
                self.tree_panel.select_body(body.name)
        self.viewport.update()

    def _search_body(self):
        text = self.search_box.text().strip()
        if not text:
            return
        self.tree_panel.edit_search.setText(text)
        low = text.lower()
        for b in self.bodies:
            if low in b.name.lower() or low in (b.en_name or "").lower():
                self.viewport.focus_body_by_name(b.name)
                self.detail_panel.show_body(b)
                self.tree_panel.select_body(b.name)
                self.viewport.update()
                return

    def _toggle_orbits(self, on):
        self.viewport.show_orbits = on
        self.viewport.update()

    def _toggle_labels(self, on):
        self.viewport.show_labels = on
        self.viewport.update()

    def _toggle_grid(self, on):
        self.viewport.show_grid = on
        self.viewport.update()

    def _toggle_nebula(self, on):
        self.viewport.show_nebula = on
        self.viewport.update()

    def _toggle_on_demand(self, on):
        self.viewport.set_on_demand(on)

    def _toggle_moons(self, on):
        self.viewport.show_moons = on
        self.viewport.update()

    def _toggle_follow(self, on):
        self.viewport.set_follow(on)

    def _on_follow_changed(self, on):
        if self.chk_follow.isChecked() != bool(on):
            self.chk_follow.blockSignals(True)
            self.chk_follow.setChecked(bool(on))
            self.chk_follow.blockSignals(False)

    def _switch_mode(self):
        if self._on_switch_mode is not None:
            self._on_switch_mode()

    def _show_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=self, viewport=self.viewport)
        dlg.exec_()

    # ---------- 帮助 ----------
    def _show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("快捷键帮助 —— 二维平面视图")
        dlg.resize(520, 420)
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(f"""
<h2 style="color:#e87d0d;">二维平面视图 —— 操作指南</h2>

<h3>视图控制</h3>
<table cellpadding="4">
<tr><td><b>拖拽</b></td><td>平移视野（自动解除锁定跟随）</td></tr>
<tr><td><b>滚轮</b></td><td>缩放，以光标位置为中心</td></tr>
<tr><td><b>单击</b></td><td>选中天体（同步详情/天体树）</td></tr>
<tr><td><b>双击</b></td><td>聚焦天体并开启锁定跟随</td></tr>
<tr><td><b>复位视野</b></td><td>回到太阳居中的全景（工具栏）</td></tr>
<tr><td><b>按需渲染</b></td><td>省算力开关（默认开）：空闲时降到低帧率重绘，拖动/缩放/选中聚焦天体时自动恢复满帧；关闭则始终满帧。运动速度不受影响</td></tr>
</table>

<h3>绘制内容</h3>
<p>俯视 J2000 黄道面，太阳位于原点，天体位置取黄道面投影 (x, y)。
画出各行星/矮行星轨道椭圆；网格环为日心距刻度，随缩放自适应。
天然卫星需拉近到行星系（每 AU 像素数足够大）才显示。</p>

<h3>科学说明</h3>
<p>轨道为开普勒二体近似的平面投影，忽略轨道倾角造成的垂直分量。
系外行星位于秒差距级距离，不在本太阳系平面视图内绘制。</p>

<h3>右侧分析面板</h3>
<p>与三维视图完全一致：详情 / 对比分析 / 测距 / 天象推演 / 观测特征 / 地面视角 / 地表视角。
其中「地表视角」可站到任一行星或卫星表面，第一人称环视天空（天空底色随太阳高度变化，
亮星为柔和光晕，地平线为静态地形剪影）。</p>

<p style="color:{TEXT_DIM};">时间由底部时间轴统一控制，与三维视图使用同一套仿真时钟逻辑。</p>
""")
        layout.addWidget(text)
        dlg.exec_()