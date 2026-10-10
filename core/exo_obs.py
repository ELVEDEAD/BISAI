"""
exo_obs.py —— 系外行星观测特征（凌星光变 / 视向速度 / 宜居带）

三种「观测特征」均由行星与宿主星参数解析算出，公式取自公开文献，可复现、
无随机数；参数缺失时返回 None（界面显示「未知」，不伪造）。

物理约定
--------
* 凌星（transit）：行星自宿主星前方通过，亮度按 (Rp/Rs)² 下降。光变曲线用
  「双圆重叠面积」解析式（无临边昏暗），比梯形模型平滑，且能表现掠凌的
  「浅而长」形态。
* 视向速度（radial velocity）：恒星被行星引力牵引产生的谱线摆动，半振幅 K
  由质量函数给出；缺行星或恒星质量时无法给出 K（标未知）。
* 宜居带（habitable zone）：Kopparapu et al. 2013 的 Seff 多项式，给出
  「保守」（失控温室 ~ 最大温室）与「乐观」（近期金星 ~ 早期火星）两条边界。

科学诚实性
----------
* 撞击参数 b 取决于轨道倾角 i，多数行星的 i 未测定：默认按中心凌 b=0 计算，
  并由 b=0（最长）到掠凌（最短）给出**持续时间区间**（不确定性可视化），
  界面须同时标注「假设值」。
* K 的取值含 sin i：本模块给出的是 M·sin i 下的最小值；真实 K 只会更大。
* 光变曲线不含临边昏暗、行星自身辐射与凌星时差，仅反映几何遮挡。
"""
import math

import numpy as np

from core.constants import AU_KM, R_SUN_KM, M_JUPITER_KG, M_EARTH_KG
from core.kepler import solve_kepler

# 1 木星质量 = 多少地球质量（换算 K 公式里的 Mp/M_Jup）
M_EARTH_PER_JUP = M_JUPITER_KG / M_EARTH_KG

# 太阳参数（宜居带与光照度的参照基准）
SUN_TEFF = 5772.0
SUN_LUM_SOLAR = 1.0

# Kopparapu et al. 2013 (ApJ 765, 131) 表 3：Seff = S0 + aT + bT² + cT³ + dT⁴
# T = Teff − 5780 K，适用 2600–7200 K
HZ_COEFFS = {
    "recent_venus":       (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse": (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "moist_greenhouse":   (1.000, 8.1774e-5, 1.7063e-9, -4.3241e-12, -6.6462e-16),
    "max_greenhouse":     (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars":         (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
}

HZ_LABELS = {
    "recent_venus": "近期金星（乐观内边界）",
    "runaway_greenhouse": "失控温室（保守内边界）",
    "moist_greenhouse": "潮湿温室",
    "max_greenhouse": "最大温室（保守外边界）",
    "early_mars": "早期火星（乐观外边界）",
}

RV_K_COEF = 28.4329     # m/s：K = 28.4329 · (Mp sin i/M_Jup) · (M*/M☉)^(-2/3) · (P/yr)^(-1/3)


# ---------- 宿主星参数 ----------
def star_radius_km(body) -> float:
    """宿主恒星半径（km）：太阳系取太阳半径，系外行星取 st_rad（R☉）"""
    if getattr(body, "body_type", "") in ("planet_solar", "dwarf"):
        return R_SUN_KM
    r = getattr(body, "host_radius_solar", None)
    return r * R_SUN_KM if r else None


def star_teff(body) -> float:
    """宿主恒星有效温度（K）"""
    if getattr(body, "body_type", "") in ("planet_solar", "dwarf"):
        return SUN_TEFF
    return getattr(body, "host_teff", None)


def star_luminosity_solar(body) -> float:
    """宿主星光度（L☉）：优先用 st_lum（log L☉），否则由 R、Teff 反推"""
    if getattr(body, "body_type", "") in ("planet_solar", "dwarf"):
        return SUN_LUM_SOLAR
    log_l = getattr(body, "host_lum", None)
    if log_l is not None:
        return 10.0 ** float(log_l)
    r = getattr(body, "host_radius_solar", None)
    t = getattr(body, "host_teff", None)
    if r and t:
        return (r ** 2) * (t / SUN_TEFF) ** 4
    return None


def star_mass_solar(body) -> float:
    """宿主恒星质量（M☉）：缺数据时按 1 M☉ 处理（用于 K 的近似）"""
    if getattr(body, "body_type", "") in ("planet_solar", "dwarf"):
        return 1.0
    return getattr(body, "host_mass_solar", None)


# ---------- 凌星 ----------
def radius_ratio(body) -> float:
    """Rp/Rs（行星与恒星半径比）；缺半径返回 None"""
    rp = getattr(body, "radius_km", None)
    rs = star_radius_km(body)
    if not rp or not rs:
        return None
    return rp / rs


def a_in_stellar_radii(body) -> float:
    """a/Rs（半长轴以恒星半径为单位）"""
    a = getattr(body, "a_au", None)
    rs = star_radius_km(body)
    if not a or not rs:
        return None
    return a * AU_KM / rs


def transit_depth_ppm(body) -> float:
    """凌星深度（ppm）：(Rp/Rs)² × 1e6"""
    p = radius_ratio(body)
    return p * p * 1e6 if p else None


def transit_durations_days(body, b: float = 0.0):
    """凌星持续时间（天）：(总时长 T14, 全食时长 T23)。含 sin i≈1（正凌）假设。

    T = (P/π) · arcsin[ (Rs/a)·sqrt(k² − b²) ]，k 取 1+p（第一/第四接触）
    或 |1−p|（第二/第三接触）。
    """
    P = body.period
    a_rs = a_in_stellar_radii(body)
    p = radius_ratio(body)
    if not P or not a_rs or not p:
        return None

    def _dur(k):
        arg = (1.0 / a_rs) * math.sqrt(max(0.0, k * k - b * b))
        return (P / math.pi) * math.asin(min(1.0, arg))

    return _dur(1.0 + p), _dur(abs(1.0 - p))


def transit_b_max(body) -> float:
    """掠凌撞击参数上限（再大就不再遮挡）：b = 1 + Rp/Rs"""
    p = radius_ratio(body)
    return 1.0 + p if p else None


def _overlap_flux(z: float, p: float) -> float:
    """双圆遮挡下的相对亮度（1 = 未遮挡）。星半径归一化为 1，行星 p，中心距 z。"""
    if z >= 1.0 + p:
        return 1.0
    if p >= 1.0 + z:
        return 0.0
    if z <= abs(1.0 - p):
        return 1.0 - p * p
    z2, p2 = z * z, p * p
    k1 = max(-1.0, min(1.0, (z2 + p2 - 1.0) / (2.0 * z * p)))
    k2 = max(-1.0, min(1.0, (z2 + 1.0 - p2) / (2.0 * z)))
    tri = (-z + p + 1.0) * (z + p - 1.0) * (z - p + 1.0) * (z + p + 1.0)
    area = p2 * math.acos(k1) + math.acos(k2) - 0.5 * math.sqrt(max(0.0, tri))
    return 1.0 - area / math.pi


def transit_flux_on_grid(body, t_days, b: float = 0.0):
    """给定时间网格（相对凌星中点，单位天）计算相对亮度数组。

    供光变曲线的「撞击参数不确定性包络」复用同一几何模型。
    """
    P = body.period
    a_rs = a_in_stellar_radii(body)
    p = radius_ratio(body)
    if not P or not a_rs or not p:
        return None
    cos_i = b / a_rs
    theta = 2.0 * np.pi * np.asarray(t_days, dtype=np.float64) / P
    z = a_rs * np.sqrt(np.sin(theta) ** 2 + (cos_i * np.cos(theta)) ** 2)
    return np.array([_overlap_flux(float(zz), p) for zz in z])


def transit_light_curve(body, b: float = 0.0, n: int = 480):
    """凌星光变曲线：返回 (t_days, flux, info)。

    t_days 以凌星中点（t=0）为原点，单位为天；info 含深度、时长、几何量。
    """
    P = body.period
    a_rs = a_in_stellar_radii(body)
    p = radius_ratio(body)
    if not P or not a_rs or not p:
        return None, None, None
    b = max(0.0, min(b, transit_b_max(body)))
    durs = transit_durations_days(body, b)
    if durs is None:
        return None, None, None
    t14 = durs[0]
    span = max(t14 * 1.6, P * 1e-4)
    t = np.linspace(-span / 2.0, span / 2.0, n)
    flux = transit_flux_on_grid(body, t, b)
    info = {
        "p": p, "a_rs": a_rs, "b": b,
        "depth_ppm": p * p * 1e6,
        "t14_days": t14, "t23_days": durs[1],
        "t14_hours": t14 * 24.0, "t23_hours": durs[1] * 24.0,
        "span_days": span,
        "b_max": transit_b_max(body),
        "b_assumed": True,
    }
    return t, flux, info


def transit_duration_range_hours(body):
    """持续时间区间（小时）：(最短, 最长)。用于不确定性可视化。

    取 b ∈ [0, 1] 这一「行星中心落在恒星视面内」的正凌范围：
    b=0 为中心凌（最长），b=1 为擦边凌（最短）。b 取决于轨道倾角，
    多数行星未测定，故以区间呈现而非单一值。
    """
    b_max = transit_b_max(body)
    if b_max is None:
        return None
    b_short = min(1.0, b_max)
    longest = transit_durations_days(body, 0.0)
    shortest = transit_durations_days(body, b_short)
    if longest is None or shortest is None:
        return None
    return shortest[0] * 24.0, longest[0] * 24.0


# ---------- 视向速度 ----------
def rv_semi_amplitude_m_s(body, sin_i: float = 1.0) -> float:
    """视向速度半振幅 K（m/s）。

    K = 28.4329 · (Mp·sin i / M_Jup) · (M*/M☉)^(−2/3) · (P/yr)^(−1/3) / sqrt(1−e²)
    近似 M* ≫ Mp。缺行星质量或周期返回 None。
    """
    mp = getattr(body, "mass_earth", None)
    P = body.period
    if not mp or not P:
        return None
    m_star = star_mass_solar(body)
    if not m_star:
        m_star = 1.0
    mp_jup = mp / M_EARTH_PER_JUP
    e = getattr(body, "e", None) or 0.0
    p_yr = P / 365.25
    k = (RV_K_COEF * (mp_jup * sin_i) * (m_star ** (-2.0 / 3.0))
         * (p_yr ** (-1.0 / 3.0)))
    return k / math.sqrt(max(1.0 - e * e, 1e-6))


def rv_curve(body, n: int = 480, sin_i: float = 1.0, omega_deg: float = 0.0):
    """视向速度曲线：返回 (t_days, rv_m_s, info)。t 以近心点（M=0）为原点。

    RV = K·[cos(ν + ω) + e·cos ω]。系外行星近心点幅角 ω 多未收录，
    默认取可复现假设值 ω=0；e≈0 时曲线退化为正弦（与 ω 无关）。
    """
    K = rv_semi_amplitude_m_s(body, sin_i)
    P = body.period
    if K is None or not P:
        return None, None, None
    e = getattr(body, "e", None) or 0.0
    w = omega_deg * math.pi / 180.0
    t = np.linspace(0.0, P, n)
    M = 2.0 * math.pi * t / P
    rv = np.empty_like(t)
    for i, Mi in enumerate(M):
        E = solve_kepler(float(Mi), e)
        nu = 2.0 * math.atan2(math.sqrt(1.0 + e) * math.sin(E / 2.0),
                              math.sqrt(1.0 - e) * math.cos(E / 2.0))
        rv[i] = K * (math.cos(nu + w) + e * math.cos(w))
    info = {"K": K, "e": e, "sin_i": sin_i, "omega_deg": omega_deg}
    return t, rv, info


# ---------- 宜居带 ----------
def _seff(key: str, teff: float) -> float:
    s0, a, b, c, d = HZ_COEFFS[key]
    T = teff - 5780.0
    return s0 + a * T + b * T ** 2 + c * T ** 3 + d * T ** 4


def habitable_zone_au(body):
    """宜居带边界（AU）：{边界名: 距离}。缺光度或温度返回 None。"""
    L = star_luminosity_solar(body)
    teff = star_teff(body)
    if not L or not teff:
        return None
    out = {}
    for key in HZ_COEFFS:
        s = _seff(key, teff)
        if s > 0:
            out[key] = math.sqrt(L / s)
    return out or None


def habitable_zone_bands(body):
    """宜居带的两条区间（AU）：(保守内, 保守外, 乐观内, 乐观外)"""
    hz = habitable_zone_au(body)
    if not hz:
        return None
    cons = (hz.get("runaway_greenhouse"), hz.get("max_greenhouse"))
    opt = (hz.get("recent_venus"), hz.get("early_mars"))
    if None in cons or None in opt:
        return None
    return cons[0], cons[1], opt[0], opt[1]


def insolation_earth(body):
    """行星接收到的恒星光通量（地球=1）：S = L / a²"""
    L = star_luminosity_solar(body)
    a = getattr(body, "a_au", None)
    if not L or not a:
        return None
    return L / (a * a)


def hz_status(body) -> str:
    """行星相对宜居带的位置描述"""
    bands = habitable_zone_bands(body)
    a = getattr(body, "a_au", None)
    if not bands or not a:
        return "未知"
    ci, co, oi, oo = bands
    if ci <= a <= co:
        return "位于保守宜居带内"
    if oi <= a <= oo:
        return "位于乐观宜居带内（保守带之外）"
    if a < oi:
        return "过于靠近恒星（乐观带内侧）"
    return "过于远离恒星（乐观带外侧）"


# ---------- 汇总（供 UI 参数表） ----------
def is_exoplanet(body) -> bool:
    return getattr(body, "body_type", "") == "planet_exo"


def observation_rows(body) -> list:
    """观测特征参数表：[(标签, 数值文本)]，缺数据一律「未知」"""
    rows = []

    def _num(v, fmt, unit=""):
        return fmt.format(v) + unit if v is not None else "未知"

    # —— 凌星 ——
    p = radius_ratio(body)
    depth = transit_depth_ppm(body)
    rng = transit_duration_range_hours(body)
    if p and is_exoplanet(body):
        rows.append(("凌星深度 (Rp/Rs)²", f"{depth:,.0f} ppm（{depth / 1e4:.4f} %）"))
        a_rs = a_in_stellar_radii(body)
        rows.append(("a/Rs", _num(a_rs, "{:.2f}")))
        if rng:
            rows.append(("凌星时长区间", f"{rng[0]:.2f} ~ {rng[1]:.2f} 小时"
                         f"（擦边凌 ~ 中心凌；撞击参数 b 未测定）"))
    else:
        rows.append(("凌星深度", "未知（缺行星半径或恒星半径）"
                     if not is_exoplanet(body) else "未知"))

    # —— 视向速度 ——
    if is_exoplanet(body):
        k = rv_semi_amplitude_m_s(body)
        if k is not None:
            rows.append(("视向速度半振幅 K", f"{k:.2f} m/s（取 sin i = 1，为最小值）"))
        else:
            rows.append(("视向速度半振幅 K", "未知（缺行星质量或周期）"))

    # —— 宜居带与光照 ——
    ins = insolation_earth(body)
    rows.append(("恒星光通量（地球=1）", _num(ins, "{:.3g}")))
    bands = habitable_zone_bands(body)
    if bands:
        ci, co, oi, oo = bands
        rows.append(("保守宜居带", f"{ci:.3f} ~ {co:.3f} AU"))
        rows.append(("乐观宜居带", f"{oi:.3f} ~ {oo:.3f} AU"))
    elif habitable_zone_au(body):
        rows.append(("宜居带", "恒星温度超出模型适用区间（2600–7200 K），不予给出"))
    else:
        rows.append(("宜居带", "未知（缺恒星光度或有效温度）"))
    rows.append(("宜居性判定", hz_status(body)))

    # —— 平衡温度 ——
    teq = getattr(body, "eq_temp", None)
    if teq:
        rows.append(("平衡温度 Teq", f"{teq:.0f} K"))
    return rows