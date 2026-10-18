"""test_deep_future_positions.py —— 亿年尺度行星位置（JPL 漂移项钳制）

2026-10-18 教训：position_at_jd 把 JPL 根数世纪变率（a_dot 等）线性外推到
T≈7.9e7 世纪 → 木星 a = -9188 AU（负半长轴）、土星 e≈-1.5 万，行星本体
被甩到数千 AU 外，水星推到 30 AU 导致无人被吞噬。修复：几何漂移钳到
JPL 有效期（±2.5 世纪），仅平黄经 L 用真实时间。
"""
import numpy as np
import pytest

from core.constants import J2000_JD
from core.sun_evolution import (SUN_NOW_AGE_GYR, EARTH_FATE, jd_from_age,
                                sun_state, orbit_expansion)
from data.loader import load_solar_system


@pytest.fixture(scope="module")
def bodies():
    return {b.name: b for b in load_solar_system()}


def _dist(b, jd):
    return float(np.linalg.norm(b.position_at_jd(jd)))


def test_jupiter_not_flung_in_deep_future(bodies):
    """白矮星期（12.5 Gyr）：木星 ≈ 5.2×1.83 ≈ 9.5 AU，而非数千 AU"""
    jd = jd_from_age(12.5)
    d = _dist(bodies["木星"], jd)
    ref = 5.2026 * orbit_expansion(0.546)      # k=1.0
    assert abs(d - ref) < 0.6                  # 相位无关，半径即轨道大小


def test_all_planets_within_reasonable_orbits(bodies):
    """RGB tip（12.18 Gyr）：全部行星日心距 < 100 AU（修复前木星 ≈ 9200 AU）"""
    jd = jd_from_age(12.18)
    for name in ("水星", "金星", "地球", "火星", "木星", "土星", "天王星", "海王星"):
        d = _dist(bodies[name], jd)
        assert d < 100.0, f"{name} 距离 {d:.1f} AU 异常"


def test_mercury_venus_engulfed_at_rgb_tip(bodies):
    """RGB tip：太阳半径 ≈1.19 AU，水星（0.46）金星（0.85）必在光球内"""
    jd = jd_from_age(12.18)
    sun_r = sun_state(12.18).radius_au
    assert sun_r > 1.15
    assert _dist(bodies["水星"], jd) < sun_r
    assert _dist(bodies["金星"], jd) < sun_r


def test_earth_escape_grazes_rgb_tip(bodies):
    """地球 escape 模式（默认）：外移到 ≈1.22 AU，贴边掠过 R≈1.19 AU 光球"""
    assert EARTH_FATE == "escape"
    jd = jd_from_age(12.18)
    d = _dist(bodies["地球"], jd)
    sun_r = sun_state(12.18).radius_au
    ref = 1.0000 * orbit_expansion(0.848, "地球")   # k=1.2
    assert abs(d - ref) < 0.05
    assert d > sun_r * 0.98                       # 不被吞（贴边掠过）


def test_outer_planets_survive(bodies):
    """AGB 之后（12.5 Gyr）：火星及以外全部幸存在光球外（白矮星极小）"""
    jd = jd_from_age(12.5)
    for name in ("火星", "木星", "土星", "天王星", "海王星"):
        assert _dist(bodies[name], jd) > 1.0


def test_present_day_unchanged(bodies):
    """回归锚点：现在（|T|<2.5 世纪）位置与原实现完全一致（T_drift=T）"""
    jd = J2000_JD + 36525.0 * 2.0    # 2200 年（T=2，未钳制区间）
    for name in ("水星", "地球", "木星"):
        b = bodies[name]
        el = b.elements
        # 原实现：所有根数用真实 T
        from core.kepler import position_at_time
        old = position_at_time(el.a + el.a_dot * 2.0, 0.0, el.e, el.e_dot,
                               el.i, el.i_dot, el.L, el.L_dot,
                               el.varpi, el.varpi_dot, el.Omega, el.Omega_dot, 2.0)
        new = b.position_at_jd(jd)
        assert np.allclose(old, new, atol=1e-12)