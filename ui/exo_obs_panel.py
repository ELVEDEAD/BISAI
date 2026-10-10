"""
exo_obs_panel.py —— 系外行星观测特征面板

把 core/exo_obs.py 的解析结果画成三张图，供「我们看到的证据」与轨道参数对照：
  1) 凌星光变曲线：亮度随时间的凹陷，含撞击参数 b 的不确定性包络（b 未测定）
  2) 视向速度曲线：恒星谱线的周期性摆动，含近心点幅角 ω 的不确定性族
  3) 宜居带：Kopparapu 2013 的保守 / 乐观边界，并标出本恒星系各行星位置

下方给出参数表（缺失一律「未知」）与科学诚实性说明。图表全部由行星/宿主星
参数解析算出，可复现、无随机数。
"""
import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QSlider,
                             QScrollArea, QFileDialog, QFrame)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib import rcParams
from matplotlib import ticker as mticker

rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False

from core import exo_obs as E
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT
from ui.widgets import make_searchable, resolve_combo_text

MPL_BG = "#252526"
MPL_AX = "#2b2b2b"
MPL_GRID = "#404040"

CHART_TRANSIT = "transit"
CHART_RV = "rv"
CHART_HZ = "hz"
CHART_LABELS = {
    CHART_TRANSIT: "凌星光变曲线",
    CHART_RV: "视向速度曲线",
    CHART_HZ: "宜居带",
}

# 首次打开时的候选默认天体（优先选数据齐全、具代表性的凌星行星）
DEFAULT_CANDIDATES = ("HD 209458 b", "TRAPPIST-1 e", "Kepler-452 b",
                      "Proxima Cen b", "51 Peg b")


def _short_label(name: str, host: str) -> str:
    """把「宿主星 + 序号」形式的名字缩短为序号（TRAPPIST-1 e → e），减少重叠"""
    for sep in (" ", "-", "_"):
        pref = host + sep
        if name.lower().startswith(pref.lower()) and len(name) > len(pref):
            return name[len(pref):].strip(" -_") or name
    return name


def _plain_num(v, _pos=None) -> str:
    """对数轴刻度用普通小数显示（避免 10⁻² 这类科学计数）"""
    if v >= 1.0:
        return f"{v:g}"
    return f"{v:.3f}".rstrip("0").rstrip(".")


class ExoObsPanel(QWidget):
    """系外行星观测特征面板（凌星 / 视向速度 / 宜居带）"""

    def __init__(self, viewport=None, bodies=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.bodies = list(bodies or (getattr(viewport, "bodies", None) or []))
        self._by_name = {b.name: b for b in self.bodies}
        self._body = None
        self._dirty = True
        self._auto_done = False
        self.setMinimumWidth(300)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        head = QLabel("观测特征")
        head.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 15px; font-weight: bold;")
        layout.addWidget(head)

        sub = QLabel("凌星光变 / 视向速度 / 宜居带——从行星与宿主星参数解析推算")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        layout.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel("天体:"), 0, 0)
        self.cmb_body = QComboBox()
        self.cmb_body.addItems([b.name for b in self.bodies] or ["（无数据）"])
        make_searchable(self.cmb_body, "搜索天体…")
        self.cmb_body.lineEdit().returnPressed.connect(self._on_body_pick)
        self.cmb_body.activated.connect(self._on_body_pick)
        grid.addWidget(self.cmb_body, 0, 1)

        grid.addWidget(QLabel("图表:"), 1, 0)
        self.cmb_chart = QComboBox()
        for key in (CHART_TRANSIT, CHART_RV, CHART_HZ):
            self.cmb_chart.addItem(CHART_LABELS[key], key)
        self.cmb_chart.currentIndexChanged.connect(self._redraw)
        grid.addWidget(self.cmb_chart, 1, 1)
        layout.addLayout(grid)

        # 撞击参数 b（仅凌星图使用）
        self.row_b = QWidget()
        rb = QHBoxLayout(self.row_b)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(6)
        self.lbl_b = QLabel("撞击参数 b = 0.00")
        self.lbl_b.setStyleSheet(f"color: {TEXT_DIM};")
        rb.addWidget(self.lbl_b)
        self.slider_b = QSlider(Qt.Horizontal)
        self.slider_b.setRange(0, 100)
        self.slider_b.setValue(0)
        self.slider_b.setToolTip(
            "b = 行星中心与恒星视面中心的最小距离（以恒星半径为单位）。\n"
            "b 取决于轨道倾角，多数行星未测定；拖动可查看不同 b 下的凌星形态，\n"
            "图中阴影带为 b ∈ [0, 1] 的全部可能范围。")
        self.slider_b.valueChanged.connect(self._on_b_changed)
        rb.addWidget(self.slider_b, 1)
        layout.addWidget(self.row_b)

        # 图表
        self.fig = Figure(figsize=(4, 3), dpi=100, facecolor=MPL_BG)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(200)
        layout.addWidget(self.canvas, 1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #252525;")
        layout.addWidget(line)

        # 参数表（可滚动）
        self.tbl_host = QWidget()
        self.tbl_grid = QGridLayout(self.tbl_host)
        self.tbl_grid.setContentsMargins(2, 2, 2, 2)
        self.tbl_grid.setVerticalSpacing(3)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.tbl_host)
        area.setFrameShape(QFrame.NoFrame)
        area.setMinimumHeight(120)
        layout.addWidget(area, 1)

        foot = QHBoxLayout()
        self.lbl_grade = QLabel("")
        self.lbl_grade.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        foot.addWidget(self.lbl_grade, 1)
        btn_png = QPushButton("导出 PNG")
        btn_png.clicked.connect(self._export_png)
        foot.addWidget(btn_png)
        layout.addLayout(foot)

        self.lbl_note = QLabel(
            "说明：光变曲线为几何遮挡解析解（不含临边昏暗与行星自身辐射）；"
            "视向速度取 sin i = 1，故 K 为最小值；宜居带采用 Kopparapu et al. 2013 "
            "的 Seff 多项式（适用恒星 2600–7200 K）。缺参数一律标「未知」，不作假设填充。")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        layout.addWidget(self.lbl_note)

    # ---------- 首次显示 ----------
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._auto_done:
            self._auto_done = True
            # 若已由主窗口设过天体（例如从详情面板点「观测特征」进入），保持不放
            if self._body is None:
                self.set_body(self._pick_default())
            else:
                self._redraw()
        elif self._dirty:
            self._redraw()

    def _pick_default(self):
        sel = getattr(self.viewport, "selected_name", None)
        b = self._by_name.get(sel) if sel else None
        if b is not None and E.is_exoplanet(b):
            return b
        for nm in DEFAULT_CANDIDATES:
            if nm in self._by_name:
                return self._by_name[nm]
        return next((b for b in self.bodies if E.is_exoplanet(b)), None)

    # ---------- 外部入口 ----------
    def set_body(self, body):
        """由主窗口（视口选中 / 天体树 / 详情面板）设置当前天体"""
        if body is None or not hasattr(body, "name"):
            return
        if self._body is body:
            return
        self._body = body
        idx = self.cmb_body.findText(body.name, Qt.MatchFixedString)
        if idx >= 0:
            self.cmb_body.blockSignals(True)
            self.cmb_body.setCurrentIndex(idx)
            self.cmb_body.blockSignals(False)
        else:
            self.cmb_body.setEditText(body.name)
        self._sync_chart_availability()
        if self.isVisible():
            self._redraw()
        else:
            self._dirty = True

    def _on_body_pick(self):
        nm = resolve_combo_text(self.cmb_body)
        b = self._by_name.get(nm)
        if b is None:
            return
        self._body = b
        if self.cmb_body.currentText().strip() != nm:
            self.cmb_body.setEditText(nm)
        self._sync_chart_availability()
        self._redraw()

    def _sync_chart_availability(self):
        """太阳系天体无凌星/视向速度特征，禁用对应图表项并切到宜居带"""
        exo = E.is_exoplanet(self._body) if self._body else False
        model = self.cmb_chart.model()
        for i in range(self.cmb_chart.count()):
            key = self.cmb_chart.itemData(i)
            item = model.item(i)
            if item is not None:
                item.setEnabled(exo or key == CHART_HZ)
        if not exo and self.cmb_chart.currentData() != CHART_HZ:
            self.cmb_chart.setCurrentIndex(
                self.cmb_chart.findData(CHART_HZ))
        self.row_b.setVisible(self.cmb_chart.currentData() == CHART_TRANSIT
                              and exo)

    def _on_b_changed(self, v):
        self.lbl_b.setText(f"撞击参数 b = {v / 100.0:.2f}")
        if self.cmb_chart.currentData() == CHART_TRANSIT:
            self._redraw()

    # ---------- 绘制 ----------
    def _redraw(self):
        self._dirty = False
        if self._body is None:
            return
        self._sync_chart_availability()
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        self._style_ax(ax)
        kind = self.cmb_chart.currentData()
        try:
            if kind == CHART_TRANSIT:
                self._plot_transit(ax)
            elif kind == CHART_RV:
                self._plot_rv(ax)
            else:
                self._plot_hz(ax)
        except Exception as ex:                    # 数据异常 → 提示，不崩溃
            ax.clear()
            self._style_ax(ax)
            ax.text(0.5, 0.5, f"绘图失败：{ex}", ha="center", va="center",
                    color="#d08a5a", transform=ax.transAxes)
        self.fig.tight_layout(pad=0.8)
        self.canvas.draw_idle()
        self._fill_table()

    def _style_ax(self, ax):
        ax.set_facecolor(MPL_AX)
        for s in ax.spines.values():
            s.set_color(MPL_GRID)
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.grid(True, color=MPL_GRID, lw=0.5, alpha=0.6)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.title.set_color(TEXT_MAIN)
        ax.title.set_fontsize(10)

    def _no_data(self, ax, msg):
        ax.text(0.5, 0.5, msg, ha="center", va="center", wrap=True,
                color="#d08a5a", fontsize=9, transform=ax.transAxes)

    # ---- 凌星光变 ----
    def _plot_transit(self, ax):
        body = self._body
        b = self.slider_b.value() / 100.0
        t, flux, info = E.transit_light_curve(body, b=b)
        if t is None:
            ax.set_title(f"{body.name} —— 凌星光变曲线")
            self._no_data(ax, "缺行星半径 / 恒星半径 / 周期，无法给出光变曲线")
            return
        # 不确定性包络：撞击参数 b 在 [0, 1] 内的全部可能形态
        b_hi = min(1.0, info["b_max"])
        grid = np.linspace(-info["span_days"] / 2.0, info["span_days"] / 2.0, 260)
        curves = [E.transit_flux_on_grid(body, grid, bb)
                  for bb in np.linspace(0.0, b_hi, 9)]
        curves = [c for c in curves if c is not None]
        if curves:
            stack = (np.vstack(curves) - 1.0) * 1e6
            ax.fill_between(grid * 24.0, stack.min(axis=0), stack.max(axis=0),
                            color="#4772b3", alpha=0.22, lw=0,
                            label="撞击参数 b∈[0,1] 的可能范围")
        ax.plot(t * 24.0, (flux - 1.0) * 1e6, color="#e8b04b", lw=1.8,
                label=f"b = {b:.2f}（当前假设）")
        for s in (-1.0, 1.0):
            ax.axvline(s * info["t14_hours"] / 2.0, color="#8a8a8a",
                       lw=0.7, ls="--")
        ax.axhline(0.0, color="#8a8a8a", lw=0.7)
        ax.set_xlabel("距凌星中点的时间（小时）")
        ax.set_ylabel("相对亮度偏差（ppm）")
        ax.set_title(f"{body.name} —— 凌星光变曲线")
        ax.legend(facecolor=MPL_BG, edgecolor=MPL_GRID, labelcolor=TEXT_DIM,
                  fontsize=7, loc="lower right")
        ax.annotate(f"深度 {info['depth_ppm']:,.0f} ppm\n"
                    f"T14 ≈ {info['t14_hours']:.2f} h（当前 b）",
                    xy=(0.03, 0.06), xycoords="axes fraction",
                    color=TEXT_DIM, fontsize=8)

    # ---- 视向速度 ----
    def _plot_rv(self, ax):
        body = self._body
        t, rv, info = E.rv_curve(body)
        if t is None:
            ax.set_title(f"{body.name} —— 视向速度曲线")
            self._no_data(ax, "缺行星质量或公转周期，无法给出视向速度")
            return
        P = body.period
        phase = t / P
        # 不确定性族：近心点幅角 ω 未收录，给出四种取向的形态
        for w in (90.0, 180.0, 270.0):
            _, rvw, _ = E.rv_curve(body, omega_deg=w)
            if rvw is not None:
                ax.plot(phase, rvw, color="#4772b3", lw=0.8, alpha=0.55)
        ax.plot(phase, rv, color="#e8b04b", lw=1.8, label="ω = 0°（当前假设）")
        ax.axhline(0.0, color="#8a8a8a", lw=0.7)
        ax.set_xlim(0.0, 1.0)
        ax.set_xlabel("轨道相位")
        ax.set_ylabel("视向速度（m/s）")
        ax.set_title(f"{body.name} —— 视向速度曲线（P = {P:.4g} 天）")
        ax.legend(facecolor=MPL_BG, edgecolor=MPL_GRID, labelcolor=TEXT_DIM,
                  fontsize=7, loc="lower right")
        ax.annotate(f"半振幅 K = {info['K']:.2f} m/s\n"
                    f"e = {info['e']:.3g}（ω 未收录，蓝线为其它取向）",
                    xy=(0.03, 0.90), xycoords="axes fraction",
                    va="top", color=TEXT_DIM, fontsize=8)

    # ---- 宜居带 ----
    def _plot_hz(self, ax):
        body = self._body
        bands = E.habitable_zone_bands(body)
        a = getattr(body, "a_au", None)
        if not bands or not a:
            ax.set_title(f"{body.name} —— 宜居带")
            self._no_data(ax, "缺恒星光度/有效温度或行星半长轴，无法给出宜居带")
            return
        ci, co, oi, oo = bands
        lo = max(1e-3, min(oi, a) * 0.5)
        hi = max(oo, a) * 1.6
        ax.set_xscale("log")
        ax.set_xlim(lo, hi)
        ax.axvspan(oi, oo, color="#4772b3", alpha=0.16, lw=0,
                   label="乐观宜居带（近期金星 ~ 早期火星）")
        ax.axvspan(ci, co, color="#4e9a51", alpha=0.30, lw=0,
                   label="保守宜居带（失控温室 ~ 最大温室）")
        # 本恒星系各行星位置
        host = body.host or "太阳"
        sibs = [b for b in self.bodies
                if (b.host or "太阳") == host and b.a_au
                and b.body_type in ("planet_solar", "dwarf", "planet_exo")]
        crowded = len(sibs) > 6
        for i, s in enumerate(sibs):
            ax.plot([s.a_au], [0.0], marker="o", ms=4.5,
                    color="#e8b04b" if s is body else "#9a9a9a",
                    mec="#1d1d1d", mew=0.5, zorder=3)
            if s is body or len(sibs) <= 12:
                ax.annotate(_short_label(s.name, host), (s.a_au, 0.0),
                            textcoords="offset points",
                            xytext=(0, 8 if s is body else (-13 if i % 2 else 8)),
                            ha="center", fontsize=7,
                            rotation=30 if crowded else 0,
                            color="#e8b04b" if s is body else TEXT_DIM)
        ax.plot([a], [0.0], marker="v", ms=7, color="#ffffff", zorder=4)
        ax.set_ylim(-0.6, 0.9)
        ax.set_yticks([])
        ax.set_xlabel("轨道半长轴（AU，对数刻度）")
        ax.set_title(f"{body.name} —— 宜居带（{host}）")
        ax.xaxis.set_major_locator(mticker.LogLocator(base=10.0, subs=(1, 2, 3, 5, 7)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(_plain_num))
        ax.xaxis.set_minor_formatter(mticker.NullFormatter())
        ax.legend(facecolor=MPL_BG, edgecolor=MPL_GRID, labelcolor=TEXT_DIM,
                  fontsize=7, loc="upper center", ncol=1)

    # ---------- 参数表 ----------
    def _fill_table(self):
        while self.tbl_grid.count():
            item = self.tbl_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if self._body is None:
            self.lbl_grade.setText("")
            return
        rows = E.observation_rows(self._body)
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            vl = QLabel(str(v))
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 11px;")
            self.tbl_grid.addWidget(kl, i, 0, Qt.AlignTop)
            self.tbl_grid.addWidget(vl, i, 1, Qt.AlignTop)
        self.tbl_grid.setColumnStretch(1, 1)
        b = self._body
        grade = getattr(b, "grade", "?")
        extra = "（轨道相位为可复现假设值）" if getattr(b, "assumed_phase", False) else ""
        self.lbl_grade.setText(f"精度等级 {grade}{extra}")

    # ---------- 导出 ----------
    def _export_png(self):
        if self._body is None:
            return
        default = f"{self._body.name}_{CHART_LABELS[self.cmb_chart.currentData()]}.png"
        path, _ = QFileDialog.getSaveFileName(self, "导出图表", default,
                                              "PNG 图片 (*.png)")
        if path:
            self.fig.savefig(path, dpi=160, facecolor=MPL_BG)