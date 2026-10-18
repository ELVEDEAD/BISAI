"""test_trail_geo.py —— 尾迹高倍速几何弧修复（防尾迹退化为直线）"""
import math
from types import SimpleNamespace

import numpy as np

from scene.viewport import Viewport


def _make_setup(speed=3652500.0, direction=1):
    """单位圆轨道 + 位于 (1,0,0) 的行星，模拟 viewport 的尾迹相关状态"""
    n = 256
    E = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([np.cos(E), np.sin(E), np.zeros(n)], axis=1)
    body = SimpleNamespace(name="P", body_type="planet_solar", period_days=365.25,
                           period=365.25, a_au=1.0,
                           parent=None, incl_deg=0.0, elements=None)
    data = np.hstack([pts, np.zeros((n, 3))]).astype(np.float32)
    fake = SimpleNamespace(
        bodies=[body], compare_names=[], selected_name="P",
        _body_pos=np.array([[1.0, 0.0, 0.0]]),
        clock=SimpleNamespace(speed=speed, direction=direction),
        _trail_last=0.0, trail_mode="clear", _trails={},
        _moon_orbits={}, _sat_orbits={},
        _orbit_ranges={"P": (0, n)}, _orbit_data=data,
    )
    fake._trail_geo_arc = lambda *a: Viewport._trail_geo_arc(fake, *a)
    return fake, pts


def test_high_speed_trail_is_smooth_arc():
    self, _ = _make_setup()
    Viewport._record_trail(self)
    arc = np.asarray(self._trails["P"])
    assert len(arc) == 96
    # 末点贴合当前天体位置
    assert np.allclose(arc[-1], [1, 0, 0], atol=0.03)
    # 所有点都在轨道圆上（几何弧而非穿心直线）
    r = np.linalg.norm(arc, axis=1)
    assert np.allclose(r, 1.0, atol=0.01)
    # 相邻点弧长小且均匀（平滑曲线）
    d = np.linalg.norm(np.diff(arc, axis=0), axis=1)
    assert d.max() < 0.1


def test_low_speed_trail_samples_current_pos():
    self, _ = _make_setup(speed=1.0)
    Viewport._record_trail(self)
    arc = self._trails["P"]
    assert len(arc) == 1
    assert np.allclose(arc[0], [1, 0, 0])


def test_reverse_direction_flips_arc():
    fwd, _ = _make_setup(direction=1)
    rev, _ = _make_setup(direction=-1)
    Viewport._record_trail(fwd)
    Viewport._record_trail(rev)
    a1 = np.asarray(fwd._trails["P"])
    a2 = np.asarray(rev._trails["P"])
    # 末点相同（当前位置），起点方向相反
    assert np.allclose(a1[-1], a2[-1], atol=0.03)
    assert not np.allclose(a1[0], a2[0], atol=1e-3)


def test_moon_trail_uses_parent_center():
    parent = SimpleNamespace(name="地球")
    moon = SimpleNamespace(name="月球", body_type="moon", period_days=27.3,
                           period=27.3, a_au=0.0026,
                           parent=parent, incl_deg=5.1)
    n = 128
    E = np.linspace(0, 2 * math.pi, n, endpoint=False)
    rel = 0.0026 * np.stack([np.cos(E), np.sin(E), np.zeros(n)], axis=1)
    ppos = np.array([1.0, 0.0, 0.0])
    self = SimpleNamespace(
        bodies=[parent, moon], compare_names=[], selected_name="月球",
        _body_pos=np.array([ppos, ppos + rel[0]]),
        clock=SimpleNamespace(speed=3652500.0, direction=1),
        _trail_last=0.0, trail_mode="clear", _trails={},
        _moon_orbits={"月球": (rel, None)}, _sat_orbits={},
        _orbit_ranges={}, _orbit_data=np.zeros((0, 6), dtype=np.float32),
    )
    self._trail_geo_arc = lambda *a: Viewport._trail_geo_arc(self, *a)
    Viewport._record_trail(self)
    arc = np.asarray(self._trails["月球"])
    assert len(arc) == 64  # min(96, 128//2)
    assert np.allclose(arc[-1], ppos + rel[0], atol=1e-6)
    r = np.linalg.norm(arc - ppos, axis=1)
    assert np.allclose(r, 0.0026, atol=1e-6)

def test_planet_without_period_days_uses_fallback():
    """回归：真实太阳系行星无 period_days 字段（period property 开普勒 fallback），
    高倍速下必须走几何弧分支，否则尾迹退化为穿心直线"""
    n = 256
    E = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([np.cos(E), np.sin(E), np.zeros(n)], axis=1)
    body = SimpleNamespace(name="海王星", body_type="planet_solar",
                           period_days=None, period=60266.0, a_au=30.07,
                           parent=None, incl_deg=1.77, elements=None)
    data = np.hstack([pts, np.zeros((n, 3))]).astype(np.float32)
    self = SimpleNamespace(
        bodies=[body], compare_names=[], selected_name="海王星",
        _body_pos=np.array([[1.0, 0.0, 0.0]]),
        clock=SimpleNamespace(speed=3652500.0, direction=1),  # 1 万年/秒
        _trail_last=0.0, trail_mode="clear", _trails={},
        _moon_orbits={}, _sat_orbits={},
        _orbit_ranges={"海王星": (0, n)}, _orbit_data=data,
    )
    self._trail_geo_arc = lambda *a: Viewport._trail_geo_arc(self, *a)
    Viewport._record_trail(self)
    arc = np.asarray(self._trails["海王星"])
    assert len(arc) == 96
    r = np.linalg.norm(arc, axis=1)
    assert np.allclose(r, 1.0, atol=0.01)
    d = np.linalg.norm(np.diff(arc, axis=0), axis=1)
    assert d.max() < 0.1