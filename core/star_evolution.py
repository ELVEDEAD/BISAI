# -*- coding: utf-8 -*-
"""star_evolution.py —— 通用恒星演化模型（按质量，演示级）

系外行星系统宿主恒星的演化：主序 → 红巨星分支（RGB）→ AGB → 白矮星。
时间推进量对全部恒星一致（仿真时钟推进 Δt，所有恒星同步老化 Δt），
各自出生时间不同由观测年龄（st_age）区分。

标度关系（恒星物理教科书级近似，锚点对齐太阳演化模型）：
- 主序寿命   t_MS  ≈ 10.0 × M^-2.5 Gyr            （M=1 → 10 Gyr）
- RGB 时长   t_RGB ≈ clip(1.0 × M^-1.0, 0.15, 1.2)
- RGB tip 半径 R_tip = 256 × M^0.2 R☉               （M=1 → 256 R☉，
             与 Schröder & Connon Smith 2008 太阳锚点一致）
- AGB tip 半径      = 1.15 × R_tip
- 白矮星终质量 M_WD = 0.077 × M + 0.48 M☉           （初始-终质量关系，
             M=1 → 0.557 ≈ S&C 2008 的 0.546 M☉）
- 白矮星半径 R_WD   = 0.0128 × M_WD^(-1/3) R☉       （碳氧 WD 质量半径关系）

适用质量范围 0.5 ≤ M ≤ 8 M☉（更大质量需超新星模型，超出演示范围，
调用方应过滤）。演示级精度：用于视觉演示与吞噬判定，非逐项恒星演化积分。
"""
import numpy as np

T_SUN_K = 5772.0          # 太阳有效温度（K）

# 演化阶段码（与 sun_evolution.SunState.phase 文本对应）
PHASE_MS, PHASE_RGB, PHASE_AGB, PHASE_WD = 0, 1, 2, 3
_PHASE_NAMES = {PHASE_MS: "主序", PHASE_RGB: "红巨星分支",
                PHASE_AGB: "AGB", PHASE_WD: "白矮星"}


def main_sequence_lifetime_gyr(m_solar):
    """主序寿命：t_MS ≈ 10 × M^-2.5 Gyr"""
    return 10.0 * m_solar ** -2.5


def rgb_duration_gyr(m_solar):
    """RGB 阶段时长（Gyr）：2.5 × M^-1，钳制 [0.3, 2.5]。

    M=1 → 2.5 Gyr：主序末端 10 Gyr + RGB 2.5 = tip 12.5 Gyr，
    与太阳演化模型（S&C 2008：主序末 9.63 → RGB tip 12.18）对齐。
    标量与 numpy 数组均可用（star_state / star_state_vec 共用）。
    """
    return np.clip(2.5 * m_solar ** -1.0, 0.3, 2.5)


def rgb_tip_radius_solar(m_solar):
    """RGB tip 光球半径（R☉）：256 × M^0.2（M=1 锚点 = S&C 2008 太阳）"""
    return 256.0 * m_solar ** 0.2


def wd_mass_solar(m_solar):
    """白矮星终质量（M☉）：初始-终质量关系 0.077M + 0.48"""
    return 0.077 * m_solar + 0.48


def wd_radius_solar(m_wd):
    """白矮星半径（R☉）：碳氧 WD 质量半径关系 0.0128 × M_WD^(-1/3)"""
    return 0.0128 * m_wd ** (-1.0 / 3.0)


def phase_name(code):
    return _PHASE_NAMES.get(int(code), "未知")


def _luminosity(r_solar, teff_k):
    """光度（L☉）：L = R² (T/T☉)⁴"""
    return (r_solar ** 2) * (teff_k / T_SUN_K) ** 4


def star_state(m_solar, age_gyr, r0_solar=1.0, teff0_k=T_SUN_K):
    """单颗恒星演化状态（标量版，与 star_state_vec 逻辑一致）。

    返回 (radius_solar, teff_k, luminosity_solar, mass_solar, phase_code)。
    主序期返回观测值（r0/teff0）；演化期按标度关系插值。
    """
    m = float(m_solar)
    t_ms = main_sequence_lifetime_gyr(m)
    t_rgb = rgb_duration_gyr(m)
    t_agb = 0.2
    if age_gyr < t_ms:                                   # 主序
        return (float(r0_solar), float(teff0_k),
                _luminosity(r0_solar, teff0_k), m, PHASE_MS)
    if age_gyr < t_ms + t_rgb:                           # RGB：加速膨胀
        x = (age_gyr - t_ms) / t_rgb
        r_tip = rgb_tip_radius_solar(m)
        r = r0_solar + (r_tip - r0_solar) * x * x
        t = teff0_k + (3500.0 - teff0_k) * x ** 0.5
        frac = (age_gyr - t_ms) / (t_rgb + t_agb)
        mm = m - (m - wd_mass_solar(m)) * min(frac, 1.0)
        return (r, t, _luminosity(r, t), mm, PHASE_RGB)
    if age_gyr < t_ms + t_rgb + t_agb:                   # AGB：脉冲膨胀后收缩
        y = (age_gyr - t_ms - t_rgb) / t_agb
        r_tip = rgb_tip_radius_solar(m)
        r = r_tip * (1.0 + 0.15 * np.sin(np.pi * min(y, 1.0)))
        t = 3200.0
        frac = (age_gyr - t_ms) / (t_rgb + t_agb)
        mm = m - (m - wd_mass_solar(m)) * min(frac, 1.0)
        return (float(r), t, _luminosity(r, t), mm, PHASE_AGB)
    age_wd = age_gyr - (t_ms + t_rgb + t_agb)            # 白矮星冷却
    m_wd = wd_mass_solar(m)
    r_wd = wd_radius_solar(m_wd)
    t_wd = max(4000.0, 40000.0 * (1.0 + age_wd) ** -0.4)
    return (r_wd, t_wd, _luminosity(r_wd, t_wd), m_wd, PHASE_WD)


def star_state_vec(m_solar, age_gyr, r0_solar, teff0_k):
    """向量化版 star_state（逻辑一致，供 viewport 批量计算）。

    入参均为等长 numpy 数组；返回
    (radius_solar, teff_k, luminosity_solar, mass_solar, phase_code)。
    """
    m = np.asarray(m_solar, dtype=np.float64)
    age = np.asarray(age_gyr, dtype=np.float64)
    r0 = np.asarray(r0_solar, dtype=np.float64)
    t0 = np.asarray(teff0_k, dtype=np.float64)

    t_ms = 10.0 * m ** -2.5
    t_rgb = rgb_duration_gyr(m)
    t_agb = 0.2
    m_wd = 0.077 * m + 0.48
    r_tip = 256.0 * m ** 0.2

    phase = np.full(len(m), PHASE_MS, dtype=np.int64)
    r = r0.copy()
    t = t0.copy()
    mm = m.copy()

    rgb = (age >= t_ms) & (age < t_ms + t_rgb)
    if np.any(rgb):
        x = np.clip((age[rgb] - t_ms[rgb]) / t_rgb[rgb], 0.0, 1.0)
        r[rgb] = r0[rgb] + (r_tip[rgb] - r0[rgb]) * x * x
        t[rgb] = t0[rgb] + (3500.0 - t0[rgb]) * np.sqrt(x)
        frac = np.clip((age[rgb] - t_ms[rgb]) / (t_rgb[rgb] + t_agb), 0.0, 1.0)
        mm[rgb] = m[rgb] - (m[rgb] - m_wd[rgb]) * frac
        phase[rgb] = PHASE_RGB

    agb = (age >= t_ms + t_rgb) & (age < t_ms + t_rgb + t_agb)
    if np.any(agb):
        y = np.clip((age[agb] - t_ms[agb] - t_rgb[agb]) / t_agb, 0.0, 1.0)
        r[agb] = r_tip[agb] * (1.0 + 0.15 * np.sin(np.pi * y))
        t[agb] = 3200.0
        frac = np.clip((age[agb] - t_ms[agb]) / (t_rgb[agb] + t_agb), 0.0, 1.0)
        mm[agb] = m[agb] - (m[agb] - m_wd[agb]) * frac
        phase[agb] = PHASE_AGB

    wd = age >= t_ms + t_rgb + t_agb
    if np.any(wd):
        age_wd = age[wd] - (t_ms[wd] + t_rgb[wd] + t_agb)
        r[wd] = 0.0128 * m_wd[wd] ** (-1.0 / 3.0)
        t[wd] = np.maximum(4000.0, 40000.0 * (1.0 + age_wd) ** -0.4)
        mm[wd] = m_wd[wd]
        phase[wd] = PHASE_WD

    lum = (r ** 2) * (t / T_SUN_K) ** 4
    return r, t, lum, mm, phase