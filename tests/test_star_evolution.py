# -*- coding: utf-8 -*-
"""test_star_evolution.py —— 通用恒星演化模型锚点测试

锚点对齐 sun_evolution（太阳 Schröder & Connon Smith 2008）：
M=1 → RGB tip 256 R☉ / 主序寿命 10 Gyr / 终质量 ≈0.546 M☉。
"""
import numpy as np
import pytest

from core.star_evolution import (
    PHASE_AGB, PHASE_MS, PHASE_RGB, PHASE_WD,
    main_sequence_lifetime_gyr, phase_name, rgb_duration_gyr,
    rgb_tip_radius_solar, star_state, star_state_vec, wd_mass_solar,
    wd_radius_solar)


def test_ms_lifetime_anchor():
    """M=1 主序寿命 10 Gyr；大质量星更短"""
    assert main_sequence_lifetime_gyr(1.0) == pytest.approx(10.0)
    assert main_sequence_lifetime_gyr(2.0) < main_sequence_lifetime_gyr(1.0)
    assert main_sequence_lifetime_gyr(0.8) > 10.0


def test_rgb_tip_anchor():
    """M=1 RGB tip = 256 R☉（S&C 2008 太阳锚点）"""
    assert rgb_tip_radius_solar(1.0) == pytest.approx(256.0)
    assert rgb_tip_radius_solar(5.0) > rgb_tip_radius_solar(1.0)


def test_wd_mass_anchor():
    """M=1 终质量 0.557 ≈ S&C 2008 的 0.546 M☉；白矮星半径地球量级"""
    assert wd_mass_solar(1.0) == pytest.approx(0.557, abs=0.01)
    r_wd = wd_radius_solar(wd_mass_solar(1.0))
    assert 0.008 < r_wd < 0.03          # ≈ 地球大小（0.0092 R☉）量级
    assert wd_mass_solar(8.0) < 1.38    # 不超碳氧 WD 钱德拉塞卡极限


def test_star_state_phases():
    """单颗恒星：主序 → RGB → AGB → WD，半径先膨胀后骤缩"""
    r, t, lum, m, ph = star_state(1.0, 5.0)
    assert ph == PHASE_MS and r == 1.0 and m == 1.0
    r, t, lum, m, ph = star_state(1.0, 10.4)
    assert ph == PHASE_RGB
    assert r > 1.0 and r < 256.0        # 膨胀途中
    assert t < 5772.0                    # 变红
    r_tip_end, _, _, m2, ph2 = star_state(1.0, 10.0 + rgb_duration_gyr(1.0) - 1e-9)
    assert ph2 == PHASE_RGB
    assert r_tip_end == pytest.approx(256.0, rel=1e-6)
    r, t, lum, m, ph = star_state(1.0, 10.0 + rgb_duration_gyr(1.0) + 0.1)
    assert ph == PHASE_AGB and r > 256.0  # AGB 脉冲超过 RGB tip
    r, t, lum, m, ph = star_state(1.0, 13.0)
    assert ph == PHASE_WD
    assert r < 0.05 and m == pytest.approx(0.557, abs=0.01)
    assert lum < 0.5                     # 白矮星远暗于主序太阳（热 WD ~0.1 L☉）


def test_more_massive_evolves_earlier():
    """1.5 M☉ 恒星比太阳更早进入红巨星（主序寿命 5.4 Gyr）"""
    t15 = main_sequence_lifetime_gyr(1.5)
    assert t15 == pytest.approx(3.63, abs=0.05)
    _, _, _, _, ph_4 = star_state(1.5, 4.0)
    _, _, _, _, ph_4_sun = star_state(1.0, 4.0)
    assert ph_4 == PHASE_RGB            # 已红巨星（3.63 < 4.0 < 4.3）
    assert ph_4_sun == PHASE_MS         # 太阳仍主序


def test_vec_matches_scalar():
    """向量化与标量逐点一致（随机质量/年龄/初始参数）"""
    rng = np.random.default_rng(42)
    m = rng.uniform(0.5, 8.0, 200)
    age = rng.uniform(0.0, 16.0, 200)
    r0 = rng.uniform(0.2, 3.0, 200)
    t0 = rng.uniform(3000.0, 7000.0, 200)
    rv, tv, lv, mv, pv = star_state_vec(m, age, r0, t0)
    for k in range(len(m)):
        rs, ts, ls, ms, ps = star_state(m[k], age[k], r0[k], t0[k])
        assert rv[k] == pytest.approx(rs, abs=1e-9)
        assert tv[k] == pytest.approx(ts, abs=1e-9)
        assert lv[k] == pytest.approx(ls, rel=1e-9)
        assert mv[k] == pytest.approx(ms, abs=1e-9)
        assert pv[k] == ps


def test_engulfment_scale():
    """吞噬判定量级：1 M☉ 恒星 RGB tip 1.19 AU —— 可吞 0.05 AU 热木星，
    不可吞 5 AU 行星；5 M☉ 恒星 RGB tip ≈ 1.6 AU"""
    r_au_1ms = rgb_tip_radius_solar(1.0) * 695700.0 / 1.496e8
    assert r_au_1ms == pytest.approx(1.19, abs=0.01)
    r_au_5ms = rgb_tip_radius_solar(5.0) * 695700.0 / 1.496e8
    assert 1.4 < r_au_5ms < 2.0


def test_phase_name():
    assert phase_name(PHASE_MS) == "主序"
    assert phase_name(PHASE_WD) == "白矮星"