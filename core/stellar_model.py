"""
stellar_model.py —— 恒星与大气物理建模（轨道反演的配套正模型）

覆盖科研中常用的「恒星与大气」解析模型：

* 黑体辐射：普朗克函数 B_λ、维恩位移峰值、斯特藩-玻尔兹曼光度
* 主序星结构：质量-光度 / 质量-半径分段幂律（经验关系）与反演
* 临边昏暗：二次临边昏暗定律 I(μ)/I(1) = 1 − u₁(1−μ) − u₂(1−μ)²，
  及其下的凌星深度（数值圆盘积分，衔接 core/exo_obs.py 的无临边昏暗模型）
* 行星大气：平衡温度、大气标高、透射谱（瑞利散射斜率 + 高斯吸收线）

公式来源（公开教材与经典文献）：
* 普朗克/维恩/斯特藩-玻尔兹曼：SI 2019 精确常数（core/constants.py）
* 主序 M-L 分段幂律：0.23M^2.3 / M^4 / 1.4M^3.5 / 32000M（分段点 0.43/2/55 M☉，
  教材标准近似，精度 ~10–30%，仅适用主序）
* 二次临边昏暗：Claret (2000) 常用形式；太阳可见光典型 u₁≈0.3, u₂≈0.3
* 平衡温度：T_eq = [(1−A)L/(16πσa²·f)]^1/4，f=1 全球重分布、f=1/2 仅昼面
* 大气标高：H = kT/(μm_H·g)；透射谱有效半径 R_eff = Rp + n·H·(λ/λ₀)^α

科学诚实性：
* 主序幂律是粗粒度经验关系，巨星/白矮星不适用（调用方需自行判断）
* 透射谱模型不含真实大气化学平衡，仅做几何+瑞利+单线叠加的演示级建模
"""
import math

import numpy as np

from core.constants import (C_LIGHT_M_S, H_PLANCK_J_S, K_B_J_PER_K, SIGMA_SB,
                            M_HYDROGEN_KG, WIEN_B_NM_K, AU_M, R_SUN_KM,
                            M_SUN_KG)

_L_SUN_W = 3.828e26                  # 太阳光度（W，IAU 2015 名义值）

# 主序 M-L 分段幂律边界（M☉）
_ML_BREAKS = (0.43, 2.0, 55.0)


# ---------- 黑体辐射 ----------
def planck_b_lambda(wave_nm, T: float):
    """普朗克黑体辐射亮度 B_λ（W·m⁻³·sr⁻¹）。

    B_λ = (2hc²/λ⁵) / [exp(hc/λkT) − 1]
    """
    lam = np.asarray(wave_nm, dtype=np.float64) * 1e-9        # nm → m
    a = 2.0 * H_PLANCK_J_S * C_LIGHT_M_S ** 2
    x = H_PLANCK_J_S * C_LIGHT_M_S / (lam * K_B_J_PER_K * T)
    # 大 x 防溢出：exp(x)−1 → exp(x)
    num = np.where(x > 700.0, 0.0, a / lam ** 5)
    out = num / np.expm1(np.clip(x, 0.0, 700.0))
    return float(out) if np.isscalar(wave_nm) else out


def wien_peak_nm(T: float) -> float:
    """维恩位移定律：黑体辐射 B_λ 峰值波长（nm）。λ_max·T = 2.897771955e6 nm·K"""
    return WIEN_B_NM_K / T


def stefan_boltzmann_flux(T: float) -> float:
    """黑体表面辐射通量（W/m²）：F = σT⁴"""
    return SIGMA_SB * T ** 4


# ---------- 恒星结构 ----------
def luminosity_from_radius_temp(radius_km: float, T: float) -> float:
    """恒星半径 + 有效温度 → 光度（L☉）：L = 4πR²σT⁴"""
    r_m = radius_km * 1e3
    return 4.0 * math.pi * r_m ** 2 * stefan_boltzmann_flux(T) / _L_SUN_W


def teff_from_luminosity_radius(lum_solar: float, radius_solar: float) -> float:
    """光度 + 半径 → 有效温度（K）：T = (L·L☉/4πR²σ)^1/4。主序近似配套反演。"""
    if lum_solar <= 0 or radius_solar <= 0:
        return None
    r_m = radius_solar * R_SUN_KM * 1e3
    return (lum_solar * _L_SUN_W / (4.0 * math.pi * r_m ** 2 * SIGMA_SB)) ** 0.25


def main_sequence_luminosity(mass_solar: float) -> float:
    """主序质量-光度分段幂律（L☉）。仅适用主序星，精度 10–30%。"""
    m = float(mass_solar)
    if m <= 0:
        return 0.0
    if m < _ML_BREAKS[0]:
        return 0.23 * m ** 2.3
    if m < _ML_BREAKS[1]:
        return m ** 4.0
    if m < _ML_BREAKS[2]:
        return 1.4 * m ** 3.5
    return 32000.0 * m


def mass_from_luminosity(lum_solar: float) -> float:
    """光度 → 主序质量（M☉）：分段幂律反演。超出适用范围（L>~1e6 L☉）返回 None。"""
    L = float(lum_solar)
    if L <= 0:
        return None
    l0 = 0.23 * _ML_BREAKS[0] ** 2.3          # ≈ 0.036
    l1 = _ML_BREAKS[1] ** 4.0                 # 16
    l2 = 1.4 * _ML_BREAKS[2] ** 3.5           # ≈ 1.05e6
    if L < l0:
        return (L / 0.23) ** (1.0 / 2.3)
    if L < l1:
        return L ** 0.25
    if L < l2:
        return (L / 1.4) ** (1.0 / 3.5)
    return None                                # >55 M☉ 端外推不可靠


def main_sequence_radius(mass_solar: float) -> float:
    """主序质量-半径近似（R☉）：M<1 时 R≈M^0.8，M≥1 时 R≈M^0.57。"""
    m = float(mass_solar)
    if m <= 0:
        return 0.0
    return m ** 0.8 if m < 1.0 else m ** 0.57


def main_sequence_lifetime_gyr(mass_solar: float) -> float:
    """主序寿命（Gyr）：τ ≈ 10·M/L(M)，太阳取 10 Gyr。"""
    m = float(mass_solar)
    if m <= 0:
        return 0.0
    return 10.0 * m / main_sequence_luminosity(m)


_SPECTRAL_CLASSES = [                       # (谱型, 有效温度下界 K)
    ("O", 30000.0), ("B", 10000.0), ("A", 7500.0),
    ("F", 6000.0), ("G", 5200.0), ("K", 3700.0), ("M", 0.0),
]


def spectral_class(teff: float) -> str:
    """有效温度 → MK 谱型（OBAFGKM，粗分类）"""
    t = float(teff)
    for name, tmin in _SPECTRAL_CLASSES:
        if t >= tmin:
            return name
    return "M"


# ---------- 临边昏暗与凌星深度 ----------
def limb_darkened_intensity(r_over_R, u1: float, u2: float):
    """二次临边昏暗相对亮度 I(μ)/I(1)，μ = √(1−r²)，r 为到恒星中心距离/Rs。"""
    mu2 = np.clip(1.0 - np.asarray(r_over_R, dtype=np.float64) ** 2, 0.0, 1.0)
    mu = np.sqrt(mu2)
    return 1.0 - u1 * (1.0 - mu) - u2 * (1.0 - mu) ** 2


def transit_depth_limb_darkened(p: float, b: float, u1: float, u2: float,
                                n_grid: int = 400) -> float:
    """带二次临边昏暗的凌星深度（数值圆盘积分）。

    恒星盘按 n_grid×n_grid 像素采样，亮度按 I(μ(r)) 加权；行星圆盘中心
    距离 b（撞击参数，以 Rs 为单位）处遮挡。u1=u2=0 时退化为几何深度 p²。
    """
    if not 0.0 <= b <= 1.0 + p:
        return 0.0
    axis = np.linspace(-1.0, 1.0, n_grid)
    gx, gy = np.meshgrid(axis, axis)
    star_mask = gx ** 2 + gy ** 2 <= 1.0
    px, py = b, 0.0
    planet_mask = (gx - px) ** 2 + (gy - py) ** 2 < p ** 2
    weights = np.where(star_mask, limb_darkened_intensity(np.hypot(gx, gy), u1, u2), 0.0)
    total = weights.sum()
    if total <= 0:
        return 0.0
    occulted = np.where(planet_mask & star_mask, weights, 0.0).sum()
    return float(occulted / total)


def transit_flux_curve_limb_darkened(z: np.ndarray, p: float, u1: float, u2: float,
                                     n_grid: int = 400) -> np.ndarray:
    """行星中心距序列 z（Rs 单位）→ 相对亮度序列（1 − δ(z)）。"""
    z = np.atleast_1d(np.asarray(z, dtype=np.float64))
    return 1.0 - np.array(
        [transit_depth_limb_darkened(p, float(zz), u1, u2, n_grid) for zz in z])


# ---------- 行星大气 ----------
def scale_height_m(T: float, mean_molecular_weight: float, g_ms2: float) -> float:
    """大气标高（m）：H = kT/(μm_H·g)。μ 以氢原子质量为单位（如 H₂O≈18）。"""
    return K_B_J_PER_K * T / (mean_molecular_weight * M_HYDROGEN_KG * g_ms2)


def equilibrium_temperature(lum_solar: float, a_au: float, albedo: float = 0.3,
                            redistribution: str = "full") -> float:
    """行星平衡温度（K）。

    T_eq = [(1−A)·L / (16πσa²·f)]^(1/4)：
      f = 1（full，全球重分布）；f = 1/2（dayside，仅昼面重分布，T×2^¼）；
      f = 1/4（substellar，副太阳点，T×4^¼）。albedo ∈ [0,1]。
    """
    f = {"full": 1.0, "dayside": 0.5, "substellar": 0.25}.get(redistribution, 1.0)
    a_m = a_au * AU_M
    L = lum_solar * _L_SUN_W
    A = min(max(albedo, 0.0), 1.0)
    return ((1.0 - A) * L / (16.0 * math.pi * SIGMA_SB * a_m ** 2 * f)) ** 0.25


def transmission_depth(wave_nm, radius_km: float, star_radius_km: float,
                       scale_height_km: float, n_scale_heights: float = 5.0,
                       rayleigh_alpha: float = -4.0, ref_wave_nm: float = 500.0,
                       absorption_lines=None):
    """透射谱凌星深度模型：δ(λ) = [R_eff(λ)/Rs]² + Σ 高斯吸收线。

    有效半径 R_eff = Rp + n·H·(λ/λ₀)^α（α=−4 为瑞利散射斜率，α=0 为灰雾霾）；
    absorption_lines = [(中心波长 nm, 深度贡献, 宽度 nm), …]（如 Na I 589.3）。
    返回与 wave_nm 等长的深度数组（无量纲，乘 1e6 得 ppm）。
    """
    lam = np.asarray(wave_nm, dtype=np.float64)
    r_eff = radius_km + n_scale_heights * scale_height_km * \
        (lam / ref_wave_nm) ** rayleigh_alpha
    depth = (r_eff / star_radius_km) ** 2
    for center, amp, width in (absorption_lines or []):
        depth = depth + amp * np.exp(-0.5 * ((lam - center) / width) ** 2)
    return depth


def occultation_depth_blackbody(radius_km: float, T: float, star_radius_km: float,
                                star_teff: float, wave_nm: float) -> float:
    """二次凌（行星被恒星遮掩）热发射深度：δ_sec ≈ (Rp/Rs)²·Bλ(Tp)/Bλ(Ts)。

    凌星深度由几何遮挡决定，二次凌深度由行星热辐射与恒星辐射之比决定
    （观测波段不透明时）。瑞利-金斯区可退化为 (Rp/Rs)²·(Tp/Ts)。
    """
    num = planck_b_lambda(wave_nm, T)
    den = planck_b_lambda(wave_nm, star_teff)
    if den == 0:
        return 0.0
    return (radius_km / star_radius_km) ** 2 * num / den