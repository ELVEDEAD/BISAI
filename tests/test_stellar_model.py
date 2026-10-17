"""test_stellar_model.py —— 恒星与大气模型测试（对解析公式做交叉验证）"""
import numpy as np
import pytest

from core.constants import R_SUN_KM, R_EARTH_KM
from core.stellar_model import (
    equilibrium_temperature, limb_darkened_intensity,
    luminosity_from_radius_temp, main_sequence_lifetime_gyr,
    main_sequence_luminosity, main_sequence_radius, mass_from_luminosity,
    occultation_depth_blackbody, planck_b_lambda, scale_height_m,
    spectral_class, stefan_boltzmann_flux, transit_depth_limb_darkened,
    transit_flux_curve_limb_darkened, transmission_depth, wien_peak_nm)

SUN_TEFF = 5772.0


# ---------- 黑体辐射 ----------
def test_wien_peak_solar():
    # 2.897771955e6 nm·K / 5772 K ≈ 501.7 nm（可见光绿段）
    assert wien_peak_nm(SUN_TEFF) == pytest.approx(501.7, abs=1.0)


def test_planck_peak_matches_wien_displacement():
    lam = np.linspace(100.0, 3000.0, 20000)
    b = planck_b_lambda(lam, 4000.0)
    assert lam[np.argmax(b)] == pytest.approx(wien_peak_nm(4000.0), abs=1.0)


def test_stefan_boltzmann_flux_value():
    # σ·(5772 K)⁴ ≈ 6.29e7 W/m²
    assert stefan_boltzmann_flux(SUN_TEFF) == pytest.approx(6.293e7, rel=2e-3)


def test_planck_extreme_frequency_no_overflow():
    # 极冷/极短波 → exp 溢出防护，返回 0 而非 inf
    assert planck_b_lambda(1.0, 3.0) == 0.0
    assert np.isfinite(planck_b_lambda(np.array([500.0, 1000.0]), 100.0)).all()


# ---------- 恒星结构 ----------
def test_solar_luminosity_from_radius_temp():
    # L(R☉, 5772 K) ≈ 1 L☉（IAU 名义太阳值自洽）
    assert luminosity_from_radius_temp(R_SUN_KM, SUN_TEFF) == \
        pytest.approx(1.0, rel=5e-3)


@pytest.mark.parametrize("m", [0.3, 0.5, 1.0, 2.5, 5.0, 20.0])
def test_main_sequence_mass_luminosity_roundtrip(m):
    L = main_sequence_luminosity(m)
    assert mass_from_luminosity(L) == pytest.approx(m, rel=1e-6)


def test_main_sequence_relations_monotonic_and_solar():
    assert main_sequence_luminosity(1.0) == pytest.approx(1.0)
    ms = [main_sequence_luminosity(m) for m in (0.5, 1.0, 2.0, 10.0)]
    assert all(a < b for a, b in zip(ms, ms[1:]))
    assert main_sequence_radius(1.0) == pytest.approx(1.0)
    assert main_sequence_radius(4.0) > main_sequence_radius(2.0)
    assert mass_from_luminosity(2e6) is None          # 超 55 M☉ 端
    assert main_sequence_lifetime_gyr(1.0) == pytest.approx(10.0)
    assert main_sequence_lifetime_gyr(4.0) < 2.0      # 大质量短寿命


@pytest.mark.parametrize("teff,expected", [
    (35000.0, "O"), (15000.0, "B"), (8500.0, "A"),
    (6800.0, "F"), (5772.0, "G"), (4500.0, "K"), (2800.0, "M"),
])
def test_spectral_classification(teff, expected):
    assert spectral_class(teff) == expected


# ---------- 临边昏暗 ----------
def test_limb_darkening_intensity_profiles():
    assert limb_darkened_intensity(0.0, 0.3, 0.3) == pytest.approx(1.0)   # 中心
    assert limb_darkened_intensity(1.0, 0.3, 0.3) == \
        pytest.approx(1.0 - 0.3 - 0.3)                                    # 边缘
    assert limb_darkened_intensity(0.5, 0.0, 0.0) == 1.0                  # 无临边昏暗


def test_transit_depth_no_limb_darkening_is_geometric():
    p = 0.1
    assert transit_depth_limb_darkened(p, b=0.0, u1=0.0, u2=0.0) == \
        pytest.approx(p * p, rel=5e-3)
    # 掠凌（行星在盘外）：零深度
    assert transit_depth_limb_darkened(p, b=1.0 + p + 0.05, u1=0.3, u2=0.3) == 0.0


def test_transit_depth_limb_darkening_deepens_center():
    p, u1, u2 = 0.1, 0.4, 0.3
    d_center = transit_depth_limb_darkened(p, 0.0, u1, u2)
    d_edge = transit_depth_limb_darkened(p, 0.95, u1, u2)
    # 中心凌比几何深度更深（遮挡亮中心），边缘凌更浅
    assert d_center > p * p > d_edge
    assert d_center < p * p / (1 - u1 - u2) + 1e-6      # 上界：亮度归一


def test_transit_flux_curve_limb_darkened():
    p = 0.08
    flux = transit_flux_curve_limb_darkened(np.array([0.0, 1.0 + p]), p, 0.3, 0.3)
    assert flux[1] == pytest.approx(1.0)
    assert flux[0] < 1.0


# ---------- 行星大气 ----------
def test_equilibrium_temperature_earth_like():
    # A=0、全球重分布、1 AU 绕 1 L☉：T_eq = [L/(16πσa²)]^1/4 ≈ 278.3 K
    t = equilibrium_temperature(1.0, 1.0, albedo=0.0)
    assert t == pytest.approx(278.3, abs=1.0)
    # 昼面重分布 → ×2^¼（分母 16π→8π）
    assert equilibrium_temperature(1.0, 1.0, albedo=0.0,
                                   redistribution="dayside") == \
        pytest.approx(t * 2 ** 0.25, rel=1e-6)
    # 反照率升高 → 降温
    assert equilibrium_temperature(1.0, 1.0, albedo=0.5) < t
    # 距离减半 → 温度 ×√2
    assert equilibrium_temperature(1.0, 0.5, albedo=0.0) == \
        pytest.approx(t * np.sqrt(2), rel=1e-6)


def test_scale_height_earth_atmosphere():
    # 地球：T=288 K、μ=28.97、g=9.81 → H ≈ 8.4 km
    H = scale_height_m(288.0, 28.97, 9.81)
    assert H == pytest.approx(8350.0, rel=0.02)
    # 温度升高 → 标高增大；g 增大 → 标高减小
    assert scale_height_m(576.0, 28.97, 9.81) > H
    assert scale_height_m(288.0, 28.97, 25.0) < H


def test_transmission_depth_rayleigh_slope_and_lines():
    wave = np.linspace(300.0, 1000.0, 700)
    rp, rs, H = 71_492.0, 696_340.0, 200.0        # ~木星行星 + K 星
    lines = [(589.3, 0.0004, 1.5)]                # Na D
    depth = transmission_depth(wave, rp, rs, H, n_scale_heights=5.0,
                               rayleigh_alpha=-4.0, absorption_lines=lines)
    assert depth.shape == wave.shape
    # 瑞利 α=−4：短波端大气有效半径更大 → 深度更大
    assert depth[0] > depth[-1]
    # Na D 线处深度抬升
    i_na = int(np.argmin(np.abs(wave - 589.3)))
    baseline = (rp / rs) ** 2 + (5 * H * (589.3 / 500.0) ** -4 / rs) ** 2
    assert depth[i_na] > baseline
    # 无大气（H=0、无线）：纯几何深度
    d0 = transmission_depth(wave, rp, rs, 0.0, absorption_lines=[])
    np.testing.assert_allclose(d0, (rp / rs) ** 2)


def test_occultation_depth_blackbody_rayleigh_jeans():
    # 深远红外（3 mm，x = hc/λkT ≈ 0.016 ≪ 1）：δ_sec ≈ (Rp/Rs)²·(Tp/Ts)
    rp, rs = R_EARTH_KM, R_SUN_KM
    tp, ts = 300.0, 5772.0
    d = occultation_depth_blackbody(rp, tp, rs, ts, wave_nm=3_000_000.0)
    assert d == pytest.approx((rp / rs) ** 2 * tp / ts, rel=0.01)
    # 中心波长处的黑体比值
    d_mid = occultation_depth_blackbody(rp, tp, rs, ts, wave_nm=10_000.0)
    ratio = planck_b_lambda(10_000.0, tp) / planck_b_lambda(10_000.0, ts)
    assert d_mid == pytest.approx((rp / rs) ** 2 * ratio, rel=1e-9)