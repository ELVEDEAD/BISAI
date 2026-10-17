"""
compare_panel.py —— 双行星相对运动分析独立面板（模块 F）

内容（对应需求 6.2 / 6.3 节）：
- 相对运动轨迹曲线（3D 真实曲线 / 2D 俯视投影切换）
- 相对距离随时间变化曲线、相对速度随时间变化曲线
- 最近/最远/当前距离、会合周期、当前相对位置
- 参考系切换（行星A / 行星B / 质心 / 宿主恒星）
- 精度等级标注（科学诚实性，A/B/C + 说明文字）
- 导出 PNG / CSV
- 与主视口时间同步（游标移动）
"""
import math
import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QLineEdit,
                             QTabWidget, QFileDialog, QMessageBox)
from ui.mpl_backend import (FigureCanvasQTAgg, NavigationToolbar2QT,
                            Figure, mdates)
from datetime import datetime

from core.time_system import jd_to_datetime, datetime_to_jd
from core.constants import format_distance, AU_KM
from core.relative_motion import (compute_relative, REF_A, REF_B, REF_BARY,
                                  REF_STAR, REF_LABELS, classify_pair)
from ui.style import BG_MAIN, BG_PANEL, TEXT_MAIN, TEXT_DIM, ACCENT
from ui.widgets import make_searchable, resolve_combo_text
from ui.chart_fullscreen import ChartFullscreenDialog

MPL_BG = "#252526"
MPL_AX = "#2b2b2b"
MPL_GRID = "#404040"


class ComparePanel(QWidget):
    """双行星相对运动分析面板（与主视口时间同步）"""

    def __init__(self, clock, bodies, parent=None):
        super().__init__(parent)
        self.clock = clock
        self.bodies = bodies
        self._body_a = None
        self._body_b = None
        self._result = None
        self._cursor_line = None
        self._cursor_line2 = None

        self._build_ui()
        self._auto_done = False
        # 时间同步游标（轻量刷新，不重算）
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._sync_cursor)
        self._sync_timer.start(300)

    def showEvent(self, ev):
        """首次显示时自动算一次默认组合，避免打开即空白"""
        super().showEvent(ev)
        if not self._auto_done:
            self._auto_done = True
            QTimer.singleShot(0, self.recompute)

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 控制区（紧凑网格：窄栏下也放得下，避免最小宽度把分栏顶死）
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel("行星 A:"), 0, 0)
        self.combo_a = QComboBox()
        self.combo_a.setMinimumWidth(110)
        self.combo_a.addItems(self._body_names())
        make_searchable(self.combo_a, "搜索行星 A…")
        grid.addWidget(self.combo_a, 0, 1)
        grid.addWidget(QLabel("行星 B:"), 0, 2)
        self.combo_b = QComboBox()
        self.combo_b.setMinimumWidth(110)
        self.combo_b.addItems(self._body_names())
        self.combo_b.setCurrentIndex(1 if self.combo_b.count() > 1 else 0)
        make_searchable(self.combo_b, "搜索行星 B…")
        grid.addWidget(self.combo_b, 0, 3)
        # 输入框回车即计算（搜索框方式的快捷操作）
        for _c in (self.combo_a, self.combo_b):
            _c.lineEdit().returnPressed.connect(self.recompute)

        grid.addWidget(QLabel("参考系:"), 1, 0)
        self.combo_ref = QComboBox()
        for key in (REF_A, REF_B, REF_BARY, REF_STAR):
            self.combo_ref.addItem(REF_LABELS[key].format(a="行星A", b="行星B"), key)
        grid.addWidget(self.combo_ref, 1, 1, 1, 2)
        btn_calc = QPushButton("计算相对运动")
        btn_calc.clicked.connect(self.recompute)
        grid.addWidget(btn_calc, 1, 3)

        grid.addWidget(QLabel("起始:"), 2, 0)
        self.edit_start = QLineEdit(self._fmt_now())
        self.edit_start.setMaximumWidth(140)
        grid.addWidget(self.edit_start, 2, 1)
        grid.addWidget(QLabel("结束:"), 2, 2)
        self.edit_end = QLineEdit(self._fmt_now(365.25 * 2))
        self.edit_end.setMaximumWidth(140)
        grid.addWidget(self.edit_end, 2, 3)

        btn_quick = QPushButton("近 1 个会合周期")
        btn_quick.clicked.connect(self._quick_range_synodic)
        grid.addWidget(btn_quick, 3, 0, 1, 2)
        btn_10y = QPushButton("近 10 年")
        btn_10y.clicked.connect(lambda: self._quick_range(365.25 * 10))
        grid.addWidget(btn_10y, 3, 2)
        btn_2y = QPushButton("近 2 年")
        btn_2y.clicked.connect(lambda: self._quick_range(365.25 * 2))
        grid.addWidget(btn_2y, 3, 3)

        btn_2d = QPushButton("轨迹: 2D 俯视")
        btn_2d.setCheckable(True)
        btn_2d.toggled.connect(self._toggle_projection)
        self.btn_2d = btn_2d
        grid.addWidget(btn_2d, 4, 0, 1, 2)
        btn_export = QPushButton("导出 CSV")
        btn_export.clicked.connect(self._export_csv)
        grid.addWidget(btn_export, 4, 2)
        btn_png = QPushButton("导出图片")
        btn_png.clicked.connect(self._export_png)
        grid.addWidget(btn_png, 4, 3)

        layout.addLayout(grid)

        # 图表区（Tab：轨迹 / 距离曲线 / 速度曲线）
        self.tabs = QTabWidget()
        self.fig_track = Figure(facecolor=MPL_BG)
        self.canvas_track = FigureCanvasQTAgg(self.fig_track)
        self.tabs.addTab(self.canvas_track, "相对运动轨迹")
        self.fig_curves = Figure(facecolor=MPL_BG)
        self.canvas_curves = FigureCanvasQTAgg(self.fig_curves)
        self.tabs.addTab(self.canvas_curves, "距离 / 速度曲线")
        layout.addWidget(self.tabs, 1)

        # 全屏按钮行
        btn_row2 = QHBoxLayout()
        btn_row2.addStretch()
        self.btn_fullscreen_track = QPushButton("放大轨迹图")
        self.btn_fullscreen_track.setToolTip("全屏查看相对运动轨迹图（滚轮缩放、拖拽平移、Esc 退出）")
        self.btn_fullscreen_track.clicked.connect(lambda: self._fullscreen_chart("track"))
        btn_row2.addWidget(self.btn_fullscreen_track)
        self.btn_fullscreen_curves = QPushButton("放大曲线图")
        self.btn_fullscreen_curves.setToolTip("全屏查看距离/速度曲线（滚轮缩放、拖拽平移、Esc 退出）")
        self.btn_fullscreen_curves.clicked.connect(lambda: self._fullscreen_chart("curves"))
        btn_row2.addWidget(self.btn_fullscreen_curves)
        layout.addLayout(btn_row2)

        # 统计 + 精度标注
        info = QGridLayout()
        self.lbl_stats = QLabel("选择两颗行星后点击“计算相对运动”")
        self.lbl_stats.setStyleSheet(f"color: {TEXT_MAIN};")
        self.lbl_grade = QLabel("")
        self.lbl_grade.setWordWrap(True)
        info.addWidget(self.lbl_stats, 0, 0)
        info.addWidget(self.lbl_grade, 1, 0)
        layout.addLayout(info)

    def _body_names(self):
        names = [b.name for b in self.bodies if b.body_type != "star"]
        return names if names else ["（无行星数据）"]

    def _get_body(self, name):
        return next((b for b in self.bodies if b.name == name), None)

    def _fmt_now(self, offset_days: float = 0.0) -> str:
        dt = jd_to_datetime(self.clock.jd + offset_days)
        return dt.strftime("%Y-%m-%d")

    # ---------- 计算 ----------
    def recompute(self):
        name_a = resolve_combo_text(self.combo_a)
        name_b = resolve_combo_text(self.combo_b)
        # 归一化输入框显示（如输入 "地" 命中 "地球" 后回填完整名）
        for combo, nm in ((self.combo_a, name_a), (self.combo_b, name_b)):
            if nm and combo.currentText().strip() != nm:
                combo.setEditText(nm)
        a = self._get_body(name_a)
        b = self._get_body(name_b)
        if not a or not b or a is b:
            self.lbl_stats.setText("请选择两颗不同的行星（可在框中输入名称搜索）")
            return
        try:
            jd0 = datetime_to_jd(datetime.strptime(self.edit_start.text().strip(), "%Y-%m-%d"))
            jd1 = datetime_to_jd(datetime.strptime(self.edit_end.text().strip(), "%Y-%m-%d"))
            if jd1 <= jd0:
                raise ValueError
        except ValueError:
            self.lbl_stats.setText("日期格式无效（应为 YYYY-MM-DD）")
            return
        n = 360 if (jd1 - jd0) < 3650 else 500
        ref = self.combo_ref.currentData() or REF_A
        # 参考系标签动态化
        ref_label = REF_LABELS[ref].format(a=a.name, b=b.name)
        self._body_a, self._body_b = a, b
        try:
            self._result = compute_relative(a, b, ref, jd0, jd1, n)
        except Exception as e:
            self._result = None      # 失败时清空旧结果，避免误导
            self.lbl_stats.setText(f"计算失败: {e}")
            return
        self._ref_label = ref_label
        self._plot_track()
        self._plot_curves()
        self._update_stats()
        self._sync_cursor(force=True)

    def _quick_range_synodic(self):
        if self._body_a and self._body_b and self._result and \
                math.isfinite(self._result.synodic_days):
            span = max(self._result.synodic_days, 30.0)
        else:
            span = 730.5
        self._quick_range(span)

    def _quick_range(self, span_days: float):
        self.edit_start.setText(self._fmt_now())
        self.edit_end.setText(self._fmt_now(span_days))
        self.recompute()

    # ---------- 绘图 ----------
    def _apply_axis_style(self, ax, title=""):
        ax.set_facecolor(MPL_AX)
        ax.tick_params(colors=TEXT_DIM, labelsize=8)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.title.set_color(TEXT_MAIN)
        ax.grid(True, color=MPL_GRID, lw=0.4, alpha=0.6)
        for spine in ax.spines.values():
            spine.set_color(MPL_GRID)
        if title:
            ax.set_title(title, fontsize=10)

    def _toggle_projection(self, checked):
        self._plot_track()

    def _plot_track(self):
        r = self._result
        self.fig_track.clear()
        if r is None:
            self.canvas_track.draw_idle()
            return
        rel = np.asarray(r.rel_positions)   # (n,3) AU
        col_a = self._body_a.color
        col_b = self._body_b.color
        use_2d = bool(self.btn_2d.isChecked())
        if use_2d:
            ax = self.fig_track.add_subplot(111)
            ax.plot(rel[:, 0], rel[:, 1], color="#e8b04b", lw=1.4,
                    label=f"相对轨迹（{self._ref_label}）")
            ax.plot([rel[0, 0]], [rel[0, 1]], "o", color=col_a, ms=5, label=r.body_a)
            ax.plot([rel[-1, 0]], [rel[-1, 1]], "s", color=col_b, ms=5, label=r.body_b)
            ax.plot([0], [0], "x", color=TEXT_DIM, ms=6, label="原点")
            self._apply_axis_style(ax, f"{r.body_a} - {r.body_b} 相对运动轨迹（2D 俯视，X-Y 黄道面）")
            ax.set_xlabel("X (AU)")
            ax.set_ylabel("Y (AU)")
            ax.set_aspect("equal", adjustable="datalim")
        else:
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
            ax = self.fig_track.add_subplot(111, projection="3d")
            ax.plot(rel[:, 0], rel[:, 1], rel[:, 2], color="#e8b04b", lw=1.4,
                    label="相对轨迹")
            ax.scatter([rel[0, 0]], [rel[0, 1]], [rel[0, 2]], color=col_a, s=22,
                       label=r.body_a, depthshade=False)
            ax.scatter([rel[-1, 0]], [rel[-1, 1]], [rel[-1, 2]], color=col_b, s=22,
                       label=r.body_b, depthshade=False)
            ax.set_title(f"{r.body_a} - {r.body_b} 相对运动轨迹（3D，{self._ref_label}）",
                         fontsize=10, color=TEXT_MAIN)
            self._style_3d(ax, rel)
        leg = ax.legend(loc="upper right", fontsize=7, framealpha=0.3)
        for t in leg.get_texts():
            t.set_color(TEXT_MAIN)
        self.fig_track.tight_layout()
        self.canvas_track.draw_idle()

    def _style_3d(self, ax, rel):
        ax.set_facecolor(MPL_AX)
        ax.tick_params(colors=TEXT_DIM, labelsize=7)
        pane = (0.16, 0.16, 0.17, 1.0)
        try:
            ax.xaxis.set_pane_color(pane)
            ax.yaxis.set_pane_color(pane)
            ax.zaxis.set_pane_color(pane)
        except Exception:
            pass
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.label.set_color(TEXT_DIM)
        ax.set_xlabel("X (AU)", fontsize=8)
        ax.set_ylabel("Y (AU)", fontsize=8)
        ax.set_zlabel("Z (AU)", fontsize=8)
        lims = []
        for d in range(3):
            lo, hi = float(rel[:, d].min()), float(rel[:, d].max())
            if hi - lo < 1e-9:
                lo, hi = lo - 1, hi + 1
            lims.append((lo, hi))
        max_span = max(hi - lo for lo, hi in lims)
        ctr = [(lo + hi) / 2 for lo, hi in lims]
        try:
            ax.set_box_aspect((1, 1, 1))
        except Exception:
            pass
        for d, axis in enumerate((ax.set_xlim, ax.set_ylim, ax.set_zlim)):
            half = max_span / 2
            axis(ctr[d] - half, ctr[d] + half)

    def _plot_curves(self):
        r = self._result
        self.fig_curves.clear()
        if r is None:
            self.canvas_curves.draw_idle()
            return
        t = np.asarray([jd_to_datetime(jd) for jd in r.times_jd])
        d = np.asarray(r.distances)
        m0 = mdates.date2num(jd_to_datetime(r.times_jd[0]))
        m1 = mdates.date2num(jd_to_datetime(r.times_jd[-1]))
        ax1 = self.fig_curves.add_subplot(211)
        ax1.plot(t, d, color="#4fa3d1", lw=1.2, label="相对距离 (AU)")
        self._apply_axis_style(ax1, "相对距离随时间变化")
        ax1.set_ylabel("距离 (AU)", fontsize=8)
        # 游标线初值取数据起点，避免 axvline(0) 把日期轴拉到 1970 年
        self._cursor_line = ax1.axvline(m0, color=ACCENT, lw=0.8, ls="--", alpha=0.9)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax1.set_xlim(m0, m1)


        ax2 = self.fig_curves.add_subplot(212, sharex=ax1)
        if r.has_velocity:
            s = np.asarray(r.speeds)
            ax2.plot(t, s, color="#e8b04b", lw=1.2, label="相对速度 (km/s)")
        else:
            ax2.text(0.5, 0.5, "相对速度数据不可用（缺失质量/速度数据）",
                     ha="center", va="center", transform=ax2.transAxes,
                     color=TEXT_DIM, fontsize=9)
        self._apply_axis_style(ax2, "相对速度随时间变化")
        ax2.set_ylabel("速度 (km/s)", fontsize=8)
        ax2.set_xlabel("日期", fontsize=8)
        self._cursor_line2 = ax2.axvline(m0, color=ACCENT, lw=0.8, ls="--", alpha=0.9)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        self.fig_curves.tight_layout()
        self.canvas_curves.draw_idle()

    def _update_stats(self):
        r = self._result
        if r is None:
            return
        syn_txt = f"{r.synodic_days:.1f} 天" if math.isfinite(r.synodic_days) else "不适用（不同恒星系统）"
        stats = (
            f"{r.body_a}  ×  {r.body_b}\n"
            f"当前距离: {format_distance(r.current_distance)}   "
            f"最近: {format_distance(r.min_distance)}   "
            f"最远: {format_distance(r.max_distance)}\n"
            f"会合周期: {syn_txt}   采样: {r.n_samples} 点 / "
            f"{(r.jd_end - r.jd_start):.1f} 天"
        )
        self.lbl_stats.setText(stats)
        self.lbl_grade.setText(f"数据精度: {r.grade_note}")

    # ---------- 全屏 ----------
    def _fullscreen_chart(self, which):
        fig = self.fig_track if which == "track" else self.fig_curves
        title = "相对运动轨迹（全屏）" if which == "track" else "距离 / 速度曲线（全屏）"
        dlg = ChartFullscreenDialog(fig, parent=self, title=title)
        # 全屏期间保持时间游标同步
        if dlg.exec_() == dlg.Accepted:
            pass
        # 关闭后刷新原图（matplotlib figure 被全屏 canvas 重绘过）
        self.canvas_track.draw_idle()
        self.canvas_curves.draw_idle()

    # ---------- 时间同步 ----------
    def _sync_cursor(self, force=False):
        r = self._result
        if r is None:
            return
        jd = self.clock.jd
        if jd < r.jd_start or jd > r.jd_end:
            return
        dt = jd_to_datetime(jd)
        m = mdates.date2num(dt)
        try:
            if self._cursor_line is not None:
                self._cursor_line.set_xdata([m, m])
            if self._cursor_line2 is not None:
                self._cursor_line2.set_xdata([m, m])
            self.canvas_curves.draw_idle()
        except Exception:
            pass

    # ---------- 导出 ----------
    def _export_csv(self):
        r = self._result
        if r is None:
            QMessageBox.information(self, "提示", "请先计算相对运动")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出相对运动数据", f"{r.body_a}_{r.body_b}_相对运动.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["说明", f"{r.body_a} - {r.body_b} 相对运动（{self._ref_label}）"])
                w.writerow(["精度等级", r.grade, r.grade_note])
                w.writerow(["会合周期(天)", r.synodic_days if math.isfinite(r.synodic_days) else "不适用"])
                w.writerow([])
                w.writerow(["日期", "JD", "相对X(AU)", "相对Y(AU)", "相对Z(AU)",
                            "距离(AU)", "速度(km/s)"])
                for i, jd in enumerate(r.times_jd):
                    sp = r.speeds[i] if r.speeds is not None and math.isfinite(r.speeds[i]) else ""
                    w.writerow([
                        jd_to_datetime(jd).strftime("%Y-%m-%d %H:%M"),
                        f"{jd:.4f}",
                        f"{r.rel_positions[i][0]:.6g}",
                        f"{r.rel_positions[i][1]:.6g}",
                        f"{r.rel_positions[i][2]:.6g}",
                        f"{r.distances[i]:.6g}",
                        sp,
                    ])
            QMessageBox.information(self, "完成", f"已导出 {r.n_samples} 行数据到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _export_png(self):
        if self._result is None:
            QMessageBox.information(self, "提示", "请先计算相对运动")
            return
        idx = self.tabs.currentIndex()
        fig = self.fig_track if idx == 0 else self.fig_curves
        path, _ = QFileDialog.getSaveFileName(
            self, "导出图片", "相对运动分析.png", "PNG (*.png)")
        if not path:
            return
        try:
            fig.savefig(path, dpi=150, facecolor=MPL_BG)
            QMessageBox.information(self, "完成", f"已导出到 {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ---------- 外部调用 ----------
    def set_pair(self, name_a: str, name_b: str):
        """由主窗口/右键菜单设置对比组合并计算"""
        ia = self.combo_a.findText(name_a)
        ib = self.combo_b.findText(name_b)
        if ia >= 0:
            self.combo_a.setCurrentIndex(ia)
        if ib >= 0:
            self.combo_b.setCurrentIndex(ib)
        self.recompute()