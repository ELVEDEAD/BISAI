"""
main_window.py —— 主窗口组装（模块 G）

布局：
    ┌──────────────────────────────────────────────────────┐
    │ 顶部工具栏：搜索 | 显示开关 | 比例切换 | 帮助        │
    ├──────────┬──────────────────────────┬────────────────┤
    │ 天体树   │                          │ 详情面板       │
    │ (左侧)   │     三维主视口           │ 对比面板       │
    │          │                          │ (右侧 Tab)     │
    ├──────────┴──────────────────────────┴────────────────┤
    │ 时间轴（底部）                                       │
    └──────────────────────────────────────────────────────┘

快捷键：
    F1     帮助对话框
    空格   播放/暂停
    Ctrl+F 搜索聚焦
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QSplitter, QLineEdit, QPushButton, QCheckBox,
                             QLabel, QTabWidget, QDialog, QTextEdit,
                             QToolBar, QAction, QComboBox)

from scene.viewport import Viewport
from ui import style
from core import i18n
from core.i18n import tr
from ui.timeline import Timeline
from ui.tree_panel import TreePanel
from ui.detail_panel import DetailPanel
from ui.compare_panel import ComparePanel
from ui.distance_panel import DistancePanel
from ui.phenomena_panel import PhenomenaPanel
from ui.exo_obs_panel import ExoObsPanel
from ui.sky_panel import SkyPanel
from ui.surface_panel import SurfacePanel
from ui.guide import GuideDialog, should_show_guide, mark_guide_completed
from ui.teaching_scenes import TeachingSceneDialog
from ui.settings_dialog import SettingsDialog
from core.time_system import SimulationClock


class MainWindow(QMainWindow):
    """主窗口：组装所有面板与视口"""

    def __init__(self, bodies, stars):
        super().__init__()
        self.bodies = bodies
        self.stars = stars
        self._switch_cb = None      # 启动器注入：返回模式选择
        self.setWindowTitle(tr("已知行星可视化 —— 太阳系 + 系外行星"))
        self.resize(1400, 900)

        self._build_ui()
        self._connect_signals()
        self._start_timers()
        self._maybe_show_guide()

        # 语言 / 主题变化时即时重建界面文字与内联样式
        i18n.add_listener(self.retranslate)
        style.add_theme_listener(self.restyle)

    def closeEvent(self, ev):
        i18n.remove_listener(self.retranslate)
        style.remove_theme_listener(self.restyle)
        super().closeEvent(ev)

    def retranslate(self):
        """按当前语言重建本窗口所有文字（即时生效）。"""
        self.setWindowTitle(tr("已知行星可视化 —— 太阳系 + 系外行星"))
        if getattr(self, "_lbl_search", None) is not None:
            self._lbl_search.setText(f"  {tr('搜索:')} ")
        self.search_box.setPlaceholderText(tr("搜索天体…"))
        for chk, key in (
            (self.chk_orbits, "轨道线"), (self.chk_labels, "标签"),
            (self.chk_grid, "网格"), (self.chk_stars, "背景星"),
            (self.chk_nebula, "星云"), (self.chk_ondemand, "按需渲染"),
            (self.chk_real_scale, "真实比例"), (self.chk_solid, "实体球"),
            (self.chk_follow, "锁定跟随"), (self.chk_moons, "卫星"),
            (self.chk_rings, "行星环"), (self.chk_sats, "人造卫星"),
            (self.chk_axes, "自转轴"), (self.chk_solar, "太阳系轨道"),
            (self.chk_exo, "系外行星轨道"), (self.chk_belt, "小天体"),
        ):
            chk.setText(tr(key))
        # 尾迹 / 密度 / 灵敏度下拉项
        self._retranslate_combo(
            self.cmb_trails, ["尾迹 · 自动清除", "尾迹 · 一直显示", "尾迹 · 关闭"])
        self._retranslate_combo(self.cmb_belt, ["少", "中", "多"])
        self._retranslate_combo(self.cmb_sens, ["很慢", "慢", "标准", "快", "很快"])
        if getattr(self, "_lbl_sens", None) is not None:
            self._lbl_sens.setText(f"  {tr('灵敏度:')} ")
        # 菜单动作
        for act, key in (
            (self.act_help, "帮助 (F1)"), (self.act_teach, "教学场景"),
            (self.act_guide, "新手引导"), (self.act_switch, "切换模式"),
            (self.act_settings, "设置"),
        ):
            act.setText(tr(key))
        # 右侧标签页
        for i, key in enumerate(("详情", "对比分析", "测距", "天象推演",
                                 "观测特征", "地面视角", "地表视角")):
            if i < self.right_tabs.count():
                self.right_tabs.setTabText(i, tr(key))
        # 子面板（若实现了 retranslate）
        for panel in (self.tree_panel, self.timeline, self.detail_panel):
            fn = getattr(panel, "retranslate", None)
            if callable(fn):
                fn()

    @staticmethod
    def _retranslate_combo(combo, keys):
        cur = combo.currentIndex()
        combo.blockSignals(True)
        for i, key in enumerate(keys):
            if i < combo.count():
                combo.setItemText(i, tr(key))
        combo.setCurrentIndex(cur)
        combo.blockSignals(False)

    def restyle(self):
        """主题变化时重建依赖调色板的内联样式（大部分由全局 QSS 覆盖）。"""
        for panel in (self.tree_panel, self.timeline, self.detail_panel):
            fn = getattr(panel, "restyle", None)
            if callable(fn):
                fn()

    def set_switch_callback(self, cb):
        """由启动器注入「切换模式」回调"""
        self._switch_cb = cb

    def _build_ui(self):
        # ---------- 顶部工具栏 ----------
        toolbar = self._build_toolbar()
        self.addToolBar(toolbar)

        # ---------- 中央区域 ----------
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 三栏分拆
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：天体树
        self.tree_panel = TreePanel(self.bodies)
        splitter.addWidget(self.tree_panel)

        # 中央：视口
        self.viewport = Viewport()
        self.viewport.load_bodies(self.bodies, self.stars)
        splitter.addWidget(self.viewport)

        # 右侧：详情 + 对比（Tab）
        right_tabs = QTabWidget()
        self.right_tabs = right_tabs
        self.detail_panel = DetailPanel(self.viewport)
        right_tabs.addTab(self.detail_panel, tr("详情"))
        self.compare_panel = ComparePanel(self.viewport.clock, self.bodies)
        right_tabs.addTab(self.compare_panel, tr("对比分析"))
        self.detail_panel.compare_panel = self.compare_panel
        self.distance_panel = DistancePanel(self.viewport, self.bodies)
        right_tabs.addTab(self.distance_panel, tr("测距"))
        self.phenomena_panel = PhenomenaPanel(self.viewport, self.bodies)
        right_tabs.addTab(self.phenomena_panel, tr("天象推演"))
        self.exo_obs_panel = ExoObsPanel(self.viewport, self.bodies)
        right_tabs.addTab(self.exo_obs_panel, tr("观测特征"))
        self.sky_panel = SkyPanel(self.viewport, self.bodies, self.stars)
        right_tabs.addTab(self.sky_panel, tr("地面视角"))
        self.surface_panel = SurfacePanel(self.viewport, self.bodies, self.stars)
        right_tabs.addTab(self.surface_panel, tr("地表视角"))
        self.detail_panel.exo_obs_panel = self.exo_obs_panel
        self.detail_panel.sky_panel = self.sky_panel
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

        # 底部时间轴
        self.timeline = Timeline(self.viewport.clock)
        main_layout.addWidget(self.timeline)

        self.setCentralWidget(central)

        # 同步工具栏控件状态到视口（工具栏在视口之前构建，信号未触发）
        self._on_belt()
        self._on_sensitivity()

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize())

        # 搜索
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("搜索天体…"))
        self.search_box.setMaximumWidth(200)
        self.search_box.returnPressed.connect(self._search_body)
        self._lbl_search = QLabel(f"  {tr('搜索:')} ")
        tb.addWidget(self._lbl_search)
        tb.addWidget(self.search_box)

        tb.addSeparator()

        # 显示开关
        self.chk_orbits = QCheckBox(tr("轨道线"))
        self.chk_orbits.setChecked(True)
        self.chk_orbits.toggled.connect(self._toggle_orbits)
        tb.addWidget(self.chk_orbits)

        self.chk_labels = QCheckBox(tr("标签"))
        self.chk_labels.setChecked(True)
        self.chk_labels.toggled.connect(self._toggle_labels)
        tb.addWidget(self.chk_labels)

        self.chk_grid = QCheckBox(tr("网格"))
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self._toggle_grid)
        tb.addWidget(self.chk_grid)

        self.chk_stars = QCheckBox(tr("背景星"))
        self.chk_stars.setChecked(True)
        self.chk_stars.toggled.connect(self._toggle_stars)
        tb.addWidget(self.chk_stars)

        self.chk_nebula = QCheckBox(tr("星云"))
        self.chk_nebula.setChecked(True)
        self.chk_nebula.setToolTip("显示背景星云（程序化体积云效果，零 CPU 每帧开销）")
        self.chk_nebula.toggled.connect(self._toggle_nebula)
        tb.addWidget(self.chk_nebula)

        self.chk_ondemand = QCheckBox(tr("按需渲染"))
        self.chk_ondemand.setChecked(True)
        self.chk_ondemand.setToolTip(
            "省算力：空闲时降到低帧率重绘，远处天体（系外行星/宿主恒星/黑洞）\n"
            "降频重算位置；拖动视角、选中/聚焦天体时自动恢复满帧。\n"
            "关闭则始终满帧渲染。运动速度不受影响（时间仍按真实 dt 推进）")
        self.chk_ondemand.toggled.connect(self._toggle_on_demand)
        tb.addWidget(self.chk_ondemand)

        self.cmb_trails = QComboBox()
        self.cmb_trails.addItems([tr("尾迹 · 自动清除"), tr("尾迹 · 一直显示"), tr("尾迹 · 关闭")])
        self.cmb_trails.setToolTip(
            "自动清除：只保留最近一段轨迹并向后渐隐，随时间自动消失（默认）\n"
            "一直显示：保留完整历史轨迹，不自动清除\n"
            "关闭：不显示尾迹")
        self.cmb_trails.currentIndexChanged.connect(self._on_trail_mode)
        tb.addWidget(self.cmb_trails)

        tb.addSeparator()

        # 比例模式
        self.chk_real_scale = QCheckBox(tr("真实比例"))
        self.chk_real_scale.setChecked(False)
        self.chk_real_scale.setToolTip(
            "真实比例：实体球按真实半径，标记点下限更小\n"
            "可视化比例：远距天体以放大标记点显示，近距自动切换为实体球\n"
            "（系外行星位于秒差距级距离，一律以细小光点显示，拉近到该行星系才按真实半径显示）")
        self.chk_real_scale.toggled.connect(self._toggle_scale)
        tb.addWidget(self.chk_real_scale)

        self.chk_solid = QCheckBox(tr("实体球"))
        self.chk_solid.setChecked(True)
        self.chk_solid.setToolTip(
            "天体按真实半径绘制为实体球（含光照与程序化表面贴图）\n"
            "贴图随自转轴定向、随时间轴自转：地球海陆、木星/土星条带、\n"
            "火星/月球斑驳、金星浓云、恒星颗粒\n"
            "靠近时球体自然放大直至填满视野；关闭则全部用点标记")
        self.chk_solid.toggled.connect(self._toggle_solid)
        tb.addWidget(self.chk_solid)

        self.chk_follow = QCheckBox(tr("锁定跟随"))
        self.chk_follow.setChecked(False)
        self.chk_follow.setToolTip(
            "开启后相机焦点每帧锁定到被聚焦天体的当前位置，天体移动也不会跑出视野\n"
            "聚焦任意天体（搜索/树/右键）会自动开启；平移视角或进入飞行模式会自动解除")
        self.chk_follow.toggled.connect(self._toggle_follow)
        tb.addWidget(self.chk_follow)

        self.chk_moons = QCheckBox(tr("卫星"))
        self.chk_moons.setChecked(True)
        self.chk_moons.setToolTip(
            "显示天然卫星（月球、伽利略卫星、土卫六等）及其轨道\n"
            "拉近到行星系（母行星视直径足够大）时才出现")
        self.chk_moons.toggled.connect(self._toggle_moons)
        tb.addWidget(self.chk_moons)

        self.chk_rings = QCheckBox(tr("行星环"))
        self.chk_rings.setChecked(True)
        self.chk_rings.setToolTip(
            "显示行星环（土星主环系含真实环带结构、木星/天王星/海王星暗环）\n"
            "按母行星真实极轴方向定向，拉近时淡入")
        self.chk_rings.toggled.connect(self._toggle_rings)
        tb.addWidget(self.chk_rings)

        self.chk_sats = QCheckBox(tr("人造卫星"))
        self.chk_sats.setChecked(True)
        self.chk_sats.setToolTip(
            "显示人类发射的地球人造卫星（国际空间站、天宫、哈勃、星链、\n"
            "导航/气象/遥感卫星等）及其真实轨道面\n"
            "仅在拉近到地球（地球视直径足够大）时出现，避免远景杂乱与额外开销；\n"
            "关闭可完全省去这部分渲染")
        self.chk_sats.toggled.connect(self._toggle_sats)
        tb.addWidget(self.chk_sats)

        self.chk_axes = QCheckBox(tr("自转轴"))
        self.chk_axes.setChecked(True)
        self.chk_axes.setToolTip(
            "显示行星自转轴（青）、赤道面圆环（琥珀）与随自转转动的子午线（灰）\n"
            "极轴按 IAU 真实极轴方向定向，子午线随时间轴自转，可直观看到转轴倾角")
        self.chk_axes.toggled.connect(self._toggle_axes)
        tb.addWidget(self.chk_axes)

        tb.addSeparator()

        # 轨迹筛选
        self.chk_solar = QCheckBox(tr("太阳系轨道"))
        self.chk_solar.setChecked(True)
        self.chk_solar.toggled.connect(self._apply_filter)
        tb.addWidget(self.chk_solar)

        self.chk_exo = QCheckBox(tr("系外行星轨道"))
        self.chk_exo.setChecked(True)
        self.chk_exo.toggled.connect(self._apply_filter)
        tb.addWidget(self.chk_exo)

        self.chk_belt = QCheckBox(tr("小天体"))
        self.chk_belt.setChecked(True)
        self.chk_belt.setToolTip(
            "太阳系小天体点云：近地小行星 / 主带 / 希尔达群 / 木星特洛伊 /\n"
            "半人马 / 柯伊伯带 / 离散盘（轨道根数送 GPU，位置实时求解）")
        self.chk_belt.toggled.connect(self._on_belt)
        tb.addWidget(self.chk_belt)

        self.cmb_belt = QComboBox()
        self.cmb_belt.setToolTip("小天体密度：预生成 10 万颗，此处只改绘制数量（各族群按比例保留）")
        for _label, _val in (("少", 20000), ("中", 50000), ("多", 100000)):
            self.cmb_belt.addItem(tr(_label), _val)
        self.cmb_belt.setCurrentIndex(1)
        self.cmb_belt.currentIndexChanged.connect(self._on_belt)
        tb.addWidget(self.cmb_belt)

        tb.addSeparator()

        # 视角灵敏度（拖拽旋转/平移速度）
        self._lbl_sens = QLabel(f"  {tr('灵敏度:')} ")
        tb.addWidget(self._lbl_sens)
        self.cmb_sens = QComboBox()
        self.cmb_sens.setToolTip("鼠标拖拽旋转/平移的灵敏度（标准 = 1.0 倍）")
        for _label, _val in (("很慢", 0.25), ("慢", 0.5), ("标准", 1.0),
                             ("快", 2.0), ("很快", 4.0)):
            self.cmb_sens.addItem(tr(_label), _val)
        self.cmb_sens.setCurrentIndex(2)
        self.cmb_sens.currentIndexChanged.connect(self._on_sensitivity)
        tb.addWidget(self.cmb_sens)

        tb.addSeparator()

        # 帮助
        self.act_help = QAction(tr("帮助 (F1)"), self)
        self.act_help.setShortcut("F1")
        self.act_help.triggered.connect(self._show_help)
        tb.addAction(self.act_help)

        # 教学
        self.act_teach = QAction(tr("教学场景"), self)
        self.act_teach.triggered.connect(self._show_teaching)
        tb.addAction(self.act_teach)

        # 新手引导
        self.act_guide = QAction(tr("新手引导"), self)
        self.act_guide.triggered.connect(self._show_guide)
        tb.addAction(self.act_guide)

        # 切换模式（返回启动器：3D / 2D / 引力系统）
        self.act_switch = QAction(tr("切换模式"), self)
        self.act_switch.setToolTip("返回模式选择（3D / 2D / 引力系统）")
        self.act_switch.triggered.connect(self._switch_mode)
        tb.addAction(self.act_switch)

        # 设置
        self.act_settings = QAction(tr("设置"), self)
        self.act_settings.setToolTip("打开设置面板（显示模式、帧率限制、语言、主题等）")
        self.act_settings.triggered.connect(self._show_settings)
        tb.addAction(self.act_settings)

        return tb

    def _switch_mode(self):
        if self._switch_cb is not None:
            self._switch_cb()

    def _connect_signals(self):
        # 树点击 → 视口选中 + 详情面板
        self.tree_panel.bodyClicked.connect(self._on_tree_click)
        # 树点击恒星系节点 → 详情面板显示恒星系概览
        self.tree_panel.systemClicked.connect(self._on_system_click)
        # 视口选中 → 详情面板
        self.viewport.bodySelected.connect(self._on_viewport_select)
        # 视口对比切换 → 刷新
        self.viewport.compareToggled.connect(self._on_compare_toggle)
        # 视口锁定跟随状态 → 同步工具栏复选框
        self.viewport.followChanged.connect(self._on_follow_changed)
        # 时间轴跳转 → 视口刷新
        self.timeline.dateChanged.connect(self._on_date_jump)
        # 天象事件点击 → 跳转时间轴 + 聚焦相关天体
        self.phenomena_panel.jumpRequested.connect(self._on_phenomena_jump)

    def _start_timers(self):
        # 时间轴日期刷新（500ms）
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self.timeline.tick)
        self._ui_timer.timeout.connect(self.sky_panel.tick)
        self._ui_timer.timeout.connect(self.surface_panel.tick)
        self._ui_timer.start(500)

    def showEvent(self, ev):
        if not self._ui_timer.isActive():
            self._ui_timer.start(500)
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._ui_timer.stop()
        super().hideEvent(ev)

    # ---------- 事件处理 ----------
    def _on_tree_click(self, body):
        self.viewport.selected_name = body.name
        self.viewport.focus_body_by_name(body.name)
        self.detail_panel.show_body(body)
        self.exo_obs_panel.set_body(body)
        self.viewport.update()

    def _on_system_click(self, group):
        """点击恒星系节点：详情面板显示恒星系概览（宿主恒星参数 + 成员行星）"""
        self.detail_panel.show_system(group)

    def _on_viewport_select(self, body):
        """主视口单击天体：选中 + 详情 + 树同步 + 把相机焦点切到该天体"""
        self.detail_panel.show_body(body)
        self.tree_panel.select_body(body.name)
        self.exo_obs_panel.set_body(body)
        self.viewport.focus_body_by_name(body.name)

    def _on_compare_toggle(self, body):
        self.viewport.update()

    def _on_date_jump(self, jd):
        self.viewport.invalidate_far()
        self.viewport.update()
        self.sky_panel._sync_from_clock()
        self.surface_panel._sync_from_clock()

    def _on_phenomena_jump(self, jd, focus_name):
        """点击天象事件：时间轴跳到事件时刻，并聚焦相关天体"""
        self.viewport.clock.jump_to(jd)
        self.viewport.invalidate_far()
        self.timeline._refresh()
        if focus_name:
            body = next((b for b in self.bodies if b.name == focus_name), None)
            if body is not None:
                self.viewport.selected_name = body.name
                self.viewport.focus_body_by_name(body.name)
                self.detail_panel.show_body(body)
                self.tree_panel.select_body(body.name)
        self.viewport.update()

    def _search_body(self):
        text = self.search_box.text().strip()
        if not text:
            return
        # 先在树中搜索
        self.tree_panel.edit_search.setText(text)
        # 尝试匹配并聚焦
        for b in self.bodies:
            if text.lower() in b.name.lower() or text.lower() in (b.en_name or "").lower():
                self.viewport.selected_name = b.name
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

    def _toggle_stars(self, on):
        self.viewport.show_stars = on
        self.viewport.update()

    def _toggle_nebula(self, on):
        self.viewport.show_nebula = on
        self.viewport.update()

    def _toggle_on_demand(self, on):
        self.viewport.set_on_demand(on)

    def _on_trail_mode(self, idx):
        vp = self.viewport
        if idx == 0:      # 自动清除
            vp.trail_mode = "clear"
            vp.show_trails = True
        elif idx == 1:    # 一直显示
            vp.trail_mode = "persist"
            vp.show_trails = True
        else:             # 关闭
            vp.show_trails = False
        vp.update()

    def _toggle_scale(self, on):
        self.viewport.real_scale = on
        self.viewport.update()

    def _toggle_solid(self, on):
        self.viewport.set_solid(on)

    def _toggle_follow(self, on):
        self.viewport.set_follow(on)

    def _toggle_moons(self, on):
        self.viewport.show_moons = on
        self.viewport.update()

    def _toggle_rings(self, on):
        self.viewport.show_rings = on
        self.viewport.update()

    def _toggle_sats(self, on):
        self.viewport.show_satellites = on
        self.viewport.update()

    def _toggle_axes(self, on):
        self.viewport.set_axes(on)
        self.viewport.update()

    def _on_follow_changed(self, on):
        """视口侧（平移/飞行/回到原点）自动解除时同步复选框状态"""
        if self.chk_follow.isChecked() != bool(on):
            self.chk_follow.blockSignals(True)
            self.chk_follow.setChecked(bool(on))
            self.chk_follow.blockSignals(False)

    def _apply_filter(self):
        self.viewport.set_orbit_filter(
            solar=self.chk_solar.isChecked(),
            exo=self.chk_exo.isChecked())

    def _on_sensitivity(self):
        vp = getattr(self, "viewport", None)
        val = self.cmb_sens.currentData()
        if vp is not None and val is not None:
            vp.camera.set_sensitivity(val)

    def _on_belt(self):
        vp = getattr(self, "viewport", None)
        val = self.cmb_belt.currentData()
        if vp is not None and val is not None:
            vp.set_belt(self.chk_belt.isChecked(), val)

    def _show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("快捷键帮助")
        dlg.resize(520, 480)
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml("""
<h2 style="color:#e87d0d;">已知行星可视化 —— 快捷键与操作指南</h2>

<h3>视角控制（Blender 式）</h3>
<table>
<tr><td><b>中键拖拽</b></td><td>旋转视角（轨道模式）</td></tr>
<tr><td><b>Shift+中键</b></td><td>平移视角</td></tr>
<tr><td><b>滚轮</b></td><td>对数缩放（远近自适应）</td></tr>
<tr><td><b>左键点击天体</b></td><td>选中并显示详情，同时把相机焦点切换到该天体（不再固定为太阳）</td></tr>
<tr><td><b>F 键</b></td><td>锁定/解锁当前选中天体。锁定后点击其他天体不会切换选中，防止误操作（HUD 显示"已锁定"提示）</td></tr>
<tr><td><b>右键</b></td><td>上下文菜单（聚焦 / 锁定跟随 / 对比 / 回到原点）</td></tr>
<tr><td><b>顶部"灵敏度"</b></td><td>调整拖拽旋转/平移速度（很慢~很快）</td></tr>
<tr><td><b>顶部"小天体"</b></td><td>太阳系小天体点云开关（近地小行星 / 主带 / 希尔达群 / 木星特洛伊 / 半人马 / 柯伊伯带 / 离散盘）；
右侧下拉框调密度（少/中/多）</td></tr>
<tr><td><b>顶部"实体球"</b></td><td>天体按真实半径绘制为球体（靠近即"贴脸"），带程序化表面贴图，关闭则用点标记</td></tr>
<tr><td><b>顶部"锁定跟随"</b></td><td>相机焦点每帧锁定到被聚焦天体；聚焦自动开启，平移/飞行自动解除</td></tr>
<tr><td><b>顶部"卫星"</b></td><td>显示天然卫星及其轨道（拉近到行星系时出现）</td></tr>
<tr><td><b>顶部"行星环"</b></td><td>显示行星环（土星真实环带结构，木/天/海王星暗环）</td></tr>
<tr><td><b>顶部"自转轴"</b></td><td>显示行星自转轴（青）、赤道面圆环（琥珀）与随自转转动的子午线（灰）</td></tr>
<tr><td><b>顶部"按需渲染"</b></td><td>省算力开关（默认开）：空闲时降到低帧率重绘，远处天体（系外行星 / 宿主恒星 / 黑洞）降频重算位置；
拖动视角、滚轮缩放、选中或聚焦天体时自动恢复满帧。关闭则始终满帧。运动速度不受影响（时间按真实 dt 推进）</td></tr>
</table>

<h3>测距 / 光行时间（右侧"测距"标签页）</h3>
<table>
<tr><td><b>天体 A / B</b></td><td>任选两个天体（太阳/行星/矮行星/天然卫星）；下拉逐个选，或直接在框内输入名称搜索（子串匹配，回车即算）</td></tr>
<tr><td><b>实时读数</b></td><td>当前距离（AU / km / 光年 / 秒差距）+ 光行时间（光走完这段距离所需时间）</td></tr>
<tr><td><b>相对速度</b></td><td>两天体当前相对速度（km/s）</td></tr>
<tr><td><b>主视口连线</b></td><td>勾选后主视口 A/B 之间画一条青蓝色连线</td></tr>
<tr><td><b>选中→A / B</b></td><td>把主视口当前选中的天体一键设为 A 或 B</td></tr>
</table>

<h3>天象推演（右侧"天象推演"标签页）</h3>
<table>
<tr><td><b>观测点</b></td><td>计算观测位置（默认地球，即地心视位置）</td></tr>
<tr><td><b>天象类型</b></td><td>冲日 / 合日 / 大距 / 方照 / 行星合相 / 凌日</td></tr>
<tr><td><b>日期区间</b></td><td>推演区间（受星历限制 1800–2050），可用"未来 N 年"快捷设定</td></tr>
<tr><td><b>开始推演</b></td><td>列出区间内全部事件（日期时间 / 类型 / 事件 / 详情）</td></tr>
<tr><td><b>点击结果行</b></td><td>主视口时间轴跳到该事件时刻，并聚焦相关天体</td></tr>
</table>
<p style="color:#a0a0a0;">说明：事件由地心视黄经 / 距角解析计算，可复现；受 JPL 近似星历精度限制，
时刻误差约数分钟至数小时。「凌日」几何敏感，标注为候选事件。</p>

<h3>观测特征（右侧"观测特征"标签页）</h3>
<table>
<tr><td><b>天体</b></td><td>任选天体（可输入名称搜索）；由主视口/天体树选中会自动同步</td></tr>
<tr><td><b>凌星光变曲线</b></td><td>亮度随时间的凹陷：深度 = (Rp/Rs)²；阴影带为撞击参数 b∈[0,1] 的全部可能形态（b 未测定）</td></tr>
<tr><td><b>撞击参数 b</b></td><td>拖动滑块改变 b，直观看到「中心凌（深而短）」与「擦边凌（浅而长）」的差别</td></tr>
<tr><td><b>视向速度曲线</b></td><td>恒星谱线摆动，半振幅 K 由质量函数给出（取 sin i = 1，为最小值）；蓝线为其它近心点幅角取向</td></tr>
<tr><td><b>宜居带</b></td><td>Kopparapu 2013 保守 / 乐观边界，并标出同一恒星系各行星的位置</td></tr>
<tr><td><b>参数表</b></td><td>凌星深度、时长区间、K、恒星光通量、宜居带边界与宜居性判定</td></tr>
<tr><td><b>导出 PNG</b></td><td>把当前图表保存为图片</td></tr>
</table>
<p style="color:#a0a0a0;">说明：光变曲线为几何遮挡解析解（不含临边昏暗与行星自身辐射）；
视向速度取 sin i = 1；宜居带适用恒星 2600–7200 K。参数缺失一律标「未知」，不作假设填充。</p>

<h3>地面视角（右侧"地面视角"标签页）</h3>
<table>
<tr><td><b>地点</b></td><td>观测地点（预设城市，可输入名称搜索）；纬度决定星空朝向，经度决定当地恒星时，含赤道与极地样本</td></tr>
<tr><td><b>日期 / 时刻</b></td><td>要查看的当地日期与时刻；勾选"跟随时间轴"时随主视口时间轴自动更新</td></tr>
<tr><td><b>星空图</b></td><td>俯视天球：正北在上、正东在左（抬头观星习惯），圆心为天顶、圆周为地平；标出太阳（含当日日轨线）、各行星、矮行星与背景亮星</td></tr>
<tr><td><b>选中天体</b></td><td>主视口/天体树当前选中的天体若在地平线上方，会以白边高亮并标注名称</td></tr>
<tr><td><b>太阳事件表</b></td><td>日出 / 中天 / 日落 / 昼长 / 正午高度角，以及民用·航海·天文三档暮光；极昼极夜单独标注</td></tr>
<tr><td><b>导出 PNG</b></td><td>把当前星空图保存为图片</td></tr>
</table>
<p style="color:#a0a0a0;">说明：位置取自 JPL 近似星历（1800–2050），高度角误差约 arcmin 级；
未逐点建模大气折射，日出/日落采用 −0.833° 标准判据（含折射 34′ 与日面半径 16′）；
天然卫星相位为假设值，位置无预测意义，故不参与星空绘制。</p>

<h3>地表视角（右侧"地表视角"标签页）</h3>
<table>
<tr><td><b>天体</b></td><td>选择要"站上去"的星球（行星 / 矮行星 / 天然卫星，可输入名称搜索）；仅列出具备自转轴数据、能定出地平坐标系的天体</td></tr>
<tr><td><b>地点 / 纬度 / 经度</b></td><td>观测点：地球可选预设城市（自动填经纬度），其他天体直接输入纬度 / 经度</td></tr>
<tr><td><b>日期 / 时刻</b></td><td>要查看的当地日期与时刻；勾选"跟随时间轴"时随主视口时间轴自动更新</td></tr>
<tr><td><b>全景图</b></td><td>第一人称向四周望去：天空底色随太阳高度角在白昼 / 晨昏 / 夜晚间变化；背景亮星为柔和光晕点（近地平因大气消光变暗，白昼隐没）；太阳 / 月球按真实视直径成盘，行星与矮行星按视星等成点</td></tr>
<tr><td><b>拖拽 / 滚轮</b></td><td>在画面上拖拽可环视四周（水平转方位、垂直调仰角），滚轮切换视场（60°/90°/120°/180°）</td></tr>
<tr><td><b>地形剪影</b></td><td>地平线以下为静态地形示意：只在切换天体 / 经纬度时按种子生成一次，不逐帧渲染</td></tr>
<tr><td><b>选中天体</b></td><td>主视口 / 天体树当前选中的天体若在地平线上方，会以橙色圆环高亮并标注名称</td></tr>
<tr><td><b>读数表</b></td><td>太阳高度角与昼夜状态、地平线上方天体数、最亮行星 / 背景星的高度角·方位角·视星等</td></tr>
<tr><td><b>导出 PNG</b></td><td>把当前全景图保存为图片</td></tr>
</table>
<p style="color:#a0a0a0;">说明：地球自转相位取 GMST（与"地面视角"自洽），其他天体本初子午线角取可复现假设值（只影响经度零点）；
未建模大气折射与行星相位（月相 / 金星位相一律按整圆盘示意）；地形剪影为程序化示意，非实测地貌。</p>

<h3>数字键盘视图（Blender 标准）</h3>
<table>
<tr><td><b>Numpad 1</b></td><td>正面视图（Ctrl 反向）</td></tr>
<tr><td><b>Numpad 3</b></td><td>侧面视图（Ctrl 反向）</td></tr>
<tr><td><b>Numpad 7</b></td><td>俯视/仰视（Ctrl 反向）</td></tr>
<tr><td><b>Numpad 4/6</b></td><td>左旋/右旋</td></tr>
<tr><td><b>Numpad 8/2</b></td><td>上仰/下俯</td></tr>
<tr><td><b>Numpad +/-</b></td><td>缩放</td></tr>
<tr><td><b>Numpad .</b></td><td>聚焦到选中天体</td></tr>
</table>

<h3>飞行模式</h3>
<table>
<tr><td><b>Shift+~</b></td><td>进入/退出飞行模式</td></tr>
<tr><td><b>WASD</b></td><td>前后左右移动</td></tr>
<tr><td><b>Q/E</b></td><td>下降/上升</td></tr>
<tr><td><b>Shift</b></td><td>加速 ×5</td></tr>
<tr><td><b>Ctrl</b></td><td>减速 ×0.2</td></tr>
<tr><td><b>Esc</b></td><td>退出飞行模式</td></tr>
</table>

<h3>时间控制</h3>
<table>
<tr><td><b>空格</b></td><td>播放/暂停</td></tr>
<tr><td><b>底部时间轴</b></td><td>倍速滑块、倒放、日期跳转</td></tr>
</table>

<h3>其他</h3>
<table>
<tr><td><b>F1</b></td><td>本帮助窗口</td></tr>
<tr><td><b>左键点击天体</b></td><td>选中、显示详情，并把相机焦点切换到该天体</td></tr>
<tr><td><b>顶部搜索栏</b></td><td>搜索天体名称（中/英）</td></tr>
<tr><td><b>左侧天体树</b></td><td>按「恒星系（系群）」归类浏览：太阳系 + 各系外恒星系（宿主星 + 其行星）；点击天体聚焦，点击恒星系节点查看该系概览（宿主恒星参数 + 成员行星）</td></tr>
<tr><td><b>右侧对比面板</b></td><td>双行星相对运动分析；行星 A/B 可直接输入名称搜索（也可下拉逐个选）</td></tr>
<tr><td><b>详情面板按钮</b></td><td>聚焦 / 加入对比 / 观测特征（跳到"观测特征"页并载入该天体）/ 地面视角（跳到"地面视角"页，高亮该天体若在地平线上方）/ 地表视角（跳到"地表视角"页，站到该天体表面）/ 尺寸对比</td></tr>
<tr><td><b>教学场景</b></td><td>一键播放预设教学演示</td></tr>
<tr><td><b>切换模式</b></td><td>返回启动器重新选择视图：3D 立体视图 / 2D 平面视图（俯视黄道面的轨道图）</td></tr>
</table>

<h3>比例模式说明</h3>
<p><b>实体球</b>（默认开启）：天体按<b>真实半径</b>绘制为三维球体，带方向光照。<br/>
远看时天体极小，退化为最小标记点；靠近（聚焦/滚轮放大）时球体自然放大，
直至填满视野——太阳等天体"贴脸"即为此效果。关闭后全部使用点标记。</p>
<p><b>可视化比例</b>（默认）：标记点下限较大，远距也容易看清。<br/>
<b>真实比例</b>：标记点下限更小，更强调真实尺度关系。</p>
<p><b>系外行星</b>位于秒差距级距离，一律以细小光点显示（不按半径放大成圆球）；
拉近到某个行星系时，才按真实半径显示为实体球。</p>

<h3>数据精度</h3>
<p>每个天体标注精度等级 A/B/C：<br/>
<b>A</b> = 轨道根数与物理参数均来自权威源（JPL）<br/>
<b>B</b> = 有轨道倾角测定（凌星法），三维位置较可靠<br/>
<b>C</b> = 缺倾角或相位，瞬时位置为假设值（M(J2000)=0，可复现）</p>
""")
        layout.addWidget(text)
        btn = QPushButton("关闭")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec_()

    def _show_teaching(self):
        dlg = TeachingSceneDialog(
            self.viewport, self.compare_panel, self.timeline,
            self.tree_panel, self.detail_panel, self)
        dlg.exec_()

    def _show_guide(self):
        dlg = GuideDialog(self)
        dlg.exec_()

    def _show_settings(self):
        dlg = SettingsDialog(parent=self, viewport=self.viewport)
        dlg.exec_()

    def _maybe_show_guide(self):
        if should_show_guide():
            QTimer.singleShot(500, self._show_guide)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_F1:
            self._show_help()
            return
        if ev.key() == Qt.Key_Space:
            self.viewport.clock.toggle_play()
            self.timeline._refresh()
            return
        if ev.key() == Qt.Key_F and (ev.modifiers() & Qt.ControlModifier):
            self.search_box.setFocus()
            return
        super().keyPressEvent(ev)