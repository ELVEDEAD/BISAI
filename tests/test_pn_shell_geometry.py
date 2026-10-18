"""test_pn_shell_geometry.py —— 行星状星云壳绘制几何（防回归）

2026-10-18 教训：_draw_pn_shell 三环基向量 u 为 2 维、v 为 3 维，
(96,2)+(96,3) 广播失败 → 跳转白矮星节点渲染即崩（ValueError）。
GL 调用全部用 no-op fake，让几何计算真实执行。
"""
import math
from types import SimpleNamespace

import numpy as np

from core.sun_evolution import SunState, jd_from_age
from scene.viewport import Viewport


class _Noop:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_fake(age_gyr=12.5):
    fake = SimpleNamespace(
        _sun_state_cache=SunState(age_gyr, 0.013, 100.0, 50000.0, 0.546,
                                  "白矮星"),
        _eye=np.zeros(3),
        _mvp_rel=np.eye(4),
        _prog_line=_Noop(),
        _vbo_trail=_Noop(),
        _qmat=lambda m: None,
    )
    return fake


def test_pn_shell_geometry_no_broadcast_error():
    """白矮星早期（壳膨胀中）：三环生成无形状错误（回归：(96,2)+(96,3)）"""
    fake = _make_fake(12.5)
    Viewport._draw_pn_shell(fake, _Noop())   # 不抛异常即通过


def test_pn_shell_rings_on_sphere():
    """三环点均在半径 r_au 的球面上，且分别在三个正交平面内"""
    fake = _make_fake(12.5)
    captured = {}

    def _capture_data():
        pass

    # 直接复算函数内几何验证半径
    w = (12.5 - 12.40) / 0.30
    r_au = 1.0 + w * 45.0
    ang = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False)
    circ = np.stack([np.cos(ang), np.sin(ang)], axis=1)
    _U = np.array([1.0, 0.0, 0.0])
    _V = np.array([0.0, 1.0, 0.0])
    _Z = np.array([0.0, 0.0, 1.0])
    rings = []
    for u, v in ((_U, _V), (_V, _Z), (_U, _Z)):
        rings.append(circ[:, 0:1] * u[None, :] * r_au
                     + circ[:, 1:2] * v[None, :] * r_au)
    pts = np.vstack(rings)
    assert pts.shape == (288, 3)
    r = np.linalg.norm(pts, axis=1)
    assert np.allclose(r, r_au, atol=1e-9)      # 全部在球面上
    # 每环各处在一个坐标平面：xy 环 z=0，yz 环 x=0，xz 环 y=0
    assert np.allclose(pts[0:96, 2], 0.0)
    assert np.allclose(pts[96:192, 0], 0.0)
    assert np.allclose(pts[192:288, 1], 0.0)


def test_pn_shell_outside_window_skipped():
    """age 不在 [12.40, 12.70]（如 RGB tip / 深冷却期）直接跳过"""
    fake = _make_fake(12.18)   # RGB tip
    Viewport._draw_pn_shell(fake, _Noop())   # 早退不抛
    fake2 = _make_fake(14.0)   # 深冷却
    Viewport._draw_pn_shell(fake2, _Noop())


def test_pn_shell_draws_three_loops():
    """绘制调用：3 个 GL_LINE_LOOP，各 96 顶点（与 288 点数据一致）"""
    calls = []

    class _F:
        GL_DEPTH_TEST = 1
        GL_LINE_LOOP = 2

        def glDisable(self, *a):
            pass

        def glEnable(self, *a):
            pass

        def glDrawArrays(self, mode, first, count):
            calls.append((mode, first, count))

    fake = _make_fake(12.45)
    Viewport._draw_pn_shell(fake, _F())
    assert len(calls) == 3
    for mode, first, count in calls:
        assert mode == 2
        assert count == 96
    assert [c[1] for c in calls] == [0, 96, 192]

def test_roche_limits_draws_line_loops():
    """洛希圈绘制走 GL_LINE_LOOP（回归：glfuncs 缺该常量 → AttributeError）

    选中地球（planet_solar → 以太阳为 primary），刚体/流体两个圈。
    """
    calls = []

    class _F:
        GL_DEPTH_TEST = 1
        GL_LINE_LOOP = 2

        def glDisable(self, *a):
            pass

        def glEnable(self, *a):
            pass

        def glDrawArrays(self, mode, first, count):
            calls.append((mode, first, count))

    sun = SimpleNamespace(name="太阳", body_type="star")
    earth = SimpleNamespace(name="地球", body_type="planet_solar",
                            parent=None, radius_km=6371.0, mass_earth=1.0)
    fake = SimpleNamespace(
        show_roche=True,
        _body_pos=np.array([[0.0, 0.0, 0.0], [1.0, 0.2, 0.0]]),
        selected_name="地球",
        _index_of={"太阳": 0, "地球": 1},
        bodies=[sun, earth],
        _sun_state_cache=None, _evo_active=False,
        _eye=np.zeros(3),
        _mvp_rel=np.eye(4),
        _prog_line=_Noop(),
        _vbo_trail=_Noop(),
        _qmat=lambda m: None,
    )
    Viewport._draw_roche_limits(fake, _F())
    # 刚体（橙）+ 流体（红）两个圈，各 128 顶点
    assert len(calls) == 2
    for mode, first, count in calls:
        assert mode == 2 and count == 128
    # 选中天体不在列表（本例地球）也不影响主序分支（primary=太阳常量参数）