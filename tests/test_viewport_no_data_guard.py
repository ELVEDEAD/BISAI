"""test_viewport_no_data_guard.py —— 数据未加载时视口渲染帧不崩溃（防回归）

时序：Viewport.__init__ 启动 16ms 定时器，_near_idx 要等 load_bodies() 才赋值；
启动器异步加载/模式切换期间 paintGL 可能先到，_update_body_positions 必须
在 _near_idx is None 时安全跳过（曾致 3D 启动报 TypeError 闪退）。
"""
from types import SimpleNamespace

import numpy as np

from scene.viewport import Viewport


def _fake_without_data():
    """伪造数据未加载的 viewport：_near_idx/_body_pos 均为初始 None"""
    fake = SimpleNamespace(
        bodies=[],
        clock=SimpleNamespace(jd=2451545.0, speed=1.0),
        _near_idx=None,
        _body_pos=None,
        _engulfed={}, _shatter_hidden=set(),
        _engulf_dirty=False, _vanished_emitted=[], _evo_last_jd=None,
        _star_evo_idx=None, _star_evo_last_jd=None, _star_evo_last_t=0.0,
        _sun_state_cache=None, _evo_active=False,
        _orbit_scale_applied=1.0, _last_orbit_rebuild=0.0,
        evolution_events=[],
        _exo_idx=np.zeros(0, dtype=np.int64),
        _far_small_idx=[], _far_idx=np.zeros(0, dtype=np.int64),
        _far_pos=None, _far_tick=0, _far_stride=8,
        on_demand=True, _active_until=0.0,
        camera=SimpleNamespace(fly_mode=False),
        _dragging=False, follow_body=None,
    )
    fake._update_sun_evolution = (
        lambda jd: Viewport._update_sun_evolution(fake, jd))
    fake._update_stellar_evolution = (
        lambda jd: Viewport._update_stellar_evolution(fake, jd))
    return fake


def test_no_data_frame_is_noop():
    """_near_idx=None：本帧安全跳过，_body_pos 保持 None，不抛异常"""
    vp = _fake_without_data()
    Viewport._update_body_positions(vp, None)   # f 未用（早退）
    assert vp._body_pos is None


def test_sun_evolution_survives_no_data():
    """数据未加载帧先跑 _update_sun_evolution 也不崩（当前时间 → 主序早退）"""
    vp = _fake_without_data()
    Viewport._update_sun_evolution(vp, vp.clock.jd)
    assert vp._evo_active is False
    assert vp._sun_state_cache.phase == "主序"