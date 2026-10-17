"""
settings_dialog.py —— 统一设置面板

按功能分组（外观、显示、交互、引导、关于），每组用小标题 + 分割线区分。
同类选项对齐整齐，控件统一右对齐，每个选项配简短说明文字。

外观：界面语言（联合国六种官方语言）、界面主题（夜间 / 日间）——即时生效
显示：显示模式（5种）、分辨率、显示器选择、帧率限制、V-Sync、DPI缩放
交互：按需渲染、灵敏度
关于：版本信息
"""
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QScreen, QGuiApplication
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QComboBox, QCheckBox, QSpinBox, QSlider,
                             QLineEdit, QPushButton, QFrame, QGroupBox,
                             QSizePolicy, QScrollArea, QWidget, QApplication,
                             QMessageBox)

from ui import style
from ui import display_mode
from core import i18n
from core.i18n import tr
from core import app_settings
from core import gpu_info
from core import render_settings
from core import llm_client


class _LLMTestWorker(QObject):
    """后台执行一次大模型连通性测试，避免阻塞设置面板。"""
    done = pyqtSignal(bool, str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        ok, text, err = llm_client.chat(
            self.cfg.get("base_url", ""), self.cfg.get("api_key", ""),
            self.cfg.get("model", ""),
            [{"role": "user", "content": "请只回复两个字：你好"}], timeout=12.0)
        self.done.emit(ok, text if ok else err)

FPS_OPTIONS = [
    ("30 FPS", 30),
    ("60 FPS", 60),
    ("90 FPS（推荐）", 90),
    ("120 FPS", 120),
    ("144 FPS", 144),
    ("无限制", 0),
]

DISPLAY_MODES = [
    ("窗口模式", "windowed"),
    ("无边框窗口", "borderless_windowed"),
    ("无边框全屏", "borderless_fullscreen"),
    ("独占全屏", "exclusive_fullscreen"),
    ("最大化窗口", "maximized"),
]


class SettingsDialog(QDialog):
    """统一设置面板"""

    def __init__(self, parent=None, viewport=None):
        super().__init__(parent)
        self.viewport = viewport
        self._parent_window = parent
        self._retrans = []          # [(callable)]：语言变化时重建文字
        self._restylers = []        # [(callable)]：主题变化时重建内联样式
        self.setWindowTitle(tr("设置"))
        self.resize(540, 640)
        self._build_ui()
        self._load_current_fps()
        i18n.add_listener(self._retranslate)
        style.add_theme_listener(self._restyle)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        # ---------- 图形 / 显卡分组（置于首位，便于快速核对运行环境） ----------
        self._section(layout, "图形 / 显卡")

        gi = gpu_info.get()
        gpu_grid = QGridLayout()
        gpu_grid.setHorizontalSpacing(14)
        gpu_grid.setVerticalSpacing(10)
        gpu_grid.setColumnStretch(1, 1)
        grow = 0

        self._label(gpu_grid, grow, "当前显卡", "当前实际用于渲染的图形设备")
        self.lbl_gpu_name = QLabel(gpu_info.renderer_label() or tr("检测失败"))
        self.lbl_gpu_name.setWordWrap(True)
        self._value_style(self.lbl_gpu_name, "TEXT_MAIN", 12, bold=True)
        gpu_grid.addWidget(self.lbl_gpu_name, grow, 1)
        grow += 1

        self._label(gpu_grid, grow, "检测到的显卡", "本机安装的全部显示适配器")
        _adapters = gpu_info.list_adapters()
        self.lbl_gpu_all = QLabel("、".join(_adapters) if _adapters else tr("检测失败"))
        self.lbl_gpu_all.setWordWrap(True)
        self._value_style(self.lbl_gpu_all, "TEXT_MAIN", 12)
        gpu_grid.addWidget(self.lbl_gpu_all, grow, 1)
        grow += 1

        self._label(gpu_grid, grow, "图形接口", "图形 API 与着色器语言版本")
        _ver = f"OpenGL {gi['obtained'] or '?'}"
        _glsl = (gi.get("glsl") or "").split(" - ")[0].strip()
        if _glsl:
            _ver += f" · GLSL {_glsl}"
        self.lbl_gpu_api = QLabel(_ver)
        self._value_style(self.lbl_gpu_api, "TEXT_MAIN", 12)
        gpu_grid.addWidget(self.lbl_gpu_api, grow, 1)
        grow += 1

        self._label(gpu_grid, grow, "加速状态", "是否由 GPU 硬件加速渲染")
        self.lbl_gpu_accel = QLabel()
        self.lbl_gpu_accel.setWordWrap(True)
        self._update_gpu_accel()
        self._retrans.append(self._update_gpu_accel)
        self._restylers.append(self._update_gpu_accel)
        gpu_grid.addWidget(self.lbl_gpu_accel, grow, 1)
        grow += 1

        self._label(gpu_grid, grow, "显卡要求", "")
        self.lbl_gpu_req = QLabel(tr("支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新"))
        self.lbl_gpu_req.setWordWrap(True)
        self._retrans.append(lambda: self.lbl_gpu_req.setText(
            tr("支持桌面 OpenGL 3.3 Core 的显卡；建议使用独立显卡并保持驱动为最新")))
        self._value_style(self.lbl_gpu_req, "TEXT_DIM", 11)
        gpu_grid.addWidget(self.lbl_gpu_req, grow, 1)
        grow += 1

        layout.addLayout(gpu_grid)

        # 检测到独立显卡但未被使用 → 给出切换指引
        self.lbl_gpu_dgpu = QLabel()
        self.lbl_gpu_dgpu.setWordWrap(True)
        self._update_gpu_dgpu()
        self._retrans.append(self._update_gpu_dgpu)
        self._value_style(self.lbl_gpu_dgpu, "ACCENT", 10)
        layout.addWidget(self.lbl_gpu_dgpu)

        # 手动切换显卡：写入 Windows 图形首选项（用户级注册表，重启程序后生效）
        pref_grid = QGridLayout()
        pref_grid.setHorizontalSpacing(14)
        pref_grid.setVerticalSpacing(10)
        pref_grid.setColumnStretch(1, 1)
        self._label(pref_grid, 0, "显卡首选项",
                    "手动选择本程序使用的显卡（Windows 图形设置，重启程序后生效）")
        self.cmb_gpu_pref = QComboBox()
        for key in gpu_info.GPU_PREF_KEYS:
            self.cmb_gpu_pref.addItem(tr(gpu_info.GPU_PREF_LABELS[key]), key)
        _cur_pref = gpu_info.current_preference()
        _pi = self.cmb_gpu_pref.findData(_cur_pref)
        if _pi >= 0:
            self.cmb_gpu_pref.setCurrentIndex(_pi)
        self.cmb_gpu_pref.currentIndexChanged.connect(self._on_gpu_pref)
        pref_grid.addWidget(self.cmb_gpu_pref, 0, 1)
        layout.addLayout(pref_grid)

        # 重新检测显卡：清除持久缓存后离屏真探测（显卡驱动更新 / 外接显卡变动后用）
        self.btn_gpu_redetect = QPushButton(tr("重新检测"))
        self.btn_gpu_redetect.clicked.connect(self._on_gpu_redetect)
        layout.addWidget(self.btn_gpu_redetect)
        self._retrans.append(lambda: self.btn_gpu_redetect.setText(tr("重新检测")))

        self.lbl_gpu_pref_path = QLabel()
        self.lbl_gpu_pref_path.setWordWrap(True)
        self._value_style(self.lbl_gpu_pref_path, "TEXT_DIM", 10)
        layout.addWidget(self.lbl_gpu_pref_path)

        self._retrans.append(self._update_gpu_pref_note)
        self._update_gpu_pref_note()

        self.lbl_gpu_hint = QLabel(
            tr("软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行"))
        self.lbl_gpu_hint.setWordWrap(True)
        self.lbl_gpu_hint.setVisible(bool(gi["software"]))
        self._retrans.append(lambda: self.lbl_gpu_hint.setText(
            tr("软件渲染时三维画面由 CPU 计算，帧率会明显偏低，请更新显卡驱动或在独立显卡上运行")))
        self._value_style(self.lbl_gpu_hint, "ACCENT", 10)
        layout.addWidget(self.lbl_gpu_hint)

        layout.addWidget(self._hline())

        # ---------- 外观分组 ----------
        self._section(layout, "外观")

        app_grid = QGridLayout()
        app_grid.setHorizontalSpacing(14)
        app_grid.setVerticalSpacing(10)
        app_grid.setColumnStretch(1, 1)
        arow = 0

        self._label(app_grid, arow, "界面语言", "选择界面显示语言（联合国六种官方语言）")
        self.cmb_lang = QComboBox()
        for code, native, _en in i18n.available_languages():
            self.cmb_lang.addItem(native, code)
        idx = self.cmb_lang.findData(i18n.get_language())
        if idx >= 0:
            self.cmb_lang.setCurrentIndex(idx)
        self.cmb_lang.currentIndexChanged.connect(self._on_language)
        app_grid.addWidget(self.cmb_lang, arow, 1)
        arow += 1

        self._label(app_grid, arow, "界面主题", "在夜间与日间配色之间切换")
        self.cmb_theme = QComboBox()
        self._populate_theme_items()
        self.cmb_theme.currentIndexChanged.connect(self._on_theme)
        app_grid.addWidget(self.cmb_theme, arow, 1)
        arow += 1

        self._label(app_grid, arow, "界面字体大小",
                    "拖动滑块调节界面文字大小（0.8～1.6 倍），即时生效")
        font_row = QHBoxLayout()
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(8)
        self.sld_font = QSlider(Qt.Horizontal)
        self.sld_font.setMinimum(int(round(style.FONT_SCALE_MIN * 100)))
        self.sld_font.setMaximum(int(round(style.FONT_SCALE_MAX * 100)))
        self.sld_font.setSingleStep(5)
        self.sld_font.setPageStep(10)
        self.sld_font.setValue(int(round(style.font_scale() * 100)))
        self.sld_font.valueChanged.connect(self._on_font_scale)
        font_row.addWidget(self.sld_font, 1)
        self.lbl_font = QLabel(f"{int(round(style.font_scale() * 100))}%")
        self._value_style(self.lbl_font, "TEXT_MAIN", 12, bold=True)
        self.lbl_font.setMinimumWidth(44)
        self.lbl_font.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        font_row.addWidget(self.lbl_font)
        font_w = QWidget()
        font_w.setLayout(font_row)
        app_grid.addWidget(font_w, arow, 1)
        arow += 1

        layout.addLayout(app_grid)
        layout.addWidget(self._hline())

        # ---------- 显示分组 ----------
        self._section(layout, "显示")

        disp_grid = QGridLayout()
        disp_grid.setHorizontalSpacing(14)
        disp_grid.setVerticalSpacing(10)
        disp_grid.setColumnStretch(1, 1)
        row = 0

        self._label(disp_grid, row, "显示模式", "选择窗口/全屏模式")
        self.cmb_display_mode = QComboBox()
        self._populate_display_modes()
        self.cmb_display_mode.currentIndexChanged.connect(self._on_display_mode)
        disp_grid.addWidget(self.cmb_display_mode, row, 1)
        row += 1

        self._label(disp_grid, row, "分辨率", "独占全屏模式下可单独设置渲染分辨率")
        self.cmb_resolution = QComboBox()
        self._populate_resolutions()
        self.cmb_resolution.setCurrentIndex(0)
        self.cmb_resolution.setEnabled(False)
        disp_grid.addWidget(self.cmb_resolution, row, 1)
        row += 1

        self._label(disp_grid, row, "显示器", "多显示器环境下选择全屏显示的屏幕")
        self.cmb_monitor = QComboBox()
        self._populate_monitors()
        disp_grid.addWidget(self.cmb_monitor, row, 1)
        row += 1

        self._label(disp_grid, row, "帧率限制", "上限帧率，避免占用过高显卡资源（默认 90 FPS）")
        self.cmb_fps = QComboBox()
        self._populate_fps()
        self.cmb_fps.setCurrentIndex(2)
        self.cmb_fps.currentIndexChanged.connect(self._on_fps_limit)
        disp_grid.addWidget(self.cmb_fps, row, 1)
        row += 1

        self._label(disp_grid, row, "当前帧率", "实时 FPS 读数")
        self.lbl_fps_now = QLabel("—")
        self._restylers.append(
            lambda: self.lbl_fps_now.setStyleSheet(
                f"color: {style.palette()['ACCENT']}; font-size: {style.fs(13)}px; font-weight: bold;"))
        self.lbl_fps_now.setStyleSheet(
            f"color: {style.palette()['ACCENT']}; font-size: {style.fs(13)}px; font-weight: bold;")
        disp_grid.addWidget(self.lbl_fps_now, row, 1)
        row += 1

        self._label(disp_grid, row, "垂直同步", "与显示器刷新率同步，防止画面撕裂")
        self.chk_vsync = QCheckBox(tr("启用 V-Sync"))
        self.chk_vsync.setChecked(False)
        self._retrans.append(lambda: self.chk_vsync.setText(tr("启用 V-Sync")))
        disp_grid.addWidget(self.chk_vsync, row, 1, alignment=Qt.AlignRight)
        row += 1

        self._label(disp_grid, row, "DPI 缩放", "跟随系统 DPI 或强制 100%")
        self.cmb_dpi = QComboBox()
        self._populate_dpi()
        disp_grid.addWidget(self.cmb_dpi, row, 1)
        row += 1

        layout.addLayout(disp_grid)
        layout.addWidget(self._hline())

        # ---------- 性能分组（档位 + 天体数量动态适配） ----------
        self._section(layout, "性能")

        perf_grid = QGridLayout()
        perf_grid.setHorizontalSpacing(14)
        perf_grid.setVerticalSpacing(10)
        perf_grid.setColumnStretch(1, 1)
        prow = 0

        self._label(perf_grid, prow, "性能档位",
                    "高性能：上限 100 万颗；均衡：50 万；省电：12 万")
        self.cmb_tier = QComboBox()
        for key in render_settings.TIERS:
            self.cmb_tier.addItem(tr(render_settings.TIER_LABELS[key]), key)
        _ti = self.cmb_tier.findData(app_settings.get_perf_tier())
        if _ti >= 0:
            self.cmb_tier.setCurrentIndex(_ti)
        self.cmb_tier.currentIndexChanged.connect(self._on_tier)
        perf_grid.addWidget(self.cmb_tier, prow, 1)
        prow += 1

        self._label(perf_grid, prow, "天体数量",
                    "在显卡可承受范围内尽量多显示（目标 30 FPS 以上，上限 100 万）")
        planet_row = QHBoxLayout()
        planet_row.setContentsMargins(0, 0, 0, 0)
        planet_row.setSpacing(8)
        self.chk_planet_auto = QCheckBox(tr("自动适配"))
        self.chk_planet_auto.setChecked(app_settings.get_planet_count_mode() == "auto")
        self.chk_planet_auto.toggled.connect(self._on_planet_auto)
        planet_row.addWidget(self.chk_planet_auto)
        self.sld_planets = QSlider(Qt.Horizontal)
        self.sld_planets.setMinimum(render_settings.PLANET_HARD_FLOOR)
        self.sld_planets.setMaximum(render_settings.max_count(app_settings.get_perf_tier()))
        self.sld_planets.setSingleStep(1000)
        self.sld_planets.setPageStep(20000)
        self.sld_planets.setValue(render_settings.clamp_count(
            app_settings.get_planet_count(), app_settings.get_perf_tier()))
        self.sld_planets.valueChanged.connect(self._on_planet_slider)
        self.sld_planets.setEnabled(self.chk_planet_auto.isChecked() is False)
        planet_row.addWidget(self.sld_planets, 1)
        self.lbl_planets = QLabel(f"{self.sld_planets.value():,}")
        self._value_style(self.lbl_planets, "TEXT_MAIN", 12)
        self.lbl_planets.setMinimumWidth(72)
        self.lbl_planets.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        planet_row.addWidget(self.lbl_planets)
        planet_w = QWidget()
        planet_w.setLayout(planet_row)
        perf_grid.addWidget(planet_w, prow, 1)
        prow += 1

        self._label(perf_grid, prow, "实时状态", "当前帧率与正在渲染的天体数量")
        self.lbl_perf_now = QLabel("—")
        self._restylers.append(
            lambda: self.lbl_perf_now.setStyleSheet(
                f"color: {style.palette()['ACCENT']}; font-size: {style.fs(13)}px; font-weight: bold;"))
        self.lbl_perf_now.setStyleSheet(
            f"color: {style.palette()['ACCENT']}; font-size: {style.fs(13)}px; font-weight: bold;")
        perf_grid.addWidget(self.lbl_perf_now, prow, 1)
        prow += 1

        layout.addLayout(perf_grid)
        layout.addWidget(self._hline())

        # ---------- 交互分组 ----------
        self._section(layout, "交互")

        inter_grid = QGridLayout()
        inter_grid.setHorizontalSpacing(14)
        inter_grid.setVerticalSpacing(10)
        inter_grid.setColumnStretch(1, 1)
        irow = 0

        self._label(inter_grid, irow, "按需渲染", "空闲时降到低帧率重绘，省算力")
        self.chk_ondemand = QCheckBox(tr("启用按需渲染"))
        self.chk_ondemand.setChecked(True)
        self._retrans.append(lambda: self.chk_ondemand.setText(tr("启用按需渲染")))
        if self.viewport:
            self.chk_ondemand.toggled.connect(self.viewport.set_on_demand)
        inter_grid.addWidget(self.chk_ondemand, irow, 1, alignment=Qt.AlignRight)
        irow += 1

        self._label(inter_grid, irow, "鼠标灵敏度", "拖拽旋转/平移速度")
        self.cmb_sens = QComboBox()
        for label, val in (("很慢", 0.25), ("慢", 0.5), ("标准", 1.0),
                           ("快", 2.0), ("很快", 4.0)):
            self.cmb_sens.addItem(tr(label), val)
        self.cmb_sens.setCurrentIndex(2)
        if self.viewport and hasattr(self.viewport, 'camera'):
            self.cmb_sens.currentIndexChanged.connect(self._on_sensitivity)
        inter_grid.addWidget(self.cmb_sens, irow, 1)
        irow += 1

        layout.addLayout(inter_grid)
        layout.addWidget(self._hline())

        # ---------- 大模型分组（AI 对话 / 问答） ----------
        self._section(layout, "大模型")

        llm_grid = QGridLayout()
        llm_grid.setHorizontalSpacing(14)
        llm_grid.setVerticalSpacing(10)
        llm_grid.setColumnStretch(1, 1)
        lrow = 0
        _cfg = app_settings.get_llm_config()

        self._label(llm_grid, lrow, "服务商", "选择大模型服务商（OpenAI 兼容接口）")
        self.cmb_llm_provider = QComboBox()
        for key, name, _url, _model in llm_client.PROVIDERS:
            self.cmb_llm_provider.addItem(name, key)
        _li = self.cmb_llm_provider.findData(_cfg["provider"])
        if _li >= 0:
            self.cmb_llm_provider.setCurrentIndex(_li)
        self.cmb_llm_provider.currentIndexChanged.connect(self._on_llm_provider)
        llm_grid.addWidget(self.cmb_llm_provider, lrow, 1)
        lrow += 1

        self._label(llm_grid, lrow, "API 地址", "OpenAI 兼容的接口根地址（如 https://api.deepseek.com/v1）")
        self.edt_llm_url = QLineEdit(_cfg["base_url"])
        llm_grid.addWidget(self.edt_llm_url, lrow, 1)
        lrow += 1

        self._label(llm_grid, lrow, "模型名称", "如 deepseek-chat / gpt-4o-mini")
        self.edt_llm_model = QLineEdit(_cfg["model"])
        llm_grid.addWidget(self.edt_llm_model, lrow, 1)
        lrow += 1

        self._label(llm_grid, lrow, "API Key", "仅保存在本机设置文件，不会上传")
        self.edt_llm_key = QLineEdit(_cfg["api_key"])
        self.edt_llm_key.setEchoMode(QLineEdit.Password)
        self.edt_llm_key.setPlaceholderText("sk-…")
        llm_grid.addWidget(self.edt_llm_key, lrow, 1)
        lrow += 1

        layout.addLayout(llm_grid)

        llm_btn_row = QHBoxLayout()
        self.lbl_llm_status = QLabel()
        self._restylers.append(
            lambda: self.lbl_llm_status.setStyleSheet(
                f"color: {style.palette()['TEXT_DIM']}; font-size: {style.fs(11)}px;"))
        self.lbl_llm_status.setStyleSheet(
            f"color: {style.palette()['TEXT_DIM']}; font-size: {style.fs(11)}px;")
        llm_btn_row.addWidget(self.lbl_llm_status, 1)
        self.btn_llm_test = QPushButton(tr("测试连接"))
        self._retrans.append(lambda: self.btn_llm_test.setText(tr("测试连接")))
        self.btn_llm_test.clicked.connect(self._on_llm_test)
        llm_btn_row.addWidget(self.btn_llm_test)
        self.btn_llm_save = QPushButton(tr("保存"))
        self._retrans.append(lambda: self.btn_llm_save.setText(tr("保存")))
        self.btn_llm_save.clicked.connect(self._on_llm_save)
        llm_btn_row.addWidget(self.btn_llm_save)
        layout.addLayout(llm_btn_row)
        layout.addWidget(self._hline())

        # ---------- 新手引导 ----------
        self._section(layout, "引导")

        guide_row = QHBoxLayout()
        self.lbl_guide = QLabel(tr("新手引导"))
        self.lbl_guide.setStyleSheet(f"color: {style.palette()['TEXT_MAIN']}; font-size: {style.fs(12)}px;")
        self._restylers.append(
            lambda: self.lbl_guide.setStyleSheet(
                f"color: {style.palette()['TEXT_MAIN']}; font-size: {style.fs(12)}px;"))
        self._retrans.append(lambda: self.lbl_guide.setText(tr("新手引导")))
        guide_row.addWidget(self.lbl_guide)
        guide_row.addStretch()
        self.btn_guide = QPushButton(tr("重新打开引导"))
        self._retrans.append(lambda: self.btn_guide.setText(tr("重新打开引导")))
        self.btn_guide.clicked.connect(self._reopen_guide)
        guide_row.addWidget(self.btn_guide)
        layout.addLayout(guide_row)
        layout.addWidget(self._hline())

        # ---------- 关于分组 ----------
        self._section(layout, "关于")
        self.lbl_about = QLabel()
        self._restylers.append(self._restyle_about)
        self._retrans.append(self._restyle_about)
        self._restyle_about()
        self.lbl_about.setStyleSheet("padding: 4px 0;")
        layout.addWidget(self.lbl_about)

        layout.addStretch()

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton(tr("确定"))
        self._retrans.append(lambda: self.btn_ok.setText(tr("确定")))
        self.btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton(tr("取消"))
        self._retrans.append(lambda: self.btn_cancel.setText(tr("取消")))
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # FPS 实时刷新定时器
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps_label)
        self._fps_timer.timeout.connect(self._update_perf_label)
        self._fps_timer.start(500)

    # ---------- 辅助 ----------
    def _section(self, layout, key):
        lbl = QLabel(tr(key))
        lbl.setStyleSheet(
            f"color: {style.palette()['ACCENT']}; font-size: {style.fs(14)}px; font-weight: bold;"
            f"border: none; padding: 0;")
        self._restylers.append(
            lambda l=lbl: l.setStyleSheet(
                f"color: {style.palette()['ACCENT']}; font-size: {style.fs(14)}px; font-weight: bold;"
                f"border: none; padding: 0;"))
        self._retrans.append(lambda l=lbl, k=key: l.setText(tr(k)))
        layout.addWidget(lbl)

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        self._restylers.append(
            lambda l=line: l.setStyleSheet(f"color: {style.palette()['BORDER']};"))
        line.setStyleSheet(f"color: {style.palette()['BORDER']};")
        return line

    def _label(self, grid, row, title, desc=""):
        """在网格指定行放一个「标题 + 说明」标签组，并登记重译/重着色。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        t = QLabel(tr(title))
        t.setStyleSheet(f"color: {style.palette()['TEXT_MAIN']}; font-size: {style.fs(12)}px;")
        self._restylers.append(
            lambda l=t: l.setStyleSheet(
                f"color: {style.palette()['TEXT_MAIN']}; font-size: {style.fs(12)}px;"))
        self._retrans.append(lambda l=t, k=title: l.setText(tr(k)))
        lay.addWidget(t)
        if desc:
            d = QLabel(tr(desc))
            d.setStyleSheet(f"color: {style.palette()['TEXT_DIM']}; font-size: {style.fs(10)}px;")
            self._restylers.append(
                lambda l=d: l.setStyleSheet(
                    f"color: {style.palette()['TEXT_DIM']}; font-size: {style.fs(10)}px;"))
            self._retrans.append(lambda l=d, k=desc: l.setText(tr(k)))
            d.setWordWrap(True)
            lay.addWidget(d)
        grid.addWidget(w, row, 0)
        return w

    def _value_style(self, label, color_key, size, bold=False):
        """给「值」标签套用调色板颜色，并登记主题重着色。"""
        weight = "bold" if bold else "normal"

        def _apply(l=label, ck=color_key, s=size, w=weight):
            l.setStyleSheet(
                f"color: {style.palette()[ck]}; font-size: {style.fs(s)}px; font-weight: {w};")

        _apply()
        self._restylers.append(_apply)

    def _update_gpu_accel(self):
        """刷新「加速状态」文字与颜色（语言/主题变化时调用）。"""
        gi = gpu_info.get()
        if gi["software"]:
            self.lbl_gpu_accel.setText(tr("软件渲染（CPU）"))
            color = style.palette()["ACCENT"]
        else:
            self.lbl_gpu_accel.setText(tr("硬件加速（GPU）"))
            color = "#4caf50"
        self.lbl_gpu_accel.setStyleSheet(
            f"color: {color}; font-size: {style.fs(12)}px; font-weight: bold;")

    def _update_gpu_dgpu(self):
        """独立显卡存在但未被使用时的切换指引（语言变化时刷新）。"""
        unused = gpu_info.unused_discrete()
        if not unused:
            self.lbl_gpu_dgpu.setVisible(False)
            return
        self.lbl_gpu_dgpu.setText(
            tr("检测到独立显卡但当前未使用：") + "、".join(unused) + "\n" +
            tr("如需改用独立显卡：NVIDIA 控制面板 → 管理 3D 设置 → 程序设置，"
               "将本程序设为「高性能 NVIDIA 处理器」；或 Windows 设置 → 显示 → 图形，"
               "将本程序设为「高性能」。"))
        self.lbl_gpu_dgpu.setVisible(True)

    def _update_gpu_pref_note(self):
        """刷新「显卡首选项」下拉项文字与设置对象说明（语言变化时调用）。"""
        cur = self.cmb_gpu_pref.currentData()
        self.cmb_gpu_pref.blockSignals(True)
        self.cmb_gpu_pref.clear()
        for key in gpu_info.GPU_PREF_KEYS:
            self.cmb_gpu_pref.addItem(tr(gpu_info.GPU_PREF_LABELS[key]), key)
        i = self.cmb_gpu_pref.findData(cur)
        if i >= 0:
            self.cmb_gpu_pref.setCurrentIndex(i)
        self.cmb_gpu_pref.blockSignals(False)
        self.lbl_gpu_pref_path.setText(tr("设置对象：") + gpu_info.exe_path())
        self.lbl_gpu_pref_path.setVisible(bool(gpu_info.list_adapters()))

    def _on_gpu_pref(self, idx):
        """写入 Windows 图形首选项并保存到配置（重启程序后生效）。"""
        pref = self.cmb_gpu_pref.currentData()
        if pref is None:
            return
        ok, err = gpu_info.set_gpu_preference(pref)
        if not ok:
            QMessageBox.warning(self, tr("设置失败"), tr("写入设置失败：") + err)
            i = self.cmb_gpu_pref.findData(app_settings.get_gpu_pref())
            self.cmb_gpu_pref.blockSignals(True)
            if i >= 0:
                self.cmb_gpu_pref.setCurrentIndex(i)
            self.cmb_gpu_pref.blockSignals(False)
            return
        app_settings.set_gpu_pref(pref)
        self.lbl_gpu_pref_path.setText(tr("设置对象：") + gpu_info.exe_path())
        if pref == "auto":
            QMessageBox.information(self, tr("图形首选项"),
                                    tr("已恢复由系统自动选择显卡，请重新启动程序后生效。"))
        else:
            QMessageBox.information(self, tr("图形首选项"),
                                    tr("已切换显卡首选项，请关闭并重新启动程序后生效。"))

    def _on_gpu_redetect(self):
        """清除显卡持久缓存并重新离屏探测，刷新本分组显示。"""
        gpu_info.redetect()
        gi = gpu_info.get()
        self.lbl_gpu_name.setText(gpu_info.renderer_label() or tr("检测失败"))
        _adapters = gpu_info.list_adapters()
        self.lbl_gpu_all.setText("、".join(_adapters) if _adapters else tr("检测失败"))
        _ver = f"OpenGL {gi['obtained'] or '?'}"
        _glsl = (gi.get("glsl") or "").split(" - ")[0].strip()
        if _glsl:
            _ver += f" · GLSL {_glsl}"
        self.lbl_gpu_api.setText(_ver)
        self._update_gpu_accel()
        self._update_gpu_dgpu()
        self.lbl_gpu_hint.setVisible(bool(gi["software"]))

    def _restyle_about(self):
        p = style.palette()
        self.lbl_about.setText(
            f"<span style='color:{p['TEXT_MAIN']};font-size:{style.fs(13)}px;'>{tr('Astrarium')}</span><br>"
            f"<span style='color:{p['TEXT_DIM']};font-size:{style.fs(11)}px;'>"
            f"{tr('太阳系 + 系外行星 · 请选择视图模式').split(' · ')[0]} + "
            f"{tr('黑洞')} + {tr('近邻恒星')} + {tr('星际天体')}<br>"
            f"{tr('数据来源：JPL / NASA Exoplanet Archive / IAU / MPC')}</span>")

    # ---------- 下拉填充 ----------
    def _populate_theme_items(self):
        self.cmb_theme.blockSignals(True)
        cur = style.current_theme()
        self.cmb_theme.clear()
        for key in style.THEME_KEYS:
            self.cmb_theme.addItem(tr(style.THEME_LABELS[key]), key)
        idx = self.cmb_theme.findData(cur)
        if idx >= 0:
            self.cmb_theme.setCurrentIndex(idx)
        self.cmb_theme.blockSignals(False)

    def _populate_display_modes(self):
        # 重建下拉项期间屏蔽信号：避免 clear() 触发 currentIndexChanged(-1)，
        # 使 currentData() 返回 None 而误触发显示模式切换（导致窗口闪动）。
        self.cmb_display_mode.blockSignals(True)
        cur = self.cmb_display_mode.currentData()
        if cur is None:            # 首次填充：回读已保存档位（默认最大化窗口）
            cur = app_settings.get_display_mode()
        self.cmb_display_mode.clear()
        for label, key in DISPLAY_MODES:
            self.cmb_display_mode.addItem(tr(label), key)
        idx = self.cmb_display_mode.findData(cur)
        if idx >= 0:
            self.cmb_display_mode.setCurrentIndex(idx)
        self.cmb_display_mode.blockSignals(False)

    def _populate_resolutions(self):
        self.cmb_resolution.blockSignals(True)
        self.cmb_resolution.clear()
        self.cmb_resolution.addItem(tr("自动（推荐）"), "auto")
        for w, h in ((1920, 1080), (2560, 1440), (3840, 2160),
                     (1280, 720), (1600, 900), (1366, 768)):
            self.cmb_resolution.addItem(f"{w}×{h}", f"{w}x{h}")
        self.cmb_resolution.setCurrentIndex(0)
        self.cmb_resolution.blockSignals(False)

    def _populate_monitors(self):
        self.cmb_monitor.blockSignals(True)
        self.cmb_monitor.clear()
        screens = QGuiApplication.screens()
        for i, scr in enumerate(screens):
            geo = scr.geometry()
            self.cmb_monitor.addItem(
                f"{tr('显示器')} {i+1} ({geo.width()}×{geo.height()})", i)
        if not screens:
            self.cmb_monitor.addItem(tr("显示器"), 0)
        self.cmb_monitor.blockSignals(False)

    def _populate_fps(self):
        # 同 _populate_display_modes：屏蔽信号，避免 clear() 以 None 误触发帧率设置，
        # 进而 int(None) 抛 TypeError。
        self.cmb_fps.blockSignals(True)
        cur = self.cmb_fps.currentData()
        self.cmb_fps.clear()
        for label, val in FPS_OPTIONS:
            self.cmb_fps.addItem(tr(label), val)
        idx = self.cmb_fps.findData(cur)
        if idx >= 0:
            self.cmb_fps.setCurrentIndex(idx)
        self.cmb_fps.blockSignals(False)

    def _populate_dpi(self):
        self.cmb_dpi.blockSignals(True)
        self.cmb_dpi.clear()
        self.cmb_dpi.addItem(tr("自动（跟随系统）"), "auto")
        self.cmb_dpi.addItem(tr("100%（强制）"), "100")
        self.cmb_dpi.blockSignals(False)

    # ---------- 即时生效 ----------
    def _on_language(self, idx):
        code = self.cmb_lang.currentData()
        app_settings.set_language(code)          # 通知全应用重译（含本对话框）
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(i18n.layout_direction(code))

    def _on_theme(self, idx):
        key = self.cmb_theme.currentData()
        app_settings.set_theme(key)              # style.apply_theme → 通知重着色
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(style.MAIN_QSS)

    def _retranslate(self):
        self.setWindowTitle(tr("设置"))
        # 下拉项文本
        cur_disp = self.cmb_display_mode.currentData()
        self._populate_display_modes()
        j = self.cmb_display_mode.findData(cur_disp)
        if j >= 0:
            self.cmb_display_mode.setCurrentIndex(j)
        cur_fps = self.cmb_fps.currentData()
        self._populate_fps()
        j = self.cmb_fps.findData(cur_fps)
        if j >= 0:
            self.cmb_fps.setCurrentIndex(j)
        self._populate_theme_items()
        cur_tier = self.cmb_tier.currentData()
        self.cmb_tier.blockSignals(True)
        self.cmb_tier.clear()
        for key in render_settings.TIERS:
            self.cmb_tier.addItem(tr(render_settings.TIER_LABELS[key]), key)
        j = self.cmb_tier.findData(cur_tier)
        if j >= 0:
            self.cmb_tier.setCurrentIndex(j)
        self.cmb_tier.blockSignals(False)
        self.chk_planet_auto.setText(tr("自动适配"))
        for cb in self._retrans:
            cb()

    def _restyle(self):
        for cb in self._restylers:
            cb()

    # ---------- 事件 ----------
    def _on_display_mode(self, idx):
        key = self.cmb_display_mode.currentData()
        if key is None:            # clear() 期间的过渡信号，忽略
            return
        self.cmb_resolution.setEnabled(key == "exclusive_fullscreen")
        app_settings.set_display_mode(key)   # 持久化：下次启动沿用该档位
        self._apply_display_mode(key)

    def _apply_display_mode(self, key):
        win = self._parent_window
        if win is None or key is None:
            return
        display_mode.apply_display_mode(win, key,
                                        self.cmb_monitor.currentData())

    def _on_fps_limit(self):
        val = self.cmb_fps.currentData()
        if val is None:            # clear() 期间的过渡信号，忽略
            return
        if self.viewport and hasattr(self.viewport, 'set_fps_limit'):
            self.viewport.set_fps_limit(val)

    def _on_sensitivity(self):
        if self.viewport and hasattr(self.viewport, 'camera'):
            val = self.cmb_sens.currentData()
            if val is not None:
                self.viewport.camera.set_sensitivity(val)

    def _load_current_fps(self):
        if self.viewport and hasattr(self.viewport, 'fps_limit'):
            target = self.viewport.fps_limit
            for i in range(self.cmb_fps.count()):
                if self.cmb_fps.itemData(i) == target:
                    self.cmb_fps.setCurrentIndex(i)
                    break

    def _update_fps_label(self):
        if self.viewport and hasattr(self.viewport, '_fps'):
            self.lbl_fps_now.setText(f"{self.viewport._fps:.0f} FPS")
        else:
            self.lbl_fps_now.setText("—")

    def _update_perf_label(self):
        if self.viewport and hasattr(self.viewport, '_fps'):
            n = getattr(self.viewport, 'belt_count', 0)
            self.lbl_perf_now.setText(f"{self.viewport._fps:.0f} FPS · {n:,}")
        else:
            self.lbl_perf_now.setText("—")

    # ---------- 字体 / 性能 / 大模型 事件 ----------
    def _on_font_scale(self, val):
        self.lbl_font.setText(f"{val}%")
        app_settings.set_font_scale(val / 100.0)      # 内部重建 QSS 并通知监听者
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(style.MAIN_QSS)

    def _on_tier(self, idx):
        key = self.cmb_tier.currentData()
        if key is None:
            return
        app_settings.set_perf_tier(key)
        hi = render_settings.max_count(key)
        self.sld_planets.blockSignals(True)
        self.sld_planets.setMaximum(hi)
        self.sld_planets.blockSignals(False)
        if self.sld_planets.value() > hi:
            self.sld_planets.setValue(hi)
        if self.viewport and hasattr(self.viewport, 'set_perf_tier'):
            self.viewport.set_perf_tier(key)

    def _on_planet_auto(self, checked):
        mode = "auto" if checked else "manual"
        app_settings.set_planet_count(self.sld_planets.value(), mode)
        self.sld_planets.setEnabled(not checked)
        if self.viewport and hasattr(self.viewport, 'set_planet_auto'):
            self.viewport.set_planet_auto(checked)

    def _on_planet_slider(self, val):
        self.lbl_planets.setText(f"{val:,}")
        if self.chk_planet_auto.isChecked():
            return                                     # 自动模式下滑块仅作显示
        app_settings.set_planet_count(val, "manual")
        if self.viewport and hasattr(self.viewport, 'set_planet_count'):
            self.viewport.set_planet_count(val, auto=False)

    def _on_llm_provider(self, idx):
        key = self.cmb_llm_provider.currentData()
        if key is None or key == "custom":
            return
        url, model = llm_client.provider_defaults(key)
        if url:
            self.edt_llm_url.setText(url)
        if model:
            self.edt_llm_model.setText(model)

    def _on_llm_save(self):
        app_settings.set_llm_config(
            provider=self.cmb_llm_provider.currentData(),
            base_url=self.edt_llm_url.text().strip(),
            model=self.edt_llm_model.text().strip(),
            api_key=self.edt_llm_key.text().strip())
        self.lbl_llm_status.setText(tr("已保存"))

    def _on_llm_test(self):
        cfg = {
            "base_url": self.edt_llm_url.text().strip(),
            "model": self.edt_llm_model.text().strip(),
            "api_key": self.edt_llm_key.text().strip(),
        }
        if not cfg["api_key"]:
            self.lbl_llm_status.setText(tr("请先填写 API Key"))
            return
        self._on_llm_save()
        self.btn_llm_test.setEnabled(False)
        self.lbl_llm_status.setText(tr("测试中…（正在请求大模型 API）"))
        self._llm_thread = QThread(self)
        self._llm_worker = _LLMTestWorker(cfg)
        self._llm_worker.moveToThread(self._llm_thread)
        self._llm_thread.started.connect(self._llm_worker.run)
        self._llm_worker.done.connect(self._on_llm_test_done)
        self._llm_worker.done.connect(self._llm_thread.quit)
        self._llm_thread.finished.connect(self._llm_thread.deleteLater)
        self._llm_thread.start()

    def _on_llm_test_done(self, ok, detail):
        self.btn_llm_test.setEnabled(True)
        if ok:
            self.lbl_llm_status.setText(tr("连接成功：") + (detail or "")[:40])
        else:
            self.lbl_llm_status.setText(tr("连接失败：") + detail)

    def _reopen_guide(self):
        from ui.guide import GuideDialog
        self.accept()
        dlg = GuideDialog(self._parent_window)
        dlg.exec_()

    def closeEvent(self, ev):
        i18n.remove_listener(self._retranslate)
        style.remove_theme_listener(self._restyle)
        super().closeEvent(ev)
