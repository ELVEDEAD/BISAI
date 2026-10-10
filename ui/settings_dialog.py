"""
settings_dialog.py —— 统一设置面板

按功能分组（外观、显示、交互、引导、关于），每组用小标题 + 分割线区分。
同类选项对齐整齐，控件统一右对齐，每个选项配简短说明文字。

外观：界面语言（联合国六种官方语言）、界面主题（夜间 / 日间）——即时生效
显示：显示模式（5种）、分辨率、显示器选择、帧率限制、V-Sync、DPI缩放
交互：按需渲染、灵敏度
关于：版本信息
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QScreen, QGuiApplication
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QComboBox, QCheckBox, QSpinBox,
                             QPushButton, QFrame, QGroupBox, QSizePolicy,
                             QScrollArea, QWidget, QApplication, QMessageBox)

from ui import style
from core import i18n
from core.i18n import tr
from core import app_settings
from core import gpu_info

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

        # 一键把本程序设为「高性能（独立显卡）」——写入 Windows 图形首选项（用户级、可撤销）
        self.btn_gpu_pref = QPushButton()
        self.btn_gpu_pref.clicked.connect(self._toggle_gpu_pref)
        pref_row = QHBoxLayout()
        pref_row.addWidget(self.btn_gpu_pref)
        pref_row.addStretch(1)
        layout.addLayout(pref_row)

        self.lbl_gpu_pref_path = QLabel()
        self.lbl_gpu_pref_path.setWordWrap(True)
        self._value_style(self.lbl_gpu_pref_path, "TEXT_DIM", 10)
        layout.addWidget(self.lbl_gpu_pref_path)

        self._retrans.append(self._update_gpu_pref_button)
        self._update_gpu_pref_button()

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
                f"color: {style.palette()['ACCENT']}; font-size: 13px; font-weight: bold;"))
        self.lbl_fps_now.setStyleSheet(
            f"color: {style.palette()['ACCENT']}; font-size: 13px; font-weight: bold;")
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

        # ---------- 新手引导 ----------
        self._section(layout, "引导")

        guide_row = QHBoxLayout()
        self.lbl_guide = QLabel(tr("新手引导"))
        self.lbl_guide.setStyleSheet(f"color: {style.palette()['TEXT_MAIN']}; font-size: 12px;")
        self._restylers.append(
            lambda: self.lbl_guide.setStyleSheet(
                f"color: {style.palette()['TEXT_MAIN']}; font-size: 12px;"))
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
        self._fps_timer.start(500)

    # ---------- 辅助 ----------
    def _section(self, layout, key):
        lbl = QLabel(tr(key))
        lbl.setStyleSheet(
            f"color: {style.palette()['ACCENT']}; font-size: 14px; font-weight: bold;"
            f"border: none; padding: 0;")
        self._restylers.append(
            lambda l=lbl: l.setStyleSheet(
                f"color: {style.palette()['ACCENT']}; font-size: 14px; font-weight: bold;"
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
        t.setStyleSheet(f"color: {style.palette()['TEXT_MAIN']}; font-size: 12px;")
        self._restylers.append(
            lambda l=t: l.setStyleSheet(
                f"color: {style.palette()['TEXT_MAIN']}; font-size: 12px;"))
        self._retrans.append(lambda l=t, k=title: l.setText(tr(k)))
        lay.addWidget(t)
        if desc:
            d = QLabel(tr(desc))
            d.setStyleSheet(f"color: {style.palette()['TEXT_DIM']}; font-size: 10px;")
            self._restylers.append(
                lambda l=d: l.setStyleSheet(
                    f"color: {style.palette()['TEXT_DIM']}; font-size: 10px;"))
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
                f"color: {style.palette()[ck]}; font-size: {s}px; font-weight: {w};")

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
            f"color: {color}; font-size: 12px; font-weight: bold;")

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

    def _update_gpu_pref_button(self):
        """刷新「改用独立显卡」按钮文字与设置对象说明。"""
        if not gpu_info.discrete_adapters():
            self.btn_gpu_pref.setVisible(False)
            self.lbl_gpu_pref_path.setVisible(False)
            return
        if gpu_info.high_performance_enabled():
            self.btn_gpu_pref.setText(tr("已启用独立显卡（点击撤销）"))
        else:
            self.btn_gpu_pref.setText(tr("改用独立显卡（重启生效）"))
        self.btn_gpu_pref.setVisible(True)
        self.lbl_gpu_pref_path.setText(tr("设置对象：") + gpu_info.exe_path())
        self.lbl_gpu_pref_path.setVisible(True)

    def _toggle_gpu_pref(self):
        """写入 / 撤销 Windows 图形首选项（用户级注册表，重启程序后生效）。"""
        enable = not gpu_info.high_performance_enabled()
        ok, err = gpu_info.set_high_performance(enable)
        if not ok:
            QMessageBox.warning(self, tr("设置失败"), tr("写入设置失败：") + err)
            return
        self._update_gpu_pref_button()
        if enable:
            QMessageBox.information(
                self, tr("图形首选项"),
                tr("已设为优先使用独立显卡，请关闭并重新启动程序后生效。"))
        else:
            QMessageBox.information(
                self, tr("图形首选项"),
                tr("已恢复由系统自动选择显卡，请重新启动程序后生效。"))

    def _restyle_about(self):
        p = style.palette()
        self.lbl_about.setText(
            f"<span style='color:{p['TEXT_MAIN']};font-size:13px;'>{tr('已知行星可视化')}</span><br>"
            f"<span style='color:{p['TEXT_DIM']};font-size:11px;'>"
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
        self._apply_display_mode(key)

    def _apply_display_mode(self, key):
        win = self._parent_window
        if win is None or key is None:
            return
        if key == "windowed":
            win.setWindowFlags(Qt.Window)
            win.showNormal()
        elif key == "borderless_windowed":
            win.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
            win.showNormal()
        elif key == "borderless_fullscreen":
            win.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
            scr = QGuiApplication.primaryScreen()
            if self.cmb_monitor.currentData() is not None:
                screens = QGuiApplication.screens()
                idx = min(self.cmb_monitor.currentData(), len(screens) - 1)
                scr = screens[idx]
            geo = scr.geometry()
            win.setGeometry(geo)
            win.show()
        elif key == "exclusive_fullscreen":
            win.setWindowFlags(Qt.Window)
            win.showFullScreen()
        elif key == "maximized":
            win.setWindowFlags(Qt.Window)
            win.showMaximized()
        win.activateWindow()
        win.raise_()

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

    def _reopen_guide(self):
        from ui.guide import GuideDialog
        self.accept()
        dlg = GuideDialog(self._parent_window)
        dlg.exec_()

    def closeEvent(self, ev):
        i18n.remove_listener(self._retranslate)
        style.remove_theme_listener(self._restyle)
        super().closeEvent(ev)
