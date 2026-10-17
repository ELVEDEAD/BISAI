"""
launcher.py —— 启动器（模式选择）窗口

程序入口先弹出本窗口，让用户选择视图模式：
    * 3D 立体视图 → 打开 ui/main_window.py 的三维主窗口
    * 2D 平面视图 → 打开 ui/main_window_2d.py 的二维平面窗口

同一时刻只显示一个主窗口；两个主窗口工具栏的「切换模式」可回到本窗口重新选择。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame)

from ui import style
from ui import dark_titlebar, display_mode
from ui.resource import icon_path
from core import i18n
from core import app_settings
from core.i18n import tr


class LauncherWindow(QWidget):
    """模式选择窗口：3D 立体视图 / 2D 平面视图"""

    def __init__(self, bodies, stars):
        super().__init__()
        self.bodies = bodies
        self.stars = stars
        self.win3d = None
        self.win2d = None
        self.win_gravity = None

        self.setWindowTitle(tr("Astrarium —— 选择视图模式"))
        self.setWindowIcon(QIcon(icon_path()))
        self.setMinimumSize(880, 440)
        self.resize(940, 500)
        self._build_ui()
        self._apply_style()

        i18n.add_listener(self.retranslate)
        style.add_theme_listener(self._apply_style)

    def showEvent(self, ev):
        dark_titlebar.apply_dark_titlebar(self)
        super().showEvent(ev)

    def closeEvent(self, ev):
        i18n.remove_listener(self.retranslate)
        style.remove_theme_listener(self._apply_style)
        super().closeEvent(ev)

    # ---------- 外观 ----------
    def _qss(self):
        p = style.palette()
        return f"""
QWidget#launcherRoot {{ background-color: {p['BG_MAIN']}; }}
QLabel#launcherTitle {{ color: {p['TEXT_MAIN']}; font-size: {style.fs(22)}px; font-weight: 600; }}
QLabel#launcherSub   {{ color: {p['TEXT_DIM']}; font-size: {style.fs(12)}px; }}
QPushButton#modeCard {{
    background-color: {p['BG_PANEL']};
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    color: {p['TEXT_MAIN']};
    font-size: {style.fs(14)}px;
    text-align: left;
    padding: 16px 20px;
}}
QPushButton#modeCard:hover {{ background-color: {p['BG_PANEL_LIGHT']}; }}
QPushButton#modeCard3d:hover {{ border: 1px solid {p['ACCENT']}; }}
QPushButton#modeCard2d:hover {{ border: 1px solid {p['ACCENT_BLUE']}; }}
QPushButton#modeCardGravity:hover {{ border: 1px solid #4caf50; }}
QLabel#launcherFoot {{ color: {p['TEXT_DIM']}; font-size: {style.fs(11)}px; }}
"""

    def _apply_style(self):
        self.setStyleSheet(self._qss())
        if getattr(self, "_line", None) is not None:
            self._line.setStyleSheet(f"color: {style.palette()['BORDER']};")

    def _build_ui(self):
        self.setObjectName("launcherRoot")
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 26)
        root.setSpacing(14)

        self._title = QLabel(tr("Astrarium"))
        self._title.setObjectName("launcherTitle")
        root.addWidget(self._title)

        self._sub = QLabel(tr("太阳系 + 系外行星 · 请选择视图模式"))
        self._sub.setObjectName("launcherSub")
        root.addWidget(self._sub)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        self._line = line
        line.setStyleSheet(f"color: {style.palette()['BORDER']};")
        root.addWidget(line)

        root.addSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(14)

        self.btn_3d = QPushButton(tr(
            "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n"
            "系外行星与背景亮星"))
        self.btn_3d.setObjectName("modeCard3d")
        self.btn_3d.setMinimumHeight(150)
        self.btn_3d.setCursor(Qt.PointingHandCursor)
        self.btn_3d.setToolTip(tr("打开三维立体视图（快捷键 3）"))
        self.btn_3d.clicked.connect(lambda: self.show_mode("3d"))
        row.addWidget(self.btn_3d)

        self.btn_2d = QPushButton(tr(
            "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n"
            "轻量平面 · 便于看轨道关系"))
        self.btn_2d.setObjectName("modeCard2d")
        self.btn_2d.setMinimumHeight(150)
        self.btn_2d.setCursor(Qt.PointingHandCursor)
        self.btn_2d.setToolTip(tr("打开二维平面视图（快捷键 2）"))
        self.btn_2d.clicked.connect(lambda: self.show_mode("2d"))
        row.addWidget(self.btn_2d)

        self.btn_gravity = QPushButton(tr(
            "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n"
            "质量越大 · 距离越近 · 凹陷越深"))
        self.btn_gravity.setObjectName("modeCardGravity")
        self.btn_gravity.setMinimumHeight(150)
        self.btn_gravity.setCursor(Qt.PointingHandCursor)
        self.btn_gravity.setToolTip(tr("打开引力系统视图（快捷键 G）"))
        self.btn_gravity.clicked.connect(lambda: self.show_mode("gravity"))
        row.addWidget(self.btn_gravity)

        root.addLayout(row)
        root.addStretch(1)

        self._foot = QLabel(tr("三个视图共用同一套数据与时间系统；"
                               "可用主窗口工具栏的「切换模式」随时返回本窗口。"))
        self._foot.setObjectName("launcherFoot")
        self._foot.setWordWrap(True)
        root.addWidget(self._foot)

    # ---------- 语言 / 主题 ----------
    def retranslate(self):
        self.setWindowTitle(tr("Astrarium —— 选择视图模式"))
        self._title.setText(tr("Astrarium"))
        self._sub.setText(tr("太阳系 + 系外行星 · 请选择视图模式"))
        self.btn_3d.setText(tr(
            "3D 立体视图\n\n三维轨道空间 · 可旋转缩放\n实体球 + 程序化表面贴图\n"
            "系外行星与背景亮星"))
        self.btn_3d.setToolTip(tr("打开三维立体视图（快捷键 3）"))
        self.btn_2d.setText(tr(
            "2D 平面视图\n\n俯视黄道面的轨道图\n行星轨道椭圆 · 自适应刻度\n"
            "轻量平面 · 便于看轨道关系"))
        self.btn_2d.setToolTip(tr("打开二维平面视图（快捷键 2）"))
        self.btn_gravity.setText(tr(
            "引力系统\n\n时空弯曲网格\n天体按 M/r 引力势把网格压出凹陷\n"
            "质量越大 · 距离越近 · 凹陷越深"))
        self.btn_gravity.setToolTip(tr("打开引力系统视图（快捷键 G）"))
        self._foot.setText(tr("三个视图共用同一套数据与时间系统；"
                              "可用主窗口工具栏的「切换模式」随时返回本窗口。"))

    # ---------- 模式切换 ----------
    def show_mode(self, mode):
        """显示指定模式的主窗口，并隐藏另一个；关闭启动器"""
        try:
            if mode == "3d":
                if self.win3d is None:
                    from ui.main_window import MainWindow
                    self.win3d = MainWindow(self.bodies, self.stars)
                    self.win3d.set_switch_callback(self.reopen)
                if self.win2d is not None:
                    self.win2d.hide()
                if self.win_gravity is not None:
                    self.win_gravity.hide()
                display_mode.apply_display_mode(
                    self.win3d, app_settings.get_display_mode())
            elif mode == "2d":
                if self.win2d is None:
                    from ui.main_window_2d import MainWindow2D
                    self.win2d = MainWindow2D(self.bodies, self.stars,
                                              on_switch_mode=self.reopen)
                if self.win3d is not None:
                    self.win3d.hide()
                if self.win_gravity is not None:
                    self.win_gravity.hide()
                display_mode.apply_display_mode(
                    self.win2d, app_settings.get_display_mode())
            elif mode == "gravity":
                if self.win_gravity is None:
                    from ui.main_window_gravity import GravityWindow
                    self.win_gravity = GravityWindow(self.bodies, self.stars)
                    self.win_gravity.set_switch_callback(self.reopen)
                if self.win3d is not None:
                    self.win3d.hide()
                if self.win2d is not None:
                    self.win2d.hide()
                display_mode.apply_display_mode(
                    self.win_gravity, app_settings.get_display_mode())
        except Exception:
            # 打包为 --windowed 后 stderr 不可见，异常会被静默吞掉，
            # 表现为「点了没反应」。此处显式弹窗提示，并保留启动器窗口。
            import traceback
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, "无法打开视图",
                "打开 %s 视图时出错：\n\n%s"
                % (mode.upper(), traceback.format_exc()[-1600:]))
            return
        self.hide()

    def reopen(self):
        """主窗口「切换模式」回调：重新显示启动器"""
        self.show()
        self.raise_()
        self.activateWindow()

    # ---------- 快捷键 ----------
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_3:
            self.show_mode("3d")
        elif ev.key() == Qt.Key_2:
            self.show_mode("2d")
        elif ev.key() == Qt.Key_G:
            self.show_mode("gravity")
        else:
            super().keyPressEvent(ev)