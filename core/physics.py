"""
physics.py —— 物理约束公式（统一单位：km / s / kg / AU）

标准天体力学公式，来源：IAU 2015 决议、NASA JPL 定义。
用途：
    * 轨道 / 环系 / 卫星的物理合理性校验（洛希极限、希尔球、同步轨道）
    * 详情面板展示由质量与半径推算的物理量（表面重力、逃逸速度、轨道速度）

公式一览：
    开普勒第三定律      T = 2π √(a³/μ)
    圆轨道速度          v = √(μ/a)
    活力公式（任意点）  v = √(μ(2/r − 1/a))
    表面重力加速度      g = μ/R²
    逃逸速度            v_esc = √(2μ/R)
    希尔球半径          r_H = a (m / 3M)^(1/3)
    洛希极限（刚体）    d = R_M (2ρ_M/ρ_m)^(1/3)
    同步轨道半径        r_sync = (μ (T/2π)²)^(1/3)
    平均密度            ρ = 3M / (4πR³)
"""
import math

from core.constants import G_SI, M_EARTH_KG, M_SUN_KG

G_KM = G_SI * 1e-9          # km³ kg⁻¹ s⁻²
SEC_PER_DAY = 86400.0


# ---------- 引力参数 μ = GM ----------
def mu_from_kg(mass_kg: float) -> float:
    """引力参数 μ = GM（km³/s²），质量单位 kg"""
    return G_KM * mass_kg


def mu_earth(mass_earth: float) -> float:
    """引力参数 μ（km³/s²），质量以地球质量为单位"""
    return G_KM * mass_earth * M_EARTH_KG


def mu_solar(mass_solar: float) -> float:
    """引力参数 μ（km³/s²），质量以太阳质量为单位"""
    return G_KM * mass_solar * M_SUN_KG


# ---------- 轨道 ----------
def kepler_period_days(a_km: float, mu: float) -> float:
    """开普勒第三定律：轨道周期（天）"""
    return 2.0 * math.pi * math.sqrt(a_km ** 3 / mu) / SEC_PER_DAY


def circular_velocity_kms(a_km: float, mu: float) -> float:
    """圆轨道速度（km/s）：v = √(μ/a)"""
    return math.sqrt(mu / a_km)


def vis_viva_kms(a_km: float, r_km: float, mu: float) -> float:
    """活力公式：任意轨道位置的速度（km/s）：v = √(μ(2/r − 1/a))"""
    return math.sqrt(max(mu * (2.0 / r_km - 1.0 / a_km), 0.0))


def semi_major_from_period_km(period_days: float, mu: float) -> float:
    """由周期反推半长轴（km）：a = (μ (T/2π)²)^(1/3)"""
    t = period_days * SEC_PER_DAY
    return (mu * (t / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)


# ---------- 天体表面 ----------
def surface_gravity_ms2(radius_km: float, mass_earth: float) -> float:
    """表面重力加速度（m/s²）：g = GM/R²"""
    r_m = radius_km * 1000.0
    return G_SI * mass_earth * M_EARTH_KG / (r_m * r_m)


def escape_velocity_kms(radius_km: float, mass_earth: float) -> float:
    """逃逸速度（km/s）：v_esc = √(2GM/R)"""
    return math.sqrt(2.0 * G_KM * mass_earth * M_EARTH_KG / radius_km)


def mean_density_gcm3(radius_km: float, mass_earth: float) -> float:
    """平均密度（g/cm³）：ρ = 3M/(4πR³)"""
    r_cm = radius_km * 1e5
    m_g = mass_earth * M_EARTH_KG * 1000.0
    return 3.0 * m_g / (4.0 * math.pi * r_cm ** 3)


# ---------- 约束边界 ----------
def hill_sphere_km(a_km: float, mass_body: float, mass_primary: float) -> float:
    """希尔球半径（km）：r_H = a (m/3M)^(1/3)

    母天体引力主导区的边界；卫星轨道半长轴应小于该值。
    质量比无量纲，故 mass_body / mass_primary 可同单位（地球质量或 kg）。
    """
    return a_km * (mass_body / (3.0 * mass_primary)) ** (1.0 / 3.0)


def roche_limit_km(radius_primary_km: float, rho_primary: float,
                   rho_satellite: float) -> float:
    """洛希极限（刚体近似，km）：d = R_M (2ρ_M/ρ_m)^(1/3)

    卫星/环粒进入该半径内会被潮汐力瓦解；行星环外缘一般位于洛希极限内。
    """
    return radius_primary_km * (2.0 * rho_primary / rho_satellite) ** (1.0 / 3.0)


def roche_limit_fluid_km(radius_primary_km: float, rho_primary: float,
                         rho_satellite: float) -> float:
    """洛希极限（流体近似，km）：d = 2.44 R_M (ρ_M/ρ_m)^(1/3)

    适用于可自由变形的流体/松散碎石天体（真实行星环多以此为准）。
    """
    return 2.44 * radius_primary_km * (rho_primary / rho_satellite) ** (1.0 / 3.0)


def synchronous_radius_km(mu: float, period_days: float) -> float:
    """同步轨道半径（km）：r = (μ (T/2π)²)^(1/3)

    轨道周期等于母天体自转周期时的轨道半径（如地球静止轨道）。
    """
    return semi_major_from_period_km(period_days, mu)


# ---------- 地球专用快捷量（μ⊕ = 398600.4418 km³/s²） ----------
MU_EARTH_KM3S2 = 398600.4418
R_EARTH_KM = 6371.0


def earth_orbit_velocity_kms(altitude_km: float) -> float:
    """地球圆轨道速度（km/s），输入轨道高度（地表以上 km）"""
    return circular_velocity_kms(R_EARTH_KM + altitude_km, MU_EARTH_KM3S2)


def earth_orbit_period_days(altitude_km: float) -> float:
    """地球圆轨道周期（天），输入轨道高度（km）"""
    return kepler_period_days(R_EARTH_KM + altitude_km, MU_EARTH_KM3S2)


def earth_altitude_km(a_km: float) -> float:
    """由地心距（km）换算轨道高度（地表以上 km）"""
    return a_km - R_EARTH_KM
