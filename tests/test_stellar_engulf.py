# -*- coding: utf-8 -*-
"""test_stellar_engulf.py —— 系外宿主恒星演化吞噬（viewport 联动）

伪造 viewport 数组（同 test_sun_evolution_viewport.py 手法）验证
_update_stellar_evolution：演化渲染联动、吞噬判定（瞬时 + 跳转区间）、
主序恢复、事件日志。时间条件复活复用 _engulfed 字典（不在此重复测试）。
"""

from types import SimpleNamespace

import numpy as np

from core.constants import J2000_JD
from core.sun_evolution import SUN_NOW_AGE_GYR, jd_from_age
from core.star_evolution import PHASE_MS, star_state_vec
from scene.viewport import Viewport


def _make_fake(jd, host_mass=1.5, host_age0=3.5, planets=(("b", 0.05, 0.0),)):
    """伪造含 1 颗宿主恒星 + N 颗系外行星的 viewport。

    宿主恒星 1.5 M☉ / age0=3.5 Gyr（主序寿命 3.63 Gyr，快进即红巨星）。
    planets: (名, a_au, e)。
    """
    n_host = len(planets) + 1
    bodies = [SimpleNamespace(name="测试星", body_type="host_star",
                              host=""),
              *[SimpleNamespace(name=f"测试星 {p[0]}", body_type="planet_exo",
                                host="测试星")
                for p in planets]]
    star_idx = np.array([0], dtype=np.int64)
    exo_idx = np.array(range(1, n_host), dtype=np.int64)
    m = len(exo_idx)
    emitted = []
    fake = SimpleNamespace(
        bodies=bodies,
        _body_pos=np.zeros((n_host, 3)),
        _star_evo_idx=star_idx,
        _star_evo_mass=np.array([host_mass]),
        _star_evo_age0=np.array([host_age0]),
        _star_evo_r0=np.array([1.2]),
        _star_evo_teff0=np.array([6700.0]),
        _star_evo_last_jd=None, _star_evo_last_t=0.0,
        _star_evo_applied=False,
        _star_evo_lum_idx=None, _star_evo_lum=None,
        _radius_km=np.array([1.2 * 695700.0] + [70000.0] * m),
        _radius_km0=None,
        _colors_arr=np.tile([1.0, 0.9, 0.8], (n_host, 1)),
        _colors_arr0=None,
        _exo_idx=exo_idx,
        _exo_star_slot=np.zeros(m, dtype=np.int64),
        _exo_a=np.array([p[1] for p in planets], dtype=np.float64),
        _exo_e=np.array([p[2] for p in planets], dtype=np.float64),
        _exo_i=np.zeros(m),
        _exo_period=np.array([365.25 * p[1] ** 1.5 for p in planets]),
        _engulfed={}, evolution_events=[],
        _engulf_dirty=False, follow_body=None,
        clock=SimpleNamespace(jd=jd, speed=1.0),
        engulfChanged=SimpleNamespace(emit=emitted.append),
    )
    fake._radius_km0 = fake._radius_km.copy()
    fake._colors_arr0 = fake._colors_arr.copy()
    fake._log_evolution_event = (
        lambda text: Viewport._log_evolution_event(fake, text))
    fake.emitted = emitted
    return fake


def test_stellar_evolution_renders_and_engulfs():
    """快进 0.5 Gyr：1.5 M☉ 恒星进 RGB 中途 → 半径/颜色已改 + 热木星被吞"""
    jd = jd_from_age(SUN_NOW_AGE_GYR + 0.5)          # Δ=+0.5 Gyr（RGB 中途）
    fake = _make_fake(jd)
    Viewport._update_stellar_evolution(fake, jd)
    # 恒星演化渲染：半径膨胀（>10 R☉）、颜色偏红、emis 数组就位
    assert fake._radius_km[0] > 10.0 * 695700.0
    assert fake._colors_arr[0][0] > fake._colors_arr[0][2]   # R > B
    assert fake._star_evo_lum_idx is not None and len(fake._star_evo_lum_idx)
    # 热木星 0.05 AU 落入膨胀光球 → 被吞 + 事件
    assert 1 in fake._engulfed
    assert "测试星" in fake.evolution_events[0][2]
    assert fake._engulf_dirty


def test_stellar_engulf_jump_over_window():
    """直接跳到恒星白矮星期（越过 RGB 窗口）：行星仍被吞（区间判定）。

    1.5 M☉ 恒星 4.5 Gyr 演化完毕；Δ=+2 Gyr 时已是白矮星，当前光球
    极小——但跳转区间覆盖了 RGB/AGB 期，热木星应仍被吞。
    """
    jd_prev = J2000_JD                                    # 从现在出发
    jd = jd_from_age(SUN_NOW_AGE_GYR + 2.0)               # Δ=+2 Gyr
    fake = _make_fake(jd)
    fake._star_evo_last_jd = jd_prev
    Viewport._update_stellar_evolution(fake, jd)
    assert 1 in fake._engulfed
    assert fake._engulf_dirty


def test_stellar_wide_orbit_survives():
    """远行星（5 AU > AGB tip 1.5 AU）：即使跳转吞不掉"""
    jd = jd_from_age(SUN_NOW_AGE_GYR + 2.0)
    fake = _make_fake(jd, planets=(("c", 5.0, 0.0),))
    fake._star_evo_last_jd = J2000_JD
    Viewport._update_stellar_evolution(fake, jd)
    assert 1 not in fake._engulfed
    # 恒星本身已演化（白矮星期，半径骤缩）
    assert fake._radius_km[0] < 0.1 * 695700.0


def test_stellar_restore_on_main_sequence():
    """跳回现在：半径/颜色恢复原值，吞噬由时间条件复活逻辑处理"""
    jd = jd_from_age(SUN_NOW_AGE_GYR + 1.0)
    fake = _make_fake(jd)
    Viewport._update_stellar_evolution(fake, jd)
    assert fake._star_evo_applied
    # 跳回现在（Δ≈0）
    jd_now = J2000_JD
    fake._star_evo_last_jd = jd_from_age(SUN_NOW_AGE_GYR + 1.0)
    fake._star_evo_last_t = 0.0
    Viewport._update_stellar_evolution(fake, jd_now)
    assert not fake._star_evo_applied
    assert fake._radius_km[0] == fake._radius_km0[0]
    assert (fake._colors_arr[0] == fake._colors_arr0[0]).all()
    assert fake._star_evo_lum_idx is None


def test_stellar_ms_stays_untouched():
    """小质量 M 矮星（0.3 M☉ 不参与演化 / 0.6 M☉ 主序）：无变化"""
    jd = jd_from_age(SUN_NOW_AGE_GYR + 1.0)
    fake = _make_fake(jd, host_mass=0.6, host_age0=8.0,
                      planets=(("b", 0.05, 0.0),))
    Viewport._update_stellar_evolution(fake, jd)
    # 0.6 M☉ t_MS=34 Gyr：仍主序 → 原值
    assert fake._radius_km[0] == fake._radius_km0[0]
    assert 1 not in fake._engulfed


def test_vec_phases_used_by_viewport():
    """star_state_vec 阶段码与吞噬窗口一致（模型-视口契约）"""
    m = np.array([1.5])
    r, t, lum, mm, code = star_state_vec(m, np.array([4.2]),
                                         np.array([1.2]), np.array([6700.0]))
    assert code[0] != PHASE_MS
    # 4.2 Gyr 处于 RGB（3.63 < 4.2 < 4.3），半径已超 0.05 AU
    assert r[0] * 695700.0 / 1.496e8 > 0.05