"""
widgets.py —— 通用小控件辅助

`make_searchable`：把下拉框变成「可下拉逐个选 + 可直接输入搜索」的二合一控件。
`resolve_combo_text`：把可编辑下拉框里的输入文本解析回列表中的真实条目。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


def make_searchable(combo: QComboBox, placeholder: str = "输入名称搜索…") -> QComboBox:
    """让下拉框既可下拉逐个选，也可直接输入关键字搜索（两种方式并存）。

    - 不区分大小写、子串匹配（输入任意片段即可命中）
    - NoInsert：输入过程中不被强制改写，回车/选中才生效
    - 下拉箭头仍可展开完整列表
    """
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMaxVisibleItems(20)
    comp = QCompleter(combo.model(), combo)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    comp.setCompletionMode(QCompleter.PopupCompletion)
    combo.setCompleter(comp)
    if placeholder and combo.lineEdit() is not None:
        combo.lineEdit().setPlaceholderText(placeholder)
    return combo


def resolve_combo_text(combo: QComboBox) -> str:
    """把可编辑下拉框的输入文本解析为列表中的真实条目名。

    精确匹配优先；否则取子串匹配的第一项（输入过程中即时生效）。
    若输入框正在被编辑，则不改写框内文字，只返回匹配到的条目名，
    避免用户打字打到一半被强制替换。
    """
    txt = combo.currentText().strip()
    if not txt:
        return ""
    idx = combo.findText(txt, Qt.MatchFixedString)
    if idx < 0:
        idx = combo.findText(txt, Qt.MatchContains)
    if idx < 0:
        return txt
    le = combo.lineEdit()
    editing = le is not None and le.hasFocus()
    if not editing:
        combo.setCurrentIndex(idx)
    return combo.itemText(idx)