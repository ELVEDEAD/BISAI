"""
orbit_fit.py —— 轨道反演：由观测数据反推开普勒轨道参数

正问题（给定参数算曲线）在 core/kepler.py 与 core/exo_obs.py；本模块做
逆问题（给定观测数据拟合参数），覆盖科研中两条主路径：

* 视向速度（RV）轨道拟合：周期图找 P → 非线性最小二乘解 (K, P, e, ω, T₀, γ)
* 凌星星历拟合：多次凌星中点时刻 → 线性最小二乘解 (T₀, P) 与 O−C 图

公式与算法来源：
* RV 模型：RV(t) = K·[cos(ν + ω) + e·cos ω] + γ（ν 为真近点角，由开普勒
  方程数值解出）；单行批次数据复用 kepler.solve_kepler_vec 向量化求解
* 周期图：floating-mean Lomb-Scargle 的 χ² 等价形式——逐频率对基
  {1, sin ωt, cos ωt} 做线性最小二乘，取 χ² 最小的频率（Scargle 1982；
  cumming 2004）
* 参数不确定度：协方差 ≈ (JᵀJ)⁻¹·s²，s² = 2·χ²/(N−m)（高斯近似，仅收敛
  良好时可信）

科学诚实性：
* RV 拟合给出的是 M·sin i 下的 K；倾角未知的单星数据无法解除简并
* 拟合基于二体开普勒模型，不含行星间摄动与恒星活动信号（jitter 需另计）
* 观测点数不足（RV < 8 点、凌星时刻 < 2 次）时返回 None，不做伪造拟合
"""
import math

import numpy as np


from core.kepler import solve_kepler_vec


# ---------- RV 正模型（供拟合与注入式自测复用） ----------
def rv_model(params, t):
    """开普勒 RV 模型。params = (K, P, e, omega_deg, T0, gamma)；t 单位天。

    返回与 t 等长的 RV 数组（K 与 gamma 同单位，通常 m/s）。
    """
    K, P, e, omega_deg, T0, gamma = params
    e = min(max(e, 0.0), 0.99)
    w = math.radians(omega_deg)
    M = 2.0 * math.pi * (np.asarray(t, dtype=np.float64) - T0) / P
    E = solve_kepler_vec(M, np.full(M.shape, e))
    # 偏近点角 → 真近点角 ν（半角公式）
    nu = 2.0 * np.arctan2(np.sqrt(1.0 + e) * np.sin(E / 2.0),
                          np.sqrt(1.0 - e) * np.cos(E / 2.0))
    return K * (np.cos(nu + w) + e * math.cos(w)) + gamma


# ---------- 周期搜索 ----------
def rv_periodogram(t, rv, rv_err=None, pmin=None, pmax=None, n_freq: int = 10000):
    """floating-mean 周期图：χ²(f) 扫描 → (周期数组, χ² 数组, 最佳周期)。

    每个频率对基 {1, sin, cos} 做加权线性最小二乘（闭式 3×3 正规方程），
    χ² 最小处即候选周期。pmin/pmax 缺省取 [2·中位采样间隔, 观测基线]。
    """
    t = np.asarray(t, dtype=np.float64)
    y = np.asarray(rv, dtype=np.float64)
    if t.size != y.size or t.size < 4:
        return None, None, None
    sig = np.asarray(rv_err if rv_err is not None else 1.0, dtype=np.float64)
    if np.isscalar(sig) or sig.size == 1:
        sig = np.full(t.shape, float(sig))
    sig = np.where(sig > 0, sig, 1.0)
    w = 1.0 / sig ** 2

    span = float(t.max() - t.min())
    if span <= 0:
        return None, None, None
    pmin = pmin if pmin else max(2.0 * float(np.median(np.diff(np.sort(t)))), 1e-3)
    pmax = pmax if pmax else span * 1.2
    if not (0 < pmin < pmax):
        return None, None, None

    freqs = np.linspace(1.0 / pmax, 1.0 / pmin, n_freq)
    chi2 = np.empty_like(freqs)
    wy = w * y
    for i, f in enumerate(freqs):
        A = np.column_stack([np.ones_like(t), np.sin(2 * math.pi * f * t),
                             np.cos(2 * math.pi * f * t)])
        WA = A * w[:, None]
        try:
            coef = np.linalg.solve(A.T @ WA, WA.T @ y)
        except np.linalg.LinAlgError:
            chi2[i] = np.inf
            continue
        chi2[i] = float(np.sum(w * (y - A @ coef) ** 2))
    best = int(np.argmin(chi2))
    return 1.0 / freqs, chi2, float(1.0 / freqs[best])


# ---------- RV 开普勒拟合 ----------
def fit_rv_kepler(t, rv, rv_err=None, p_guess=None):
    """单行星开普勒 RV 轨道拟合（非线性最小二乘）。

    参数：
        t, rv, rv_err  观测（天；速度；速度误差，可 None → 等权）
        p_guess        周期初值（天，None 时自动跑周期图）

    返回 dict：
        params  (K, P, e, omega_deg, T0, gamma)
        errors  对应 1σ 高斯近似不确定度（协方差 (JᵀJ)⁻¹·s² 对角线开方）
        chi2_red, rms, periodogram_best（若跑了周期图）
    数据点 < 8 或拟合不收敛时返回 None。
    """
    t = np.asarray(t, dtype=np.float64)
    y = np.asarray(rv, dtype=np.float64)
    if t.size != y.size or t.size < 8:
        return None
    if np.any(~np.isfinite(y)) or np.any(~np.isfinite(t)):
        return None
    sig = np.asarray(rv_err if rv_err is not None else 1.0, dtype=np.float64)
    if np.isscalar(sig) or sig.size == 1:
        sig = np.full(t.shape, float(sig))
    sig = np.where(np.isfinite(sig) & (sig > 0), sig, max(float(np.std(y)), 1e-6))

    pgram_best = None
    if p_guess is None or p_guess <= 0:
        _, _, pgram_best = rv_periodogram(t, y, sig, n_freq=20000)
        p_guess = pgram_best if pgram_best else float(t.max() - t.min() or 1.0)

    # 初值网格：(e₀, ω₀) 强耦合，单初值易陷局部极小，取 χ² 最小者
    gamma0 = float(np.mean(y))
    K0 = max(0.5 * float(np.ptp(y)), 1e-3)
    T00 = float(t[int(np.argmax(y))])

    def resid(p):
        return (rv_model(p, t) - y) / sig

    best = None
    from scipy.optimize import least_squares
    for e0, w0 in ((0.05, 0.0), (0.3, 90.0), (0.5, 180.0)):
        x0 = [K0, p_guess, e0, w0, T00, gamma0]
        try:
            res = least_squares(
                resid, x0, method="trf",
                bounds=([0.0, 1e-3, 0.0, -360.0, -np.inf, -np.inf],
                        [np.inf, np.inf, 0.95, 360.0, np.inf, np.inf]),
                max_nfev=20000)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if res.success and (best is None or res.cost < best.cost):
            best = res
    res = best
    if res is None:
        return None

    n, m = t.size, 6
    dof = max(n - m, 1)
    chi2_red = float(2.0 * res.cost / dof)
    rms = float(np.sqrt(np.mean((res.fun * sig) ** 2)))

    # 协方差 (JᵀJ)⁻¹·s² → 1σ 参数误差
    try:
        JTJ = res.jac.T @ res.jac
        cov = np.linalg.inv(JTJ) * (2.0 * res.cost / dof)
        errs = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        errs = np.full(6, np.nan)

    params = tuple(float(v) for v in res.x)
    out = {"params": params, "errors": tuple(float(v) for v in errs),
           "chi2_red": chi2_red, "rms": rms, "converged": bool(res.success)}
    if pgram_best:
        out["periodogram_best"] = pgram_best
    # 模型曲线（均匀相位采样，供 UI 绘制）
    t_grid = np.linspace(t.min(), t.min() + params[1], 600)
    out["model_t"] = t_grid
    out["model_rv"] = rv_model(params, t_grid)
    return out


# ---------- 凌星星历（TTV 基础） ----------
def fit_transit_ephemeris(t_transits, p_guess=None):
    """凌星中点时刻序列 → 线性最小二乘星历 (T0, P) 与 O−C 残差。

    t_k = T0 + n_k·P：循环数 n_k 由候选周期取整得到，在 p_guess 邻域
    （0.5×–2×，几何网格扫描）取 O−C RMS 最小的候选，再迭代细化至稳定
    （防止周期猜测偏差导致 epoch 错分）。返回 dict：T0、P、n、oc（天）、
    oc_rms_days、p_guess；时刻数 < 2 返回 None。
    """
    t = np.sort(np.asarray(t_transits, dtype=np.float64))
    if t.size < 2:
        return None
    if p_guess is None or p_guess <= 0:
        if t.size >= 3:
            p_guess = float(np.median(np.diff(t)))
        else:
            p_guess = float(t[1] - t[0])
        if p_guess <= 0:
            return None

    def _linfit(n, tt):
        """给定循环数解正规方程 → (T0, P, oc)；失败返回 None"""
        A = np.column_stack([np.ones_like(tt), n.astype(np.float64)])
        try:
            T0, P = np.linalg.solve(A.T @ A, A.T @ tt)
        except np.linalg.LinAlgError:
            return None
        if P <= 0:
            return None
        oc = tt - (T0 + n * P)
        return float(T0), float(P), oc

    def _dedup(n, tt):
        """同一 epoch 多次记录只保留首见"""
        _, first = np.unique(n, return_index=True)
        return n[first], tt[first]

    # 候选周期网格：O−C RMS 最小者胜出（epoch 正确分配时 O−C 几乎为 0）。
    # RMS 相近（< 1.5×最小值）时取最接近 p_guess 者——「P 减半 epoch 加倍」
    # 与「P 加倍隔次观测」均与真解 RMS 并列，需靠周期先验打破简并。
    candidates = []
    for p_try in np.geomspace(p_guess * 0.5, p_guess * 2.0, 240):
        n = np.round((t - t[0]) / p_try)
        if n[-1] < 1:
            continue
        n, tt = _dedup(n, t)
        if tt.size < 2:
            continue
        fit = _linfit(n, tt)
        if fit is None:
            continue
        rms = float(np.sqrt(np.mean(fit[2] ** 2)))
        candidates.append((rms, fit, n, tt))
    if not candidates:
        return None
    r_min = min(c[0] for c in candidates)
    near = [c for c in candidates if c[0] <= max(1.5 * r_min, r_min + 1e-9)]
    best = min(near, key=lambda c: abs(c[1][1] - p_guess))   # 以先验打破简并
    rms, fit, n, tt = best

    # 迭代细化：用当前 P 重算循环数，至稳定（最多 10 轮）
    _, fit, n, tt = best
    for _ in range(10):
        n_new, tt_new = _dedup(np.round((t - t[0]) / fit[1]), t)
        if tt_new.size < 2:
            break
        new_fit = _linfit(n_new, tt_new)
        if new_fit is None:
            break
        if np.array_equal(n_new, n):
            fit = new_fit
            break
        n, tt, fit = n_new, tt_new, new_fit

    T0, P, oc = fit
    return {"T0": T0, "P": P, "n": n.astype(int),
            "oc": oc, "oc_rms_days": float(np.sqrt(np.mean(oc ** 2))),
            "p_guess": float(p_guess)}