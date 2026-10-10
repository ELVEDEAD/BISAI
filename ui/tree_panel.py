"""
tree_panel.py —— 左侧天体树面板（模块 J）

按「恒星系（系群）」归类：一颗宿主恒星 + 其行星归为一个恒星系。
    恒星系（系群）
      ├ 太阳系 · 9 颗行星 · 12 颗卫星          ← 默认展开
      │   ├ 太阳
      │   ├ 水星 / 金星 / 地球 / 火星 / …
      │   │   └ 月球（挂在地球下）
      │   └ 冥王星（矮行星）
      ├ TRAPPIST-1 系 · M8V · 7 颗行星 · 12.5 光年   ← 展开时懒加载
      │   ├ TRAPPIST-1 b / c / d / e / f / g / h
      └ …（其余恒星系，按行星数降序 → 名称）

- 点击天体 → 选中 + 聚焦到视口 + 显示详情面板
- 点击恒星系节点 → 右侧详情面板显示「恒星系概览」（宿主恒星参数 + 成员行星）
- 搜索过滤：实时匹配天体名（中/英）与恒星系名；命中懒加载系群时自动展开生成子节点
- 系外恒星系采用懒加载（首次展开时才生成子节点），避免数千个节点一次性构建
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget,
                             QTreeWidgetItem, QLineEdit, QLabel)

from data.loader import BODY_TYPE_LABELS, group_by_system
from ui import style
from core.i18n import tr

ROLE_BODY = Qt.UserRole            # 天体条目存 Body
ROLE_GROUP = Qt.UserRole + 1       # 恒星系节点存 SystemGroup
ROLE_LAZY = Qt.UserRole + 2        # 该恒星系节点尚未生成子节点（懒加载占位）

# 特殊顶层分组（非恒星系，直接展示成员列表）
_SPECIAL_GROUPS = {"黑洞", "极端海外天体", "近邻恒星", "星际天体"}


class TreePanel(QWidget):
    """左侧天体树：搜索 + 恒星系分组 + 点击聚焦"""
    bodyClicked = pyqtSignal(object)      # 点击天体（Body 对象）
    systemClicked = pyqtSignal(object)    # 点击恒星系节点（SystemGroup 对象）

    def __init__(self, bodies, parent=None):
        super().__init__(parent)
        self.bodies = list(bodies)
        self._groups = group_by_system(self.bodies)
        self._group_items = []                 # [(QTreeWidgetItem, SystemGroup)]
        self._name_to_group = {}               # {天体名: SystemGroup}
        self._bh_group = None                  # 黑洞特殊组（None 表示无黑洞）
        self._special_groups = {}              # {组名: SystemGroup}（特殊顶层分组）
        for g in self._groups:
            if g.host in _SPECIAL_GROUPS:
                self._special_groups[g.host] = g
                if g.host == "黑洞":
                    self._bh_group = g
                for b in g.planets:
                    self._name_to_group[b.name] = g
                continue
            if g.star is not None:
                self._name_to_group[g.star.name] = g
            for b in g.planets:
                self._name_to_group[b.name] = g
            for m in g.moons:
                self._name_to_group[m.name] = g
        self.setMinimumWidth(220)
        self._build_ui()
        self._populate()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText(tr("搜索天体 / 恒星系名称…"))
        self.edit_search.textChanged.connect(self._filter)
        layout.addWidget(self.edit_search)

        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(
            f"color: {style.palette()['TEXT_DIM']}; font-size: 10px;")
        self.lbl_count.setWordWrap(True)
        layout.addWidget(self.lbl_count)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        layout.addWidget(self.tree, 1)

    # ---------- 构建 ----------
    def _populate(self):
        self.tree.clear()
        self._group_items = []

        root = QTreeWidgetItem([tr("恒星系（系群）")])
        root.setExpanded(True)
        self.tree.addTopLevelItem(root)

        # 特殊顶层分组（黑洞、极端海外天体、近邻恒星、星际天体）
        _special_order = ["极端海外天体", "近邻恒星", "星际天体", "黑洞"]
        _special_tooltips = {
            "极端海外天体": "极端海外天体（ETNO）\n半长轴 >250 AU 的分离型天体\n数据来源：MPC/JPL 轨道根数",
            "近邻恒星": "太阳系周边近邻恒星\n数据来源：RECONS / CNS5 / Gaia DR3",
            "星际天体": "已确认的星际天体（双曲轨道）\n数据来源：MPC 轨道根数",
            "黑洞": "恒星级 / 中等质量 / 超大质量黑洞\n参与引力网格时空扭曲",
        }
        for sname in _special_order:
            sg = self._special_groups.get(sname)
            if sg is None:
                continue
            label = f"{tr(sname)}（{len(sg.planets)}）"
            s_root = QTreeWidgetItem([label])
            s_root.setExpanded(False)
            s_root.setData(0, ROLE_GROUP, sg)
            s_root.setToolTip(0, _special_tooltips.get(sname, sname))
            for b in sg.planets:
                s_root.addChild(self._make_body_item(b))
            self.tree.addTopLevelItem(s_root)

        for g in self._groups:
            if g.host in _SPECIAL_GROUPS:
                continue           # 特殊组已单独处理
            node = QTreeWidgetItem([self._group_label(g)])
            node.setData(0, ROLE_GROUP, g)
            node.setToolTip(0, self._group_tooltip(g))
            if g.is_solar:
                node.setExpanded(True)
                self._fill_solar(node, g)
            else:
                node.setExpanded(False)
                self._add_placeholder(node)
            root.addChild(node)
            self._group_items.append((node, g))

        self._set_full_count()

    def _group_label(self, g):
        if g.is_solar:
            txt = f"{tr('太阳系')} · {g.n_planets} {tr('颗行星')}"
            if g.moons:
                txt += f" · {len(g.moons)} {tr('颗卫星')}"
            return txt
        parts = [f"{g.host} {tr('系')}"]
        if g.spec:
            parts.append(g.spec)
        parts.append(f"{g.n_planets} {tr('颗行星')}")
        if g.dist_pc:
            parts.append(f"{g.dist_pc / 0.3066:.4g} {tr('光年')}")
        return " · ".join(parts)

    def _group_tooltip(self, g):
        if g.is_solar:
            return ("恒星系：太阳系\n宿主恒星：太阳（G2V）\n"
                    f"成员：太阳 + {g.n_planets} 颗行星（含矮行星）+ "
                    f"{len(g.moons)} 颗天然卫星")
        lines = [f"恒星系：{g.host} 系"]
        if g.spec:
            lines.append(f"恒星光度型：{g.spec}")
        if g.host_teff:
            lines.append(f"有效温度：{g.host_teff:.0f} K")
        if g.host_mass_solar:
            lines.append(f"质量：{g.host_mass_solar:.3g} M☉")
        if g.dist_pc:
            lines.append(f"距离：{g.dist_pc:.4g} pc ≈ {g.dist_pc / 0.3066:.4g} 光年")
        lines.append(f"已确认行星：{g.n_planets} 颗")
        return "\n".join(lines)

    def _make_body_item(self, b):
        item = QTreeWidgetItem([b.name])
        item.setData(0, ROLE_BODY, b)
        tip = BODY_TYPE_LABELS.get(b.body_type, b.body_type)
        if b.en_name:
            tip += f" | {b.en_name}"
        if b.body_type == "moon" and b.parent_name:
            tip += f"（母行星：{b.parent_name}）"
        item.setToolTip(0, tip)
        return item

    def _fill_solar(self, node, g):
        """太阳系：太阳 + 行星/矮行星，天然卫星挂到母行星下"""
        planet_items = {}
        if g.star is not None:
            node.addChild(self._make_body_item(g.star))
        for b in g.planets:
            item = self._make_body_item(b)
            node.addChild(item)
            planet_items[b.name] = item
        for m in g.moons:
            parent_item = planet_items.get(m.parent_name)
            if parent_item is not None:
                parent_item.addChild(self._make_body_item(m))

    def _add_placeholder(self, node):
        node.addChild(QTreeWidgetItem(["…"]))
        node.setData(0, ROLE_LAZY, True)

    def _on_item_expanded(self, item):
        self._ensure_populated(item)

    def _ensure_populated(self, node):
        """懒加载：首次展开恒星系节点时生成成员条目（宿主恒星 + 行星）"""
        if not node.data(0, ROLE_LAZY):
            return
        g = node.data(0, ROLE_GROUP)
        node.takeChildren()
        # 宿主恒星（若有）放在最前面
        if g.star is not None:
            node.addChild(self._make_body_item(g.star))
        for b in g.planets:
            node.addChild(self._make_body_item(b))
        node.setData(0, ROLE_LAZY, False)

    def _set_full_count(self):
        n_exo = sum(g.n_planets for g in self._groups
                    if not g.is_solar and g.host not in _SPECIAL_GROUPS)
        n_moon = sum(len(g.moons) for g in self._groups)
        n_solar = next((g.n_planets for g in self._groups if g.is_solar), 0)
        n_host = sum(1 for g in self._groups
                     if not g.is_solar and g.host not in _SPECIAL_GROUPS
                     and g.star is not None)
        n_bh = len(self._special_groups.get("黑洞").planets) if "黑洞" in self._special_groups else 0
        n_etno = len(self._special_groups.get("极端海外天体").planets) if "极端海外天体" in self._special_groups else 0
        n_nearby = len(self._special_groups.get("近邻恒星").planets) if "近邻恒星" in self._special_groups else 0
        n_iso = len(self._special_groups.get("星际天体").planets) if "星际天体" in self._special_groups else 0
        n_systems = len([g for g in self._groups if g.host not in _SPECIAL_GROUPS])
        parts = [f"{tr('共')} {len(self.bodies)} {tr('个天体')} · {tr('恒星系')} {n_systems}"]
        if n_bh:
            parts.append(f"{tr('黑洞')} {n_bh}")
        if n_etno:
            parts.append(f"ETNO {n_etno}")
        if n_nearby:
            parts.append(f"{tr('近邻恒星')} {n_nearby}")
        if n_iso:
            parts.append(f"{tr('星际天体')} {n_iso}")
        line1 = " · ".join(parts)
        line2 = (f"{tr('宿主恒星')} {n_host} + {tr('太阳系')} {n_solar} + "
                 f"{tr('卫星')} {n_moon} + {tr('系外行星')} {n_exo}")
        self.lbl_count.setText(f"{line1}\n{line2}")

    # ---------- 交互 ----------
    def _on_item_clicked(self, item, column):
        body = item.data(0, ROLE_BODY)
        if body is not None:
            self.bodyClicked.emit(body)
            return
        group = item.data(0, ROLE_GROUP)
        if group is not None:
            self.systemClicked.emit(group)

    def _filter(self, text):
        """搜索过滤：匹配天体中/英文名与恒星系名；命中懒加载系群时先展开生成子节点"""
        text = text.strip().lower()
        if not text:
            self._restore_all()
            return
        for node, g in self._group_items:
            if g.is_solar or not node.data(0, ROLE_LAZY):
                continue
            if text in g.host.lower() or any(
                    text in b.name.lower() or text in (b.en_name or "").lower()
                    for b in g.planets):
                self._ensure_populated(node)

        matched = [0]

        def visit(item, force=False):
            body = item.data(0, ROLE_BODY)
            group = item.data(0, ROLE_GROUP)
            hit = False
            if body is not None:
                hit = (text in body.name.lower()
                       or text in (body.en_name or "").lower())
                if hit:
                    matched[0] += 1
            elif group is not None:
                hit = text in group.host.lower()
            force_child = force or (group is not None and hit)
            child_hit = False
            for j in range(item.childCount()):
                if visit(item.child(j), force_child):
                    child_hit = True
            show = force or hit or child_hit
            item.setHidden(not show)
            if child_hit or (group is not None and hit):
                item.setExpanded(True)
            return show

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
        self.lbl_count.setText(f"{tr('匹配')} {matched[0]} {tr('个天体')}")

    def _restore_all(self):
        def visit(item):
            item.setHidden(False)
            for j in range(item.childCount()):
                visit(item.child(j))
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
        for node, g in self._group_items:
            node.setExpanded(g.is_solar)
        self._set_full_count()

    # ---------- 外部调用 ----------
    def select_body(self, name):
        """在树中选中并滚动到指定天体（懒加载系群会先展开）"""
        group = self._name_to_group.get(name)
        if group is not None:
            for node, g in self._group_items:
                if g is group:
                    self._ensure_populated(node)
                    node.setExpanded(True)
                    break
        item = self._find_item(name)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _find_item(self, name):
        def search(item):
            body = item.data(0, ROLE_BODY)
            if body is not None and body.name == name:
                return item
            for j in range(item.childCount()):
                found = search(item.child(j))
                if found is not None:
                    return found
            return None
        for i in range(self.tree.topLevelItemCount()):
            found = search(self.tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    # ---------- 语言 / 主题 ----------
    def retranslate(self):
        """语言变化：重建树文字（保留当前搜索过滤）。"""
        self.edit_search.setPlaceholderText(tr("搜索天体 / 恒星系名称…"))
        self._populate()
        text = self.edit_search.text().strip()
        if text:
            self._filter(text)

    def restyle(self):
        self.lbl_count.setStyleSheet(
            f"color: {style.palette()['TEXT_DIM']}; font-size: 10px;")