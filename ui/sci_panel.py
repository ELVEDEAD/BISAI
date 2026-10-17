"""
sci_panel.py —— 科研计算面板（右侧功能栏）

把 core 新增的四个科研计算模块暴露为可操作界面：
    1) FITS 数据处理：读取 .fits/.fits.gz → 图像显示 / 孔径测光 / 宇宙线剔除，
       或光谱表 → Savitzky-Golay 去噪 / 连续谱归一化
    2) 视向速度轨道反演：粘贴或载入 (t, RV[, σ]) 数据 → χ² 周期图 →
       开普勒轨道拟合 (K, P, e, ω, T₀, γ) 与相位折叠图
    3) 凌星星历：凌星中点时刻序列 → (T₀, P) 线性拟合 + O−C 图（TTV 分析入口）
    4) 恒星与大气：主序质量→光度/半径/寿命/谱型，行星平衡温度、大气标高、
       临边昏暗凌星光变、黑体光谱

科学诚实性约定（与 core 模块一致）：
    * 「演示数据」为固定种子的注入模拟（信号 + 高斯噪声），仅用于流程演示，
      图题明确标注「模拟」，不与真实观测混淆
    * 拟合输出附带 1σ 高斯近似误差与 χ²ᵣ；点数不足时提示而非伪造结果
"""
import os

import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QComboBox, QLabel, QPushButton, QCheckBox,
                             QDoubleSpinBox, QTabWidget, QTextEdit,
                             QFileDialog, QFrame, QScrollArea)

from ui.mpl_backend import FigureCanvasQTAgg, Figure, Circle

from core import fits_io
from core import photometry as P
from core import orbit_fit as F
from core import stellar_model as S
from ui import style
from ui.style import TEXT_MAIN, TEXT_DIM, ACCENT

MPL_BG = "#252526"
MPL_AX = "#2b2b2b"
MPL_GRID = "#404040"
MPL_NOTE = "#d08a5a"


def _parse_rows(text, min_cols=2, max_cols=3):
    """文本框 → 数值行数组（支持空格/逗号/制表符分隔，# 为注释）。"""
    rows = []
    for ln in str(text).splitlines():
        parts = ln.replace(",", " ").replace("\t", " ").split()
        if not parts or parts[0].startswith("#"):
            continue
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) >= min_cols:
            rows.append(vals[:max_cols])
    if not rows:
        return None
    return np.array(rows, dtype=np.float64)


class SciPanel(QWidget):
    """科研计算面板：FITS 数据处理 / RV 轨道反演 / 凌星星历 / 恒星与大气模型"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        # FITS 页状态
        self._path = None
        self._hdus = []
        self._img = None          # 当前图像（剔除宇宙线后）
        self._img_raw = None
        self._phot_xy = None
        self._phot_circle = None
        self._spec = None         # (wave, flux)
        self._build_ui()

    # ================================================================ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        head = QLabel("科研计算")
        head.setStyleSheet(
            f"color: {TEXT_MAIN}; font-size: {style.fs(15)}px; font-weight: bold;")
        layout.addWidget(head)
        sub = QLabel("FITS 数据处理 · 视向速度 / 凌星轨道反演 · 恒星与大气建模")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
        layout.addWidget(sub)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_fits_page(), "FITS 数据")
        self.tabs.addTab(self._build_rv_page(), "RV 拟合")
        self.tabs.addTab(self._build_ephemeris_page(), "凌星星历")
        self.tabs.addTab(self._build_stellar_page(), "恒星与大气")
        layout.addWidget(self.tabs, 1)

    # ---------- 通用小部件 ----------
    @staticmethod
    def _spin(default, lo, hi, dec=3, step=1.0, tip=None, suffix=""):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setSingleStep(step)
        sp.setValue(default)
        if suffix:
            sp.setSuffix(f" {suffix}")
        if tip:
            sp.setToolTip(tip)
        return sp

    @staticmethod
    def _label(text, dim=False, wrap=True):
        lbl = QLabel(text)
        lbl.setWordWrap(wrap)
        lbl.setStyleSheet(
            f"color: {TEXT_DIM if dim else TEXT_MAIN}; "
            f"font-size: {style.fs(11 if dim else 12)}px;")
        return lbl

    @staticmethod
    def _make_canvas(figsize=(4.2, 2.6)):
        fig = Figure(figsize=figsize, dpi=100, facecolor=MPL_BG)
        canvas = FigureCanvasQTAgg(fig)
        canvas.setMinimumHeight(190)
        return fig, canvas

    @staticmethod
    def _style_ax(ax):
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
                color=MPL_NOTE, fontsize=9, transform=ax.transAxes)

    # ================================================= FITS 数据页
    def _build_fits_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        row = QHBoxLayout()
        btn_open = QPushButton("打开 FITS …")
        btn_open.clicked.connect(self._open_fits)
        row.addWidget(btn_open)
        self.cmb_hdu = QComboBox()
        self.cmb_hdu.setEnabled(False)
        self.cmb_hdu.currentIndexChanged.connect(self._on_hdu_changed)
        row.addWidget(self.cmb_hdu, 1)
        v.addLayout(row)

        self.lbl_fits = self._label("支持 .fits / .fits.gz（纯内置解析器，无需 astropy）", dim=True)
        v.addWidget(self.lbl_fits)

        self.fig_fits, self.canvas_fits = self._make_canvas()
        v.addWidget(self.canvas_fits, 1)
        self.canvas_fits.mpl_connect("button_press_event", self._on_img_click)

        # 图像模式行
        self.row_img = QWidget()
        r = QHBoxLayout(self.row_img)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(6)
        self.sp_radius = self._spin(6.0, 1.0, 200.0, dec=1, suffix="px",
                                    tip="孔径测光的圆孔半径（像素）")
        self.sp_radius.valueChanged.connect(self._do_photometry)
        r.addWidget(QLabel("孔径半径:"))
        r.addWidget(self.sp_radius)
        self.chk_cr = QCheckBox("剔除宇宙线")
        self.chk_cr.toggled.connect(self._on_cr_toggled)
        r.addWidget(self.chk_cr)
        r.addStretch(1)
        v.addWidget(self.row_img)

        # 光谱模式行
        self.row_spec = QWidget()
        r2 = QHBoxLayout(self.row_spec)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(6)
        self.chk_smooth = QCheckBox("SavGol 平滑")
        self.chk_smooth.setChecked(True)
        self.chk_smooth.toggled.connect(self._show_spectrum)
        self.chk_norm = QCheckBox("连续谱归一化")
        self.chk_norm.toggled.connect(self._show_spectrum)
        r2.addWidget(self.chk_smooth)
        r2.addWidget(self.chk_norm)
        r2.addStretch(1)
        v.addWidget(self.row_spec)
        self.row_spec.hide()

        self.lbl_fits_result = self._label("点击「打开 FITS」载入观测数据；图像可点击选测光中心。")
        v.addWidget(self.lbl_fits_result)
        return page

    # ---------- FITS 逻辑 ----------
    def _open_fits(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 FITS 文件", "", "FITS 文件 (*.fits *.fit *.fts *.gz);;所有文件 (*)")
        if not path:
            return
        try:
            self._hdus = fits_io.read_fits(path)
        except Exception as ex:
            self._hdus = []
            self.lbl_fits.setText(f"读取失败：{ex}")
            self.lbl_fits.setWordWrap(True)
            return
        self._path = path
        self.cmb_hdu.blockSignals(True)
        self.cmb_hdu.clear()
        for i, hdu in enumerate(self._hdus):
            shape = getattr(hdu.data, "shape", None)
            kind = str(hdu.header.get("XTENSION", "IMAGE")).strip()
            self.cmb_hdu.addItem(f"#{i} {hdu.name} ({kind}"
                                 f"{f' {shape}' if shape else ''})")
        self.cmb_hdu.blockSignals(False)
        self.cmb_hdu.setEnabled(bool(self._hdus))
        # 自动选中第一个有数据的 HDU（跳过空主 HDU，直接看到内容）
        for i, hdu in enumerate(self._hdus):
            has_data = (getattr(hdu.data, "size", 0) or 0) > 0 or bool(hdu.columns)
            if has_data:
                if self.cmb_hdu.currentIndex() != i:
                    self.cmb_hdu.setCurrentIndex(i)
                else:
                    self._on_hdu_changed()
                break
        else:
            self._on_hdu_changed()

    def _on_hdu_changed(self, *_):
        idx = self.cmb_hdu.currentIndex()
        if not self._hdus or not (0 <= idx < len(self._hdus)):
            return
        hdu = self._hdus[idx]
        self._img = self._img_raw = None
        self._phot_xy = None
        self._phot_circle = None
        self._spec = None
        self.row_img.hide()
        self.row_spec.hide()
        self.lbl_fits_result.setText("")

        data = hdu.data
        if data is not None and getattr(data, "ndim", 0) == 2 \
                and np.issubdtype(np.asarray(data).dtype, np.number):
            self._img_raw = np.asarray(data, dtype=np.float64)
            self._img = self._img_raw.copy()
            self.chk_cr.blockSignals(True)
            self.chk_cr.setChecked(False)
            self.chk_cr.blockSignals(False)
            self.row_img.show()
            self._show_image()
        elif hdu.columns:
            self._spec = self._pick_spectrum_columns(hdu.columns)
            if self._spec is not None:
                self.row_spec.show()
                self._show_spectrum()
            else:
                self._spec = None
                self._fig_message(self.fig_fits, "表扩展中未找到可用的「波长 + 流量」数值列")
                self.lbl_fits_result.setText(
                    f"列：{', '.join(list(hdu.columns)[:10])}")
        else:
            self._fig_message(self.fig_fits, "该 HDU 无可显示数据（空主 HDU？试试选扩展）")

    @staticmethod
    def _pick_spectrum_columns(columns):
        """从表列中启发式识别 (波长, 流量) 数值列对。"""
        numeric = []
        for name, col in columns.items():
            arr = np.asarray(col)
            if arr.ndim == 1 and arr.size >= 8 \
                    and np.issubdtype(arr.dtype, np.number):
                numeric.append((str(name), arr.astype(np.float64)))
        if not numeric:
            return None
        wave = flux = None
        for name, arr in numeric:
            ln = name.lower()
            if wave is None and ("wave" in ln or "lam" in ln):
                wave = (name, arr)
            elif flux is None and "flux" in ln:
                flux = (name, arr)
        if wave is None or flux is None:
            if len(numeric) >= 2:
                wave, flux = numeric[0], numeric[1]
            else:
                return None
        w, f = wave[1], flux[1]
        if w.size != f.size:
            return None
        good = np.isfinite(w) & np.isfinite(f)
        if good.sum() < 8:
            return None
        order = np.argsort(w[good])
        return w[good][order], f[good][order]

    def _fig_message(self, fig, msg):
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        self._no_data(ax, msg)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()

    def _show_image(self):
        if self._img is None:
            return
        fig = self.fig_fits
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        ax.grid(False)
        img = self._img
        finite = img[np.isfinite(img)]
        if finite.size == 0:
            self._no_data(ax, "图像无有效像素")
            fig.canvas.draw_idle()
            return
        lo, hi = np.percentile(finite, [0.5, 99.5])
        if not np.isfinite(lo + hi) or hi <= lo:
            hi = lo + 1.0
        im = ax.imshow(img, origin="lower", cmap="gray", vmin=lo, vmax=hi,
                       interpolation="nearest", aspect="equal")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.ax.tick_params(colors=TEXT_DIM, labelsize=7)
        cb.outline.set_edgecolor(MPL_GRID)
        ax.set_title(os.path.basename(str(self._path or "")) + " — 图像")
        ax.set_xlabel("x (pix)")
        ax.set_ylabel("y (pix)")
        # fig.clear() 已带走旧圆圈引用，此处直接重画（若有测光中心）
        self._phot_circle = None
        self._draw_phot_circle(ax)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()

    def _draw_phot_circle(self, ax):
        if self._phot_xy is None:
            return
        x, y = self._phot_xy
        r = self.sp_radius.value()
        self._phot_circle = Circle((x, y), r, fill=False,
                                   color="#e6913f", lw=1.2)
        ax.add_patch(self._phot_circle)

    def _on_img_click(self, ev):
        if self._img is None or ev.inaxes is None or ev.xdata is None:
            return
        self._phot_xy = (float(ev.xdata), float(ev.ydata))
        self._show_image()
        self._do_photometry()

    def _do_photometry(self, *_):
        if self._img is None or self._phot_xy is None:
            return
        x, y = self._phot_xy
        r = self.sp_radius.value()
        try:
            res = P.aperture_photometry(self._img, x, y, r, gain=1.0)
        except Exception as ex:
            self.lbl_fits_result.setText(f"测光失败：{ex}")
            return
        self.lbl_fits_result.setText(
            f"孔径测光 @({x:.1f}, {y:.1f}) r={r:.1f}px —— "
            f"流量 {res['flux']:.1f} ADU，"
            f"仪器星等 {res['mag']:.3f} ± {res['mag_err']:.3f}，"
            f"SNR {res['snr']:.1f}，天背景 {res['sky_per_pix']:.2f} ADU/px")

    def _on_cr_toggled(self, on):
        if self._img_raw is None:
            return
        if on:
            try:
                self._img, _ = P.remove_cosmic_rays(self._img_raw, sigma=6.0)
            except Exception as ex:
                self.lbl_fits_result.setText(f"宇宙线剔除失败：{ex}")
                self._img = self._img_raw
        else:
            self._img = self._img_raw
        self._show_image()
        self._do_photometry()

    def _show_spectrum(self, *_):
        if self._spec is None:
            return
        wave, flux = self._spec
        fig = self.fig_fits
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        y = flux
        ylabel = "流量"
        if self.chk_norm.isChecked():
            y, _ = P.normalize_spectrum(wave, flux)
            ylabel = "归一化流量"
            ax.axhline(1.0, color=MPL_GRID, lw=0.8, ls="--")
        if self.chk_smooth.isChecked():
            n = y.size
            if n >= 5:
                win = min(21, n if n % 2 == 1 else n - 1)
                ax.plot(wave, y, color="#5a83c4", lw=0.5, alpha=0.35, label="原始")
                ax.plot(wave, P.savgol_smooth(y, window=win), color="#e6913f",
                        lw=1.2, label="SavGol 平滑")
                ax.legend(fontsize=7, labelcolor=TEXT_DIM, frameon=False)
            else:
                ax.plot(wave, y, color="#5a83c4", lw=0.7)
        else:
            ax.plot(wave, y, color="#5a83c4", lw=0.7)
        ax.set_title("光谱（表扩展）")
        ax.set_xlabel("波长")
        ax.set_ylabel(ylabel)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()

    # ================================================= RV 拟合页
    def _build_rv_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        self.txt_rv = QTextEdit()
        self.txt_rv.setPlaceholderText(
            "每行一条观测：时间(天/BJD)  RV(m/s)  [σ(m/s)]\n"
            "支持空格 / 逗号 / 制表符分隔，# 开头为注释")
        self.txt_rv.setMaximumHeight(96)
        v.addWidget(self.txt_rv)

        row = QHBoxLayout()
        b1 = QPushButton("演示数据")
        b1.setToolTip("注入模拟信号 K=12.5 m/s、P=17.4 d、e=0.25 + 0.15 m/s 高斯噪声（固定种子）")
        b1.clicked.connect(self._demo_rv)
        b2 = QPushButton("载入 CSV …")
        b2.clicked.connect(self._load_rv_csv)
        b3 = QPushButton("周期图")
        b3.clicked.connect(self._run_periodogram)
        b4 = QPushButton("拟合开普勒轨道")
        b4.setObjectName("accentBtn")
        b4.clicked.connect(self._fit_rv)
        for b in (b1, b2, b3, b4):
            row.addWidget(b)
        v.addLayout(row)

        self.fig_rv, self.canvas_rv = self._make_canvas()
        v.addWidget(self.canvas_rv, 1)
        self._fig_message(self.fig_rv, "载入或粘贴 RV 数据后运行周期图 / 拟合")

        self.lbl_rv_result = self._label("结果将显示在这里（参数 ± 1σ，χ²ᵣ）")
        v.addWidget(self.lbl_rv_result)
        return page

    def _demo_rv(self):
        rng = np.random.default_rng(42)
        truth = (12.5, 17.4, 0.25, 55.0, 2450000.5, 3.2)
        t = np.sort(rng.uniform(2450000.0, 2450120.0, 60))
        rv = F.rv_model(truth, t) + rng.normal(0.0, 0.15, t.size)
        lines = [f"{ti:.4f}  {yi:.3f}  0.150" for ti, yi in zip(t, rv)]
        self.txt_rv.setPlainText(
            "# 模拟演示数据（注入开普勒信号 + 高斯噪声，seed=42）\n" + "\n".join(lines))
        self.lbl_rv_result.setText("已装入模拟演示数据（非真实观测，仅演示流程）")

    def _load_rv_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "载入 RV 数据", "", "数据文件 (*.csv *.txt *.dat);;所有文件 (*)")
        if not path:
            return
        data = None
        for kwargs in ({"delimiter": ","}, {}):
            try:
                data = np.loadtxt(path, comments="#", **kwargs)
                break
            except Exception:
                continue
        if data is None or data.ndim < 2:
            self.lbl_rv_result.setText("载入失败：无法解析为数值表格（每行：时间 RV [σ]）")
            return
        self.txt_rv.setPlainText("\n".join(
            "  ".join(f"{v:.6g}" for v in row) for row in data))

    def _run_periodogram(self):
        rows = _parse_rows(self.txt_rv.toPlainText(), min_cols=2)
        if rows is None or rows.shape[0] < 8:
            self._fig_message(self.fig_rv, "数据不足（至少 8 条「时间 RV」观测）")
            return
        t, y = rows[:, 0], rows[:, 1]
        err = rows[:, 2] if rows.shape[1] > 2 else None
        periods, chi2, best = F.rv_periodogram(t, y, err, n_freq=6000)
        if periods is None:
            self._fig_message(self.fig_rv, "周期图计算失败（基线或采样异常）")
            return
        fig = self.fig_rv
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        ax.plot(periods, chi2, color="#5a83c4", lw=0.8)
        ax.axvline(best, color="#e6913f", lw=1.0, ls="--")
        ax.set_title("RV 周期图（χ²，floating-mean）")
        ax.set_xlabel("周期 (天)")
        ax.set_ylabel("χ²")
        ax.set_xscale("log")
        ax.annotate(f"P = {best:.4f} d", xy=(best, chi2.min()),
                    xytext=(8, 4), textcoords="offset points",
                    color="#e6913f", fontsize=9)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()
        self.lbl_rv_result.setText(f"周期图最优候选周期 P ≈ {best:.4f} 天（χ² 最低点）")

    def _fit_rv(self):
        rows = _parse_rows(self.txt_rv.toPlainText(), min_cols=2)
        if rows is None or rows.shape[0] < 8:
            self._fig_message(self.fig_rv, "数据不足（至少 8 条「时间 RV」观测）")
            return
        t, y = rows[:, 0], rows[:, 1]
        err = rows[:, 2] if rows.shape[1] > 2 else None
        out = F.fit_rv_kepler(t, y, err)
        if out is None:
            self._fig_message(self.fig_rv, "拟合失败：点数不足或不收敛（需 ≥ 8 点）")
            return
        K, Pp, e, w, T0, gamma = out["params"]
        ek = out["errors"]

        fig = self.fig_rv
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        # 相位折叠 + 模型曲线
        phase = ((t - T0) / Pp + 0.5) % 1.0 - 0.5
        if err is not None:
            ax.errorbar(phase, y, yerr=err, fmt="o", ms=3, lw=0.7,
                        color="#dfe0e2", ecolor="#95999e", capsize=0,
                        label="观测（相位折叠）")
        else:
            ax.plot(phase, y, "o", ms=3, color="#dfe0e2", label="观测（相位折叠）")
        pg = ((out["model_t"] - T0) / Pp + 0.5) % 1.0 - 0.5
        order = np.argsort(pg)
        ax.plot(pg[order], out["model_rv"][order], color="#e6913f", lw=1.3,
                label="开普勒模型")
        ax.set_title(f"RV 轨道拟合（模拟）" if "模拟" in self.txt_rv.toPlainText()[:40]
                     else "RV 轨道拟合")
        ax.set_xlabel("轨道相位")
        ax.set_ylabel("RV (m/s)")
        ax.legend(fontsize=7, labelcolor=TEXT_DIM, frameon=False)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()

        self.lbl_rv_result.setText(
            f"K = {K:.2f} ± {ek[0]:.2f} m/s\n"
            f"P = {Pp:.5f} ± {ek[1]:.5f} d\ne = {e:.3f} ± {ek[2]:.3f}\n"
            f"ω = {w:.1f}° ± {ek[3]:.1f}°\nT₀ = {T0:.3f} ± {ek[4]:.3f}\n"
            f"γ = {gamma:.2f} ± {ek[5]:.2f} m/s\n"
            f"χ²ᵣ = {out['chi2_red']:.2f}，RMS = {out['rms']:.3f} m/s")

    # ================================================= 凌星星历页
    def _build_ephemeris_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        self.txt_eph = QTextEdit()
        self.txt_eph.setPlaceholderText(
            "每行一个凌星中点时刻（儒略日 / BJD）\n# 开头为注释")
        self.txt_eph.setMaximumHeight(96)
        v.addWidget(self.txt_eph)

        row = QHBoxLayout()
        b1 = QPushButton("演示数据")
        b1.setToolTip("模拟 P = 7.351 d 的凌星序列 + 每 5 周期 2.9 分钟 TTV + 36 秒噪声（固定种子）")
        b1.clicked.connect(self._demo_eph)
        b2 = QPushButton("拟合星历（O−C）")
        b2.setObjectName("accentBtn")
        b2.clicked.connect(self._fit_ephemeris)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)

        self.fig_eph, self.canvas_eph = self._make_canvas()
        v.addWidget(self.canvas_eph, 1)
        self._fig_message(self.fig_eph, "输入凌星时刻后拟合线性星历 (T₀, P)")

        self.lbl_eph_result = self._label("结果将显示在这里")
        v.addWidget(self.lbl_eph_result)
        return page

    def _demo_eph(self):
        rng = np.random.default_rng(7)
        T0, P = 2454000.5, 7.351
        ttv = np.array([0.002 if n % 5 == 4 else 0.0 for n in range(20)])
        t = np.array([T0 + n * P for n in range(20)]) + ttv \
            + rng.normal(0.0, 36.0 / 86400.0, 20)
        self.txt_eph.setPlainText(
            "# 模拟演示数据（P=7.351 d + TTV + 36 s 噪声，seed=7）\n"
            + "\n".join(f"{ti:.6f}" for ti in t))
        self.lbl_eph_result.setText("已装入模拟演示数据（非真实观测，仅演示流程）")

    def _fit_ephemeris(self):
        rows = _parse_rows(self.txt_eph.toPlainText(), min_cols=1, max_cols=1)
        if rows is None or rows.shape[0] < 2:
            self._fig_message(self.fig_eph, "至少需要 2 个凌星时刻")
            return
        out = F.fit_transit_ephemeris(rows[:, 0])
        if out is None:
            self._fig_message(self.fig_eph, "拟合失败（时刻无法构成线性星历）")
            return
        fig = self.fig_eph
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        oc_min = out["oc"] * 24.0 * 60.0
        ax.plot(out["n"], oc_min, "o", ms=4, color="#5a83c4")
        ax.axhline(0.0, color=MPL_GRID, lw=0.8, ls="--")
        ax.set_title("凌星 O−C 图（观测 − 线性星历）")
        ax.set_xlabel("凌星序号 n")
        ax.set_ylabel("O−C (分钟)")
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()
        self.lbl_eph_result.setText(
            f"T₀ = {out['T0']:.6f}（BJD）\nP = {out['P']:.6f} d\n"
            f"O−C RMS = {out['oc_rms_days'] * 86400.0:.1f} 秒"
            f"（≈ {out['oc_rms_days'] / out['P'] * 1e6:.1f} ppm of P）\n"
            "O−C 的系统性起伏是凌星时刻变化（TTV）的信号——"
            "可能指示系统中存在另一颗行星。")

    # ================================================= 恒星与大气页
    def _build_stellar_page(self):
        page = QWidget()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)

        def add_row(r, label, widget, tip=None):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: {style.fs(11)}px;")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(widget, r, 1)
            if tip:
                lbl.setToolTip(tip)

        self.sp_mass = self._spin(1.0, 0.05, 80.0, dec=2, step=0.1, suffix="M☉",
                                  tip="主序星质量（幂律适用范围 0.08–55 M☉）")
        add_row(0, "恒星质量:", self.sp_mass)
        self.sp_a = self._spin(1.0, 0.001, 100.0, dec=3, step=0.1, suffix="AU",
                               tip="行星轨道半长轴")
        add_row(1, "行星距离:", self.sp_a)
        self.sp_albedo = self._spin(0.3, 0.0, 1.0, dec=2, step=0.05,
                                    tip="邦德反照率（地球 ≈ 0.3）")
        add_row(2, "反照率:", self.sp_albedo)
        self.cmb_redist = QComboBox()
        self.cmb_redist.addItem("全球重分布", "full")
        self.cmb_redist.addItem("仅昼面", "dayside")
        self.cmb_redist.addItem("副太阳点", "substellar")
        add_row(3, "热量重分布:", self.cmb_redist)
        self.sp_pt = self._spin(288.0, 10.0, 3000.0, dec=0, step=10, suffix="K",
                                tip="行星大气温度（算标高用）")
        add_row(4, "行星温度:", self.sp_pt)
        self.sp_mu = self._spin(28.97, 1.0, 50.0, dec=2, tip="以氢原子质量为单位（H₂≈2，地球空气≈28.97）")
        add_row(5, "平均分子量 μ:", self.sp_mu)
        self.sp_g = self._spin(9.81, 0.1, 100.0, dec=2, suffix="m/s²",
                               tip="行星表面重力")
        add_row(6, "表面重力:", self.sp_g)
        self.sp_p = self._spin(0.1, 0.001, 0.5, dec=3, step=0.01,
                               tip="行星/恒星半径比 Rp/Rs")
        add_row(7, "半径比 Rp/Rs:", self.sp_p)
        self.sp_b = self._spin(0.0, 0.0, 1.5, dec=2, step=0.05,
                               tip="撞击参数（行星中心到恒星视面中心距离 / Rs）")
        add_row(8, "撞击参数 b:", self.sp_b)
        self.sp_u1 = self._spin(0.3, 0.0, 1.0, dec=2, step=0.05,
                                tip="二次临边昏暗系数 u₁（太阳可见光 ≈ 0.3）")
        add_row(9, "临边昏暗 u₁:", self.sp_u1)
        self.sp_u2 = self._spin(0.3, 0.0, 1.0, dec=2, step=0.05,
                                tip="二次临边昏暗系数 u₂")
        add_row(10, "临边昏暗 u₂:", self.sp_u2)
        v.addLayout(grid)

        row = QHBoxLayout()
        btn = QPushButton("计算")
        btn.setObjectName("accentBtn")
        btn.clicked.connect(self._compute_stellar)
        row.addWidget(btn)
        self.cmb_stchart = QComboBox()
        self.cmb_stchart.addItem("黑体光谱", "bb")
        self.cmb_stchart.addItem("临边昏暗凌星光变", "ld")
        self.cmb_stchart.currentIndexChanged.connect(self._compute_stellar)
        row.addWidget(self.cmb_stchart, 1)
        v.addLayout(row)

        self.fig_st, self.canvas_st = self._make_canvas()
        v.addWidget(self.canvas_st)
        self._fig_message(self.fig_st, "输入参数后点「计算」")

        self.lbl_st_result = self._label("主序幂律为经验近似（精度 10–30%），巨星 / 白矮星不适用。")
        v.addWidget(self.lbl_st_result)

        area.setWidget(inner)
        wrap = QVBoxLayout(page)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(area)
        return page

    def _compute_stellar(self, *_):
        m = self.sp_mass.value()
        a = self.sp_a.value()
        A = self.sp_albedo.value()
        redist = self.cmb_redist.currentData()
        try:
            L = S.main_sequence_luminosity(m)
            R = S.main_sequence_radius(m)
            tau = S.main_sequence_lifetime_gyr(m)
            teff = S.teff_from_luminosity_radius(L, R)
            scls = S.spectral_class(teff) if teff else "未知"
            peak = S.wien_peak_nm(teff) if teff else None
            teq = S.equilibrium_temperature(L, a, A, redist)
            H_km = S.scale_height_m(self.sp_pt.value(), self.sp_mu.value(),
                                    self.sp_g.value()) / 1000.0
            p, b = self.sp_p.value(), self.sp_b.value()
            u1, u2 = self.sp_u1.value(), self.sp_u2.value()
            depth_ld = S.transit_depth_limb_darkened(p, b, u1, u2)
        except Exception as ex:
            self.lbl_st_result.setText(f"计算失败：{ex}")
            return

        self.lbl_st_result.setText(
            f"主序模型（M = {m:.2f} M☉）：L = {L:.4g} L☉，R = {R:.3f} R☉，"
            f"τ ≈ {tau:.2f} Gyr\n"
            f"反推 Teff ≈ {teff:.0f} K（{scls} 型），"
            f"黑体峰值 λ ≈ {peak:.0f} nm\n"
            f"行星（a = {a:g} AU，A = {A:.2f}，{self.cmb_redist.currentText()}）："
            f"T_eq = {teq:.1f} K\n"
            f"大气标高 H = {H_km:.2f} km（T={self.sp_pt.value():.0f} K，"
            f"μ={self.sp_mu.value():g}，g={self.sp_g.value():g} m/s²）\n"
            f"凌星深度：几何 p² = {p * p * 1e6:.0f} ppm → "
            f"含临边昏暗 = {depth_ld * 1e6:.0f} ppm（b = {b:.2f}）")

        fig = self.fig_st
        fig.clear()
        ax = fig.add_subplot(111)
        self._style_ax(ax)
        if self.cmb_stchart.currentData() == "bb" and teff:
            lam = np.linspace(max(50.0, peak * 0.2), peak * 5.0, 800)
            ax.plot(lam, S.planck_b_lambda(lam, teff), color="#e6913f", lw=1.3)
            ax.axvline(peak, color=MPL_GRID, ls="--", lw=0.8)
            ax.set_title(f"黑体光谱（Teff ≈ {teff:.0f} K）")
            ax.set_xlabel("波长 (nm)")
            ax.set_ylabel("B_λ (W·m⁻³·sr⁻¹)")
        else:
            p = self.sp_p.value()
            z = np.linspace(1.0 + p, 0.0, 240)
            flux = S.transit_flux_curve_limb_darkened(
                z, p, self.sp_u1.value(), self.sp_u2.value(), n_grid=300)
            ax.plot(z, flux, color="#5a83c4", lw=1.3)
            ax.set_title("临边昏暗凌星光变（二次定律）")
            ax.set_xlabel("行星−恒星视心距 z (Rs)")
            ax.set_ylabel("相对亮度")
            ax.set_xlim(1.0 + p, 0.0)
            ax.set_ylim(flux.min() - 0.002, 1.002)
        fig.tight_layout(pad=0.8)
        fig.canvas.draw_idle()

    # ---------- 主题 / 翻译桩（主窗口统一调度） ----------
    def retranslate(self):
        pass

    def restyle(self):
        pass