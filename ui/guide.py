"""
guide.py —— 新手引导教程（模块 N）

首次启动时引导用户完成完整操作流程：
  1. 视角操作介绍（旋转/缩放/平移）
  2. 搜索天体
  3. 选中行星并查看详情
  4. 选中两颗行星进行相对运动分析
  5. 时间控制与倍速

使用半透明覆盖层 + 步骤提示卡片，可随时跳过或回看。
排版遵循 Blender 式简洁专业风格：紧凑、层级清晰、标题与正文分色。
"""
import os
import json

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFrame, QCheckBox,
                             QScrollArea, QSizePolicy)

from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT, BG_PANEL, BG_PANEL_LIGHT, BORDER

GUIDE_FLAG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", ".guide_completed"))


GUIDE_STEPS = [
    {
        "title": "欢迎使用已知行星可视化",
        "body": ("本软件展示太阳系八大行星、矮行星、5700+ 颗系外行星、8 个黑洞、"
                 "近邻恒星与星际天体的三维位置与轨道。\n\n"
                 "接下来用 5 步快速了解核心操作（可随时跳过）。"),
        "highlight": None,
    },
    {
        "title": "第 1 步：视角操作",
        "body": ("• 中键拖拽 —— 旋转视角\n"
                 "• Shift+中键 —— 平移视角\n"
                 "• 滚轮 —— 缩放（远近自适应）\n"
                 "• 右键 —— 上下文菜单\n\n"
                 "试试旋转视角观察太阳系全貌。\n"
                 "Numpad 1/3/7 = 正/侧/俯视图，Numpad . = 聚焦选中天体。"),
        "highlight": "viewport",
    },
    {
        "title": "第 2 步：搜索天体",
        "body": ("顶部搜索栏输入天体名称（中/英文均可），\n"
                 "例如：地球、火星、Kepler-186 f、Proxima\n\n"
                 "左侧天体树也可浏览所有天体，\n"
                 "按恒星系分组，点击即可聚焦。"),
        "highlight": "search",
    },
    {
        "title": "第 3 步：选中行星并查看详情",
        "body": ("左键点击视口中的天体即可选中，\n"
                 "右侧详情面板会显示该天体的完整数据\n"
                 "（轨道根数、物理参数、精度等级等）。\n\n"
                 "缺失数据如实标注「未知」，不伪造。"),
        "highlight": "detail",
    },
    {
        "title": "第 4 步：对比两颗行星",
        "body": ("右键点击天体 →「加入对比」，选两颗后\n"
                 "切换到右侧「对比分析」标签页，\n"
                 "可查看相对运动轨迹、距离/速度曲线、会合周期。\n\n"
                 "支持 4 种参考系切换、全屏放大与 CSV/PNG 导出。"),
        "highlight": "compare",
    },
    {
        "title": "第 5 步：时间控制",
        "body": ("底部时间轴：播放/暂停、倒放、9 档倍速、\n"
                 "日期跳转（日历点选或手动输入微调）。\n"
                 "倍速从实时×1 到 100年/秒，可快速观察行星运动。\n\n"
                 "空格键 = 播放/暂停，F1 = 帮助。"),
        "highlight": "timeline",
    },
    {
        "title": "准备就绪！",
        "body": ("你已掌握所有核心操作。\n\n"
                 "更多功能：\n"
                 "• 尺寸对比：详情面板 →「尺寸对比」按钮\n"
                 "• 引力系统：切换模式 → 引力系统视图\n"
                 "• 天象推演 / 地面视角 / 地表视角\n"
                 "• 设置：工具栏 →「设置」（显示模式、帧率限制等）\n"
                 "• 教学场景：工具栏 →「教学场景」\n"
                 "• 飞行模式：Shift+~ 进入自由漫游"),
        "highlight": None,
    },
]


class GuideDialog(QDialog):
    """新手引导对话框（步骤卡片式，Blender 风排版）"""
    guideFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新手引导")
        self.setModal(True)
        self.resize(480, 380)
        self.setStyleSheet(self._qss())
        self._step = 0
        self._build_ui()
        self._show_step()

    def _qss(self):
        return f"""
QDialog {{ background-color: {BG_PANEL}; }}
QPushButton#guideBtn {{
    background-color: #3a3a3a;
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 12px;
}}
QPushButton#guideBtn:hover {{ background-color: #4a4a4a; }}
QPushButton#guideBtn:disabled {{ color: #555; }}
QPushButton#guideBtnPrimary {{
    background-color: #5a3a20;
    color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: bold;
}}
QPushButton#guideBtnPrimary:hover {{ background-color: #6a4a28; }}
QLabel#guideTitle {{ color: {ACCENT}; font-size: 16px; font-weight: bold; }}
QLabel#guideBody {{ color: {TEXT_MAIN}; font-size: 13px; line-height: 1.6; }}
QLabel#guideStep {{ color: {TEXT_DIM}; font-size: 11px; }}
QCheckBox {{ color: {TEXT_DIM}; font-size: 11px; }}
QFrame#guideSep {{ background-color: {BORDER}; max-height: 1px; }}
"""

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        self.lbl_title = QLabel("")
        self.lbl_title.setObjectName("guideTitle")
        layout.addWidget(self.lbl_title)

        sep = QFrame()
        sep.setObjectName("guideSep")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        self.lbl_body = QLabel("")
        self.lbl_body.setObjectName("guideBody")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setTextFormat(Qt.PlainText)
        self.lbl_body.setMinimumHeight(140)
        layout.addWidget(self.lbl_body, 1)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("guideStep")
        layout.addWidget(self.lbl_progress)

        sep2 = QFrame()
        sep2.setObjectName("guideSep")
        sep2.setFrameShape(QFrame.HLine)
        layout.addWidget(sep2)

        btn_row = QHBoxLayout()
        self.chk_skip = QCheckBox("不再显示")
        btn_row.addWidget(self.chk_skip)
        btn_row.addStretch()

        self.btn_prev = QPushButton("上一步")
        self.btn_prev.setObjectName("guideBtn")
        self.btn_prev.clicked.connect(self._prev)
        btn_row.addWidget(self.btn_prev)

        self.btn_next = QPushButton("下一步")
        self.btn_next.setObjectName("guideBtnPrimary")
        self.btn_next.clicked.connect(self._next)
        btn_row.addWidget(self.btn_next)

        self.btn_skip = QPushButton("跳过引导")
        self.btn_skip.setObjectName("guideBtn")
        self.btn_skip.clicked.connect(self._skip)
        btn_row.addWidget(self.btn_skip)

        layout.addLayout(btn_row)

    def _show_step(self):
        step = GUIDE_STEPS[self._step]
        self.lbl_title.setText(step["title"])
        self.lbl_body.setText(step["body"])
        self.lbl_progress.setText(
            f"步骤 {self._step + 1} / {len(GUIDE_STEPS)}")
        self.btn_prev.setEnabled(self._step > 0)
        is_last = (self._step == len(GUIDE_STEPS) - 1)
        self.btn_next.setText("完成" if is_last else "下一步")

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _next(self):
        if self._step < len(GUIDE_STEPS) - 1:
            self._step += 1
            self._show_step()
        else:
            self._finish()

    def _skip(self):
        self._finish()

    def _finish(self):
        if self.chk_skip.isChecked():
            try:
                with open(GUIDE_FLAG_FILE, "w") as f:
                    json.dump({"completed": True}, f)
            except Exception:
                pass
        self.guideFinished.emit()
        self.accept()


def should_show_guide() -> bool:
    """是否应该显示新手引导（首次启动或未标记完成）"""
    return not os.path.exists(GUIDE_FLAG_FILE)


def mark_guide_completed():
    """标记引导已完成"""
    try:
        with open(GUIDE_FLAG_FILE, "w") as f:
            json.dump({"completed": True}, f)
    except Exception:
        pass