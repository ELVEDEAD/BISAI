"""
photometry.py —— 观测数据处理：CCD 定标、孔径测光、去噪与光谱预处理

科研流程对应关系（与 fits_io.py 配合使用）：
    原始 FITS 帧 → calibrate_image（偏置/暗流/平场）→ remove_cosmic_rays
    → aperture_photometry（孔径测光 + 天背景）→ flux_to_mag + 大气消光
    光谱 FITS → savgol_smooth（去噪）→ normalize_spectrum（连续谱归一化）

公式与算法来源：
    * CCD 定标线性模型：S = (Raw − Bias − Dark·t) / Flat   （标准 CCD 方程）
    * 孔径测光信噪比：SNR = F·g / √(F·g + n_ap·(B + RN²/g))（Merline & Howell 1995 简化）
    * 大气消光：m_真 = m_观测 − k·X，气团 X 采用 Kasten & Young (1989) 公式
    * 宇宙线剔除：拉普拉斯响应 + σ 裁剪（van Dokkum 2001 的单帧简化版）
    * Savitzky-Golay 平滑：保谱线形状的时域多项式平滑（scipy.signal）

科学诚实性：
    * 测光输出以 ADU 计（gain 默认 1，即电子=ADU）；SNR 公式为泊松+读出噪声
      近似，未含平场误差项与暗流散粒噪声（保守估计）
    * 连续谱拟合为分段中值 + 线性插值，仅适用于吸收线稀疏的连续谱
"""
import math

import numpy as np


from core.constants import RAD2DEG


# ---------- CCD 图像定标 ----------
def calibrate_image(raw, bias=None, dark=None, dark_exptime=None,
                    flat=None, exptime=None):
    """CCD 线性定标：S = (Raw − Bias − Dark·t_exp) / Flat。

    dark 与 exptime 任一为 None 时跳过暗流项；flat 为 None 时跳过平场项。
    flat 中接近 0 的像素（坏像素）返回 NaN，调用方需掩膜处理。
    """
    data = np.asarray(raw, dtype=np.float64).copy()
    if bias is not None:
        data -= np.asarray(bias, dtype=np.float64)
    if dark is not None and dark_exptime and exptime:
        data -= np.asarray(dark, dtype=np.float64) * (exptime / dark_exptime)
    if flat is not None:
        f = np.asarray(flat, dtype=np.float64)
        safe = np.where(np.abs(f) < 1e-8, np.nan, f)
        data = data / safe
    return data


# ---------- 统计 ----------
def sigma_clipped_stats(data, sigma: float = 3.0, iters: int = 5):
    """迭代 σ 裁剪统计 → (均值, 中位数, 标准差)。NaN 参与判定但不计入统计。"""
    d = np.asarray(data, dtype=np.float64).ravel()
    d = d[np.isfinite(d)]
    if d.size == 0:
        return float("nan"), float("nan"), float("nan")
    lo, hi = d.min(), d.max()
    for _ in range(iters):
        med = np.median(d)
        std = d.std()
        if std == 0:
            break
        mask = np.abs(d - med) <= sigma * std
        if mask.all() or (~mask).sum() < 2:
            d = d[mask]
            break
        d = d[mask]
    return float(d.mean()), float(np.median(d)), float(d.std())


# ---------- 孔径测光 ----------
def _fraction_in_circle(dx: np.ndarray, dy: np.ndarray, r: float, sub: int = 5) -> np.ndarray:
    """像素被半径 r 圆覆盖的面积分数（sub×sub 子采样网格估计）"""
    if sub <= 1:
        return (np.hypot(dx, dy) < r).astype(np.float64)
    offs = (np.arange(sub) + 0.5) / sub - 0.5          # 子采样中心偏移
    sx = dx[:, None, None] + offs[None, :, None]
    sy = dy[:, None, None] + offs[None, None, :]
    hit = (np.hypot(sx, sy) < r).mean(axis=(1, 2))
    return hit


def aperture_photometry(data, x: float, y: float, r_ap: float,
                        r_in: float = None, r_out: float = None,
                        gain: float = 1.0, read_noise: float = 0.0):
    """圆孔径 + 环形天背景孔径测光。

    参数：
        data        二维图像（ADU）
        x, y       孔径中心（像素坐标，(0,0) 为第 [0,0] 像素中心？——约定
                    x 为列、y 为行，像素 [j, i] 中心在 (i+0, j+0)…即整数格点）
        r_ap        孔径半径（像素）
        r_in/r_out  天背景环内/外半径（None 时不做天背景扣除）
        gain        增益（e⁻/ADU，默认 1）
        read_noise  读出噪声（e⁻）

    返回 dict：flux（背景扣除后，ADU）、flux_err、mag（仪器星等
    m = −2.5·log₁₀F，F ≤ 0 时为 NaN）、mag_err、snr、sky_per_pix、n_ap
    """
    img = np.asarray(data, dtype=np.float64)
    ny, nx = img.shape
    r_in = r_in if r_in is not None else r_ap * 1.5
    r_out = r_out if r_out is not None else r_in * 2.0

    half = int(math.ceil(max(r_ap, r_out)))
    x0, x1 = max(0, int(math.floor(x)) - half - 1), min(nx, int(math.floor(x)) + half + 2)
    y0, y1 = max(0, int(math.floor(y)) - half - 1), min(ny, int(math.floor(y)) + half + 2)
    xs = np.arange(x0, x1)
    ys = np.arange(y0, y1)
    gx, gy = np.meshgrid(xs, ys)                     # 像素中心（整数格点）
    dx = (gx - x).ravel()
    dy = (gy - y).ravel()
    vals = img[y0:y1, x0:x1].ravel()

    frac = _fraction_in_circle(dx, dy, r_ap)
    in_ap = frac > 0
    n_ap = float(frac.sum())

    if r_out > r_in > 0:
        ring = (np.hypot(dx, dy) >= r_in) & (np.hypot(dx, dy) <= r_out)
        if ring.sum() >= 3:
            _, sky_med, _ = sigma_clipped_stats(vals[ring])
        else:
            sky_med = 0.0
    else:
        sky_med = 0.0
    sky = float(sky_med) if np.isfinite(sky_med) else 0.0

    raw_flux = float((vals * frac)[in_ap].sum()) if in_ap.any() else 0.0
    flux = raw_flux - sky * n_ap

    # SNR：泊松（源+天）+ 读出噪声，均换算到电子
    f_e = max(flux, 0.0) * gain
    b_e = max(sky, 0.0) * gain
    var_e = f_e + n_ap * (b_e + read_noise * read_noise)
    snr = f_e / math.sqrt(var_e) if var_e > 0 else float("inf")

    flux_err = (math.sqrt(var_e) / gain) if gain > 0 and var_e > 0 else float("nan")
    mag = -2.5 * math.log10(flux) if flux > 0 else float("nan")
    mag_err = (2.5 / math.log(10)) / snr if snr > 0 else float("nan")

    return {"flux": flux, "flux_err": flux_err, "mag": mag, "mag_err": mag_err,
            "snr": snr, "sky_per_pix": sky, "n_ap": n_ap,
            "raw_flux": raw_flux}


# ---------- 星等与消光 ----------
def flux_to_mag(flux, zeropoint: float = 0.0):
    """流量 → 星等：m = −2.5·log₁₀(F/F₀) = −2.5·log₁₀F + ZP（F ≤ 0 → NaN）"""
    f = np.asarray(flux, dtype=np.float64)
    out = np.where(f > 0, -2.5 * np.log10(np.where(f > 0, f, 1.0)) + zeropoint, np.nan)
    return float(out) if np.isscalar(flux) else out


def mag_to_flux(mag, zeropoint: float = 0.0):
    """星等 → 流量（相对流量单位，ZP=0 时即仪器流量）"""
    m = np.asarray(mag, dtype=np.float64)
    out = 10.0 ** (-0.4 * (m - zeropoint))
    return float(out) if np.isscalar(mag) else out


def airmass(zenith_deg: float) -> float:
    """气团（Kasten & Young 1989）：X = 1 / [cos z + 0.50572(96.07995 − z)^(−1.6364)]"""
    z = float(zenith_deg)
    if not 0.0 <= z < 91.0:
        return float("inf")
    zr = z / RAD2DEG                               # 度 → 弧度
    return 1.0 / (math.cos(zr) + 0.50572 * (96.07995 - z) ** (-1.6364))


def correct_extinction(mag_instrumental: float, zenith_deg: float,
                       k_mag_per_airmass: float):
    """大气消光改正：m₀ = m_inst − k·X（X 为气团，k 为波段消光系数 mag/airmass）"""
    return mag_instrumental - k_mag_per_airmass * airmass(zenith_deg)


# ---------- 图像去噪 ----------
def remove_cosmic_rays(data, sigma: float = 6.0, min_neighbors: int = 3):
    """单帧宇宙线剔除（van Dokkum 2001 简化版）。

    判据：像素值 > σ·局部噪声 且 显著高于 3×3 邻域中值（宇宙线为「尖峰」，
    恒星为 PSF 展宽）。命中像素用邻域中值替换，返回 (图像副本, 命中掩膜)。
    """
    img = np.asarray(data, dtype=np.float64)
    out = img.copy()
    ny, nx = img.shape
    hit = np.zeros(img.shape, dtype=bool)
    if nx < 3 or ny < 3:
        return out, hit

    # 3×3 邻域中值（边界用镜像填充）
    pad = np.pad(img, 1, mode="reflect")
    stack = np.dstack([pad[dy:dy + ny, dx:dx + nx]
                       for dy in range(3) for dx in range(3)
                       if not (dy == 1 and dx == 1)])
    med = np.median(stack, axis=2)
    # σ·噪声底：全局稳健 σ（MAD 放大）
    _, _, mad_std = sigma_clipped_stats(img)
    if not np.isfinite(mad_std) or mad_std <= 0:
        mad_std = np.std(img)
        if mad_std <= 0:
            return out, hit

    suspicious = (img - med) > sigma * mad_std

    # 邻域内显著像素计数（PSF 星像会在相邻像素连续，宇宙线孤立）
    cnt = np.zeros(img.shape, dtype=int)
    spad = np.pad(suspicious, 1, mode="constant")
    for dy in range(3):
        for dx in range(3):
            if dy == 1 and dx == 1:
                continue
            cnt += spad[dy:dy + ny, dx:dx + nx].astype(int)
    hit = suspicious & (cnt < min_neighbors)
    out[hit] = med[hit]

    return out, hit


def median_filter_image(data, size: int = 3):
    """二维中值滤波（边界镜像填充）。size 为奇数窗口边长（像素）。"""
    if size < 3 or size % 2 == 0:
        raise ValueError("size 须为 ≥3 的奇数")
    img = np.asarray(data, dtype=np.float64)
    pad = size // 2
    p = np.pad(img, pad, mode="reflect")
    ny, nx = img.shape
    win = size * size
    stack = np.empty((win, ny, nx))
    k = 0
    for dy in range(size):
        for dx in range(size):
            stack[k] = p[dy:dy + ny, dx:dx + nx]
            k += 1
    return np.median(stack, axis=0)


# ---------- 光谱预处理 ----------
def savgol_smooth(flux, window: int = 11, polyorder: int = 3):
    """Savitzky-Golay 平滑（光谱/光变去噪，保峰形）。window 为奇数。"""
    y = np.asarray(flux, dtype=np.float64)
    if window % 2 == 0 or window < polyorder + 2:
        window = max(polyorder + 2 + (polyorder + 2) % 2, 5)
    from scipy.signal import savgol_filter
    return savgol_filter(y, window_length=window, polyorder=polyorder)


def estimate_continuum(wave, flux, n_segments: int = 20,
                       percentile: float = 95.0):
    """连续谱估计：等波长分段取高分位（默认 95%）→ 线性插值到全波长。

    高分位而非最大值，可抵抗少量宇宙线/发射线污染。
    """
    w = np.asarray(wave, dtype=np.float64)
    f = np.asarray(flux, dtype=np.float64)
    if w.size < n_segments * 2:
        n_segments = max(1, w.size // 4)
    edges = np.linspace(0, w.size, n_segments + 1, dtype=int)
    knots_w, knots_f = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        seg_w, seg_f = w[a:b], f[a:b]
        good = np.isfinite(seg_f)
        if good.sum() == 0:
            continue
        knots_w.append(float(np.median(seg_w[good])))
        knots_f.append(float(np.percentile(seg_f[good], percentile)))
    knots_w, knots_f = np.asarray(knots_w), np.asarray(knots_f)
    order = np.argsort(knots_w)
    return np.interp(w, knots_w[order], knots_f[order])


def normalize_spectrum(wave, flux, n_segments: int = 20, percentile: float = 95.0):
    """连续谱归一化：flux / continuum → 归一化光谱（连续谱 ≈ 1，吸收线 < 1）。

    同时返回连续谱本身，供质量检查。
    """
    cont = estimate_continuum(wave, flux, n_segments, percentile)
    safe = np.where(np.abs(cont) < 1e-12, np.nan, cont)
    return np.asarray(flux, dtype=np.float64) / safe, cont


def apply_redshift(wave_rest, z: float):
    """红移波长网格：λ_观测 = λ_静止·(1 + z)"""
    return np.asarray(wave_rest, dtype=np.float64) * (1.0 + z)