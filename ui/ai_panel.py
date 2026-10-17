"""ai_panel.py —— 大模型 AI 对话 / 问答面板

内置天文助手：可就天文知识、行星信息、系外行星、天象等提问，回答来自
用户配置的大模型 API（OpenAI 兼容接口，见 core/llm_client.py）。

要点：
    * API Key / 地址 / 模型在「设置 → 大模型」中配置，本面板只负责对话；
    * 网络请求在后台线程执行，界面不卡顿，状态行给出「思考中 / 成功 / 失败」反馈；
    * 自动附带当前选中天体的上下文（由主窗口 set_context 注入），回答更贴合画面；
    * 文字随界面语言与主题、字号即时重建（沿用既有监听机制）。
"""
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser,
                             QPlainTextEdit, QPushButton, QLabel, QSizePolicy)

from core import i18n, app_settings, llm_client
from core.i18n import tr
from ui import style

_MAX_HISTORY_TURNS = 8          # 最多保留的历史轮数（不含系统提示）


class _ChatWorker(QObject):
    """后台执行一次对话补全，避免阻塞界面。"""
    done = pyqtSignal(bool, str, str)      # ok, text, err

    def __init__(self, cfg, messages, temperature=0.6):
        super().__init__()
        self.cfg = cfg
        self.messages = messages
        self.temperature = temperature

    def run(self):
        ok, text, err = llm_client.chat(
            self.cfg.get("base_url", ""), self.cfg.get("api_key", ""),
            self.cfg.get("model", ""), self.messages,
            temperature=self.temperature)
        self.done.emit(ok, text, err)


class AIPanel(QWidget):
    """天文助手对话面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []              # [(role, content)] 不含 system
        self._context = ""              # 当前天体上下文（附加到提问前）
        self._busy = False
        self._thread = None
        self._worker = None
        self._pending_user = ""
        self._build_ui()
        i18n.add_listener(self.retranslate)
        style.add_theme_listener(self.restyle)
        self.retranslate()
        self.restyle()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.lbl_title = QLabel()
        layout.addWidget(self.lbl_title)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.view, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.lbl_status = QLabel()
        row.addWidget(self.lbl_status, 1)
        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self.clear_chat)
        row.addWidget(self.btn_clear)
        layout.addLayout(row)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(tr("输入天文问题…（Ctrl+Enter 发送）"))
        self.input.setFixedHeight(84)
        layout.addWidget(self.input)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_send = QPushButton()
        self.btn_send.setDefault(True)
        self.btn_send.clicked.connect(self.send)
        btn_row.addWidget(self.btn_send)
        layout.addLayout(btn_row)

    # ---------------------------------------------------------------- 文字 / 样式
    def retranslate(self):
        self.lbl_title.setText(
            "<b>" + tr("天文助手") + "</b>"
            + f"<span style='color:{style.palette()['TEXT_DIM']};'> &nbsp;"
            + tr("基于大模型 API（在「设置 → 大模型」中配置）") + "</span>")
        self.btn_send.setText(tr("发送"))
        self.btn_clear.setText(tr("清空对话"))
        self.input.setPlaceholderText(tr("输入天文问题…（Ctrl+Enter 发送）"))
        if not self._busy:
            self._set_status(tr("就绪"), style.palette()["TEXT_DIM"])

    def restyle(self):
        p = style.palette()
        self.lbl_title.setText(
            "<b>" + tr("天文助手") + "</b>"
            + f"<span style='color:{p['TEXT_DIM']};'> &nbsp;"
            + tr("基于大模型 API（在「设置 → 大模型」中配置）") + "</span>")
        self.view.setStyleSheet(
            f"background-color: {p['BG_MAIN']}; border: 1px solid {p['BORDER']};"
            f"border-radius: 6px; padding: 6px;")

    def _set_status(self, text, color=None):
        c = color or style.palette()["TEXT_DIM"]
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {c};")

    # ---------------------------------------------------------------- 上下文
    def set_context(self, text: str):
        """注入当前选中天体的上下文（主窗口在选中变化时调用）。"""
        self._context = (text or "").strip()

    # ---------------------------------------------------------------- 对话
    def clear_chat(self):
        self._history = []
        self.view.clear()
        self._set_status(tr("就绪"), style.palette()["TEXT_DIM"])

    def _append(self, role: str, text: str):
        p = style.palette()
        if role == "user":
            head = tr("我"); color = p["ACCENT_BLUE"]
        elif role == "assistant":
            head = tr("助手"); color = p["ACCENT"]
        else:
            head = tr("系统"); color = p["TEXT_DIM"]
        import html
        body = html.escape(text).replace("\n", "<br>")
        self.view.append(
            f"<div style='margin:6px 0;'>"
            f"<span style='color:{color};'><b>{head}</b></span><br>"
            f"<span style='color:{p['TEXT_MAIN']};'>{body}</span></div>")
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().maximum())

    def keyPressEvent(self, ev):
        if (ev.key() in (Qt.Key_Return, Qt.Key_Enter)
                and (ev.modifiers() & Qt.ControlModifier)):
            self.send()
            return
        super().keyPressEvent(ev)

    def send(self):
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        cfg = app_settings.get_llm_config()
        if not cfg.get("api_key"):
            self._set_status(tr("未配置 API Key，请在「设置 → 大模型」中填写。"),
                             style.palette()["ACCENT"])
            return

        self.input.clear()
        prompt = text
        if self._context:
            prompt = f"（当前上下文：{self._context}）\n{text}"
        self._append("user", text)

        messages = llm_client.build_messages(prompt, self._history[-2 * _MAX_HISTORY_TURNS:])
        self._pending_user = text
        self._busy = True
        self.btn_send.setEnabled(False)
        self._set_status(tr("思考中…（正在调用大模型 API）"), style.palette()["ACCENT_BLUE"])

        self._thread = QThread(self)
        self._worker = _ChatWorker(cfg, messages)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_done(self, ok, text, err):
        self._busy = False
        self.btn_send.setEnabled(True)
        if ok:
            self._append("assistant", text)
            pending = getattr(self, "_pending_user", "")
            if pending:
                self._history.append(("user", pending))
            self._history.append(("assistant", text))
            self._history = self._history[-2 * _MAX_HISTORY_TURNS:]
            self._set_status(tr("已回复"), style.palette()["ACCENT"])
        else:
            self._append("system", err)
            self._set_status(tr("调用失败：") + err, style.palette()["ACCENT"])

    def _cleanup_thread(self):
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def closeEvent(self, ev):
        i18n.remove_listener(self.retranslate)
        style.remove_theme_listener(self.restyle)
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1500)
        super().closeEvent(ev)