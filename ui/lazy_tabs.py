"""
lazy_tabs.py —— QTabWidget 面板懒加载管理器

matplotlib 面板（对比分析 / 观测特征 / 科研计算 / 地面视角）首次切入
对应标签页、或代码首次访问时才 import + 构造，把 matplotlib 的导入
成本（约 1s）移出主窗口打开的关键路径。

线程说明：本类仅在 GUI 线程使用（QTabWidget 限制）。
"""
from PyQt5.QtWidgets import QWidget


class LazyTabManager:
    """占位标签页 + 按需原位替换。

    用法：
        mgr = LazyTabManager(right_tabs)
        mgr.add_lazy_tab("sky", "地面视角", factory, on_created)
        panel = mgr.ensure("sky")      # 需要时创建（幂等）
        panel = mgr.get("sky")         # 仅取已创建的，不触发创建
    """

    def __init__(self, tab_widget):
        self._tabs = tab_widget
        self._specs = {}      # key -> {factory, title, index, on_created}
        self._created = {}    # key -> panel 实例
        tab_widget.currentChanged.connect(self._on_current_changed)

    def add_lazy_tab(self, key, title, factory, on_created=None):
        """添加占位标签页。factory() 返回真面板；on_created(key, panel) 在
        面板创建后回调（用于依赖注入 / 定时器连接）。"""
        index = self._tabs.addTab(QWidget(), title)
        self._specs[key] = {"factory": factory, "title": title,
                            "index": index, "on_created": on_created}
        return index

    def ensure(self, key):
        """返回面板；未创建则先创建并原位替换占位页（幂等、可重入）。"""
        if key in self._created:
            return self._created[key]
        spec = self._specs.get(key)
        if spec is None:
            return None
        panel = spec["factory"]()
        self._created[key] = panel
        index = spec["index"]
        self._tabs.removeTab(index)
        self._tabs.insertTab(index, panel, spec["title"])
        self._tabs.setCurrentIndex(index)
        cb = spec.get("on_created")
        if cb is not None:
            cb(key, panel)
        return panel

    def get(self, key):
        """仅返回已创建的面板（绝不触发创建），未创建返回 None。"""
        return self._created.get(key)

    def _on_current_changed(self, index):
        for key, spec in self._specs.items():
            if spec["index"] == index:
                self.ensure(key)
                return