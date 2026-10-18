"""test_sun_evolution.py —— 太阳演化插值表：节点锚点、物理自洽、行星命运"""
import math

import pytest

from core.sun_evolution import (
    SOLAR_RADIUS_AU,
    SUN_NOW_AGE_GYR,
    age_from_jd,
    blackbody_rgb,
    is_engulfed,
    jd_from_age,
    orbit_expansion,
    sun_state,
)


def test_now_state_anchored():
    st = sun_state(SUN_NOW_AGE_GYR)
    assert st.radius_solar == pytest.approx(1.0, abs=1e-9)
    assert st.luminosity_solar == pytest.approx(1.0, rel=1e-6)
    assert st.teff_k == pytest.approx(5778.0)
    assert st.mass_solar == pytest.approx(1.0)
    assert st.phase == "主序"


def test_past_clamped_to_now():
    st = sun_state(0.0)
    assert st.radius_solar == pytest.approx(1.0)
    assert st.phase == "主序"


def test_rgb_tip_schroder_smith():
    """RGB tip：R≈256 R☉≈1.2 AU（S&C 2008）"""
    st = sun_state(12.18)
    assert st.radius_solar == pytest.approx(256.0, rel=1e-6)
    assert st.radius_au == pytest.approx(1.2, abs=0.01)
    assert 2000.0 <= st.luminosity_solar <= 4000.0
    assert st.phase == "红巨星分支"


def test_agb_final_mass():
    st = sun_state(12.38)
    assert st.mass_solar == pytest.approx(0.546, abs=1e-6)
    assert st.phase == "渐近巨星分支"


def test_white_dwarf_earth_size_and_cooling():
    st = sun_state(13.0)
    assert st.phase == "白矮星"
    assert st.radius_solar == pytest.approx(0.013)
    # Mestel 冷却：温度随年龄单调下降
    st_old = sun_state(18.0)
    assert st_old.teff_k < st.teff_k
    assert st_old.luminosity_solar < st.luminosity_solar


def test_luminosity_stefan_boltzmann_consistent():
    """L = R²(T/5778)⁴ 在全表范围内成立（含插值中间点）"""
    for age in (4.6, 6.5, 8.0, 9.63, 10.5, 11.5, 12.0, 12.25, 12.35, 12.45, 13.5, 15.0):
        st = sun_state(age)
        expect = st.radius_solar ** 2 * (st.teff_k / 5778.0) ** 4
        assert st.luminosity_solar == pytest.approx(expect, rel=1e-9), age


def test_main_sequence_luminosity_growth():
    """主序段：每 ~1.1 Gyr 光度约 +10%（标准太阳演化近似）"""
    l0 = sun_state(4.58).luminosity_solar
    l1 = sun_state(5.7).luminosity_solar
    assert 1.05 <= l1 / l0 <= 1.25


def test_monotonic_radius_through_rgb():
    """RGB 上升段半径单调膨胀"""
    prev = 0.0
    for age in [9.7 + 0.25 * i for i in range(10)]:
        r = sun_state(age).radius_solar
        assert r >= prev
        prev = r


def test_age_jd_roundtrip():
    for age in (4.58, 6.0, 12.18, 13.0, 20.0):
        assert age_from_jd(jd_from_age(age)) == pytest.approx(age, abs=1e-6)


def test_blackbody_rgb_colors():
    warm = blackbody_rgb(2700.0)   # 红巨星：偏红
    white = blackbody_rgb(5778.0)  # 现在：近白
    hot = blackbody_rgb(90000.0)   # 年轻白矮星：钳制深蓝
    assert warm[0] > warm[2]
    assert abs(white[0] - white[2]) < 0.35
    assert hot[2] > hot[0]
    for rgb in (warm, white, hot):
        assert all(0.0 <= c <= 1.0 for c in rgb)


def test_orbit_expansion_engulf_vs_escape():
    """地球两种命运：escape 在 RGB tip 贴边掠过；engulf 被吞噬"""
    import core.sun_evolution as se
    m_tip = 0.848   # RGB tip 太阳质量
    r_tip_au = sun_state(12.18).radius_au
    se.EARTH_FATE = "engulf"
    a_eng = 1.0 * orbit_expansion(m_tip, "地球")
    se.EARTH_FATE = "escape"
    a_esc = 1.0 * orbit_expansion(m_tip, "地球")
    assert a_esc > r_tip_au              # 逃逸模式：贴边掠过
    assert is_engulfed(r_tip_au, a_eng)  # 吞噬模式：坠入光球


def test_mercury_venus_doomed_both_modes():
    """水星金星在两种模式下都必然被吞噬（RGB tip R≈1.2 AU）"""
    import core.sun_evolution as se
    r_tip_au = sun_state(12.18).radius_au
    for a0 in (0.387, 0.723):  # 水星、金星
        for fate in ("escape", "engulf"):
            se.EARTH_FATE = fate
            a = a0 * orbit_expansion(0.848, "")
            assert is_engulfed(r_tip_au, a), (a0, fate)
    se.EARTH_FATE = "escape"


def test_outer_planets_survive():
    """火星及外行星轨道外移幸存"""
    r_tip_au = sun_state(12.18).radius_au
    for a0 in (1.524, 5.2, 9.58, 19.2, 30.05):
        a = a0 * orbit_expansion(0.848, "")
        assert not is_engulfed(r_tip_au, a)


def test_mass_loss_expands_outer_orbits():
    """AGB 后（M=0.546）外行星轨道显著外移（角动量守恒）"""
    exp = orbit_expansion(0.546, "木星")
    assert exp == pytest.approx(1.0 / 0.546, rel=1e-9)