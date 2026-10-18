"""
teaching_scenes.py —— 预设教学场景（模块 N）

一键播放预设教学场景，自动设置视角、时间、选中天体、对比组合：
  1. 开普勒第一定律：椭圆轨道（聚焦地球，观察椭圆形状）
  2. 开普勒第二定律：等面积定律（近日点快、远日点慢）
  3. 开普勒第三定律：周期与半长轴（地球 vs 木星速度对比）
  4. 火星合相：地火最近距离（对比面板+时间加速）
  5. TRAPPIST-1 系统：7颗行星共振链
  6. 系外行星尺度：从近邻到远距离的系外行星巡览
"""
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QFrame, QDialog)

from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT, BG_PANEL


@dataclass
class TeachingScene:
    name: str
    description: str
    focus_body: str = ""
    compare_a: str = ""
    compare_b: str = ""
    speed_index: int = 3
    azimuth_deg: float = 35.0
    elevation_deg: float = 20.0
    distance: float = 80.0
    real_scale: bool = False
    show_orbits: bool = True
    show_grid: bool = True
    show_labels: bool = True
    show_trails: bool = True
    filter_solar: bool = True
    filter_exo: bool = True
    extra_note: str = ""


SCENES = [
    TeachingScene(
        name="开普勒第一定律：椭圆轨道",
        description="行星沿椭圆轨道运行，太阳位于椭圆的一个焦点上。\n"
                    "聚焦地球，观察其椭圆轨道（偏心率 e=0.0167）。",
        focus_body="地球",
        speed_index=5,
        azimuth_deg=0,
        elevation_deg=90,
        distance=2.5,
        extra_note="从俯视角度观察地球椭圆轨道。偏心率虽小（0.0167），"
                   "但轨道形状确为椭圆，太阳位于焦点而非中心。",
    ),
    TeachingScene(
        name="开普勒第二定律：等面积定律",
        description="行星与太阳连线在相等时间内扫过相等面积。\n"
                    "近日点附近运行更快，远日点附近运行更慢。\n"
                    "对比地球与火星，观察速度差异。",
        focus_body="地球",
        compare_a="地球",
        compare_b="火星",
        speed_index=6,
        azimuth_deg=0,
        elevation_deg=60,
        distance=3.0,
        extra_note="加速时间观察：近日点附近行星移动更快（角速度大），"
                   "远日点附近更慢。对比面板的速度曲线可直观验证。",
    ),
    TeachingScene(
        name="开普勒第三定律：周期与半长轴",
        description="公转周期的平方与半长轴的立方成正比 (T² ∝ a³)。\n"
                    "地球 a=1AU, T=1年；木星 a=5.2AU, T=11.87年。\n"
                    "对比地球与木星的运动速度差异。",
        focus_body="太阳",
        compare_a="地球",
        compare_b="木星",
        speed_index=7,
        azimuth_deg=35,
        elevation_deg=20,
        distance=40.0,
        extra_note="木星半长轴是地球的5.2倍，周期11.87年≈5.2^1.5。"
                   "加速到10年/秒可直观看到木星缓慢绕行 vs 地球快速公转。",
    ),
    TeachingScene(
        name="火星合相（最近距离）",
        description="地球与火星的会合周期约780天。\n"
                    "合相时地火距离最近（约0.37-0.68 AU），\n"
                    "这是火星探测任务的最佳发射窗口。",
        focus_body="火星",
        compare_a="地球",
        compare_b="火星",
        speed_index=5,
        azimuth_deg=0,
        elevation_deg=5,
        distance=3.5,
        extra_note="对比面板中查看距离曲线的周期性变化，"
                   "最近点即为合相（火星冲日附近），约每780天一次。",
    ),
    TeachingScene(
        name="TRAPPIST-1 系统：共振链",
        description="TRAPPIST-1 是一颗超冷矮星，拥有7颗类地行星，\n"
                    "形成轨道共振链（周期比接近整数比）。\n"
                    "这是目前最著名的系外行星系统之一。",
        focus_body="TRAPPIST-1",
        compare_a="TRAPPIST-1 e",
        compare_b="TRAPPIST-1 f",
        speed_index=5,
        azimuth_deg=0,
        elevation_deg=45,
        distance=0.02,
        filter_solar=False,
        filter_exo=True,
        show_grid=False,
        extra_note="7颗行星周期比接近 1:1.5:2:2.5:3.3:4.1:5.4，"
                   "形成拉普拉斯共振链。e与f的会合周期约18天。",
    ),
    TeachingScene(
        name="系外行星尺度巡览",
        description="从最近的 Proxima Cen b（4.24光年）\n"
                    "到 Kepler 系统的遥远行星，\n"
                    "感受系外行星在银河系中的分布尺度。",
        focus_body="Proxima Cen b",
        speed_index=3,
        azimuth_deg=35,
        elevation_deg=20,
        distance=500000.0,
        filter_solar=False,
        filter_exo=True,
        show_grid=True,
        real_scale=True,
        extra_note="真实比例下系外行星极小（标记点显示），"
                   "但轨道线和宿主星位置清晰可见。缩放可见不同距离的系外行星系统。",
    ),
    TeachingScene(
        name="太阳死亡之旅（物理演化）",
        description="按 Schröder & Connon Smith (2008) 模型推演太阳命运：\n"
                    "主序 → 红巨星分支（半径膨胀至 1.2 AU）→ 氦闪 →\n"
                    "AGB → 行星状星云 → 白矮星。\n"
                    "水星金星被吞噬，行星轨道随质量损失外移。",
        focus_body="太阳",
        speed_index=12,        # 1 亿年/秒
        azimuth_deg=15,
        elevation_deg=25,
        distance=4.0,
        show_grid=False,
        extra_note="观测要点：太阳颜色随黑体温度变红、半径吞没内行星轨道；"
                   "吞噬瞬间太阳闪光；时间轴「演化」下拉可跳转关键节点；"
                   "HUD 实时显示 R/L/T/M。地球默认「逃逸」命运"
                   "（core/sun_evolution.py 的 EARTH_FATE 可切换「吞噬」模式）。",
    ),
    TeachingScene(
        name="潮汐锁定：月球一面朝向地球",
        description="月球自转周期 = 公转周期（27.32 天），\n"
                    "因此永远以同一面朝向地球。\n"
                    "潮汐摩擦使月球每年外移 3.82 cm（激光测距实测），\n"
                    "地球自转每世纪减慢约 2 ms。",
        focus_body="月球",
        speed_index=4,         # 1 周/秒 ≈ 4 秒一个公转周期
        azimuth_deg=20,
        elevation_deg=15,
        distance=0.02,
        extra_note="锁定跟随月球，观察月球表面斑纹始终朝向地球。"
                   "对照：木卫一受轨道共振挤压潮汐加热（火山活动最活跃的天体）。",
    ),
    TeachingScene(
        name="洛希极限与潮汐撕裂",
        description="天体进入主星流体洛希极限（d = 2.44·R·(ρ_p/ρ_s)^{1/3}）\n"
                    "时被潮汐力撕碎。\n"
                    "选中天体右键 →「潮汐撕裂演示」，观察轨道旋进与碎裂链条\n"
                    "（参考苏梅克-列维 9 号被木星撕裂成 21 块）。",
        focus_body="月球",
        speed_index=3,
        azimuth_deg=35,
        elevation_deg=20,
        distance=0.05,
        extra_note="演示步骤：选中月球（或其他卫星/行星）→ 右键「潮汐撕裂演示」→ "
                   "天体沿轨道旋进，进入地球流体洛希极限（约 2.9 倍地球半径）"
                   "后被撕成碎片链。右键还可切换「洛希极限圈」显示"
                   "（橙=刚体极限，红=流体极限）。",
    ),
]


class TeachingScenePanel(QWidget):
    """教学场景面板：列表 + 一键播放 + 说明"""

    def __init__(self, viewport=None, compare_panel=None, timeline=None,
                 tree_panel=None, detail_panel=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.compare_panel = compare_panel
        self.timeline = timeline
        self.tree_panel = tree_panel
        self.detail_panel = detail_panel
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("预设教学场景")
        title.setStyleSheet(f"color: {ACCENT}; font-size: {style.fs(14)}px; font-weight: bold;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        for scene in SCENES:
            item = QListWidgetItem(scene.name)
            item.setToolTip(scene.description)
            self.list_widget.addItem(item)
        self.list_widget.currentRowChanged.connect(self._on_select)
        layout.addWidget(self.list_widget, 1)

        self.lbl_desc = QLabel("")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(f"color: {TEXT_MAIN}; font-size: {style.fs(12)}px;")
        self.lbl_desc.setMinimumHeight(80)
        layout.addWidget(self.lbl_desc)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(self.lbl_note)

        self.btn_play = QPushButton("一键播放")
        self.btn_play.setStyleSheet(
            f"background-color: {ACCENT}; color: #ffffff; font-weight: bold;")
        self.btn_play.clicked.connect(self._play_scene)
        layout.addWidget(self.btn_play)

    def _on_select(self, row):
        if 0 <= row < len(SCENES):
            scene = SCENES[row]
            self.lbl_desc.setText(scene.description)
            self.lbl_note.setText(scene.extra_note)

    def _play_scene(self):
        row = self.list_widget.currentRow()
        if not (0 <= row < len(SCENES)):
            return
        scene = SCENES[row]
        self._apply_scene(scene)

    def _apply_scene(self, scene: TeachingScene):
        vp = self.viewport
        if vp is None:
            return

        # 比例模式
        vp.real_scale = scene.real_scale

        # 显示开关
        vp.show_orbits = scene.show_orbits
        vp.show_grid = scene.show_grid
        vp.show_labels = scene.show_labels
        vp.show_trails = scene.show_trails

        # 轨迹筛选
        vp.set_orbit_filter(solar=scene.filter_solar, exo=scene.filter_exo)

        # 倍速
        vp.clock.speed_index = scene.speed_index
        vp.clock.direction = 1
        vp.clock.playing = True

        # 视角
        vp.camera.set_view(scene.azimuth_deg, scene.elevation_deg)
        vp._release_follow()
        vp.focus_body = None
        vp.camera.snap_focus(vp.camera.focus.copy(), scene.distance)

        # 聚焦天体
        if scene.focus_body:
            vp.focus_body_by_name(scene.focus_body)
            if self.detail_panel:
                b = next((x for x in vp.bodies if x.name == scene.focus_body), None)
                if b:
                    self.detail_panel.show_body(b)
            if self.tree_panel:
                self.tree_panel.select_body(scene.focus_body)

        # 对比组合
        if scene.compare_a and scene.compare_b:
            vp.compare_names = [scene.compare_a, scene.compare_b]
            if self.compare_panel:
                self.compare_panel.set_pair(scene.compare_a, scene.compare_b)

        # 时间轴刷新
        if self.timeline:
            self.timeline._refresh()

        vp.update()


class TeachingSceneDialog(QDialog):
    """教学场景对话框（独立弹出）"""

    def __init__(self, viewport=None, compare_panel=None, timeline=None,
                 tree_panel=None, detail_panel=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预设教学场景")
        self.resize(400, 500)
        layout = QVBoxLayout(self)
        self.panel = TeachingScenePanel(
            viewport, compare_panel, timeline, tree_panel, detail_panel, self)
        layout.addWidget(self.panel)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)