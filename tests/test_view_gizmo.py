"""test_view_gizmo.py —— Blender 风格视角导航轴（View Gizmo）测试

覆盖：camera.view_to 动画（最短路径/保持方位/可打断/飞行模式）、
Gizmo 姿态同步与命中判定（正负优先/负端点隐藏/姿态不变不重绘）、
viewport 集成（_gizmo_view 六向映射 / 显隐开关 / 事件拦截覆写）。
"""
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------- camera
def test_view_to_reaches_target(qapp):
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.azimuth = math.radians(35.0)
    cam.elevation = math.radians(20.0)
    cam.view_to(0.0, 0.0)
    assert cam.view_anim_active
    for _ in range(200):
        cam.update(0.05)
    assert not cam.view_anim_active
    assert abs(math.degrees(cam.azimuth) % 360.0) < 1e-6
    assert abs(math.degrees(cam.elevation)) < 1e-6
    # focus / distance 不动（保持观察目标与缩放）
    assert cam.distance == 80.0


def test_view_to_shortest_path(qapp):
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.azimuth = math.radians(350.0)      # -10°
    cam.view_to(10.0, 0.0)
    seen = []
    for _ in range(60):
        cam.update(0.05)
        seen.append(math.degrees(cam.azimuth))
    assert min(seen) >= 349.9              # 沿 +20° 最短路径，不绕 -340°
    assert abs((math.degrees(cam.azimuth) - 10.0) % 360.0) < 1e-6


def test_view_to_keeps_azimuth_for_poles(qapp):
    """+Z 俯视：az 保持当前值（水平朝向无唯一解），仅抬俯仰。"""
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.azimuth = math.radians(123.0)
    cam.view_to(None, 89.9)
    for _ in range(200):
        cam.update(0.05)
    assert abs(math.degrees(cam.azimuth) - 123.0) < 1e-6
    assert abs(math.degrees(cam.elevation) - 89.9) < 1e-3


def test_view_to_interruptible(qapp):
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.view_to(0.0, 0.0)
    for _ in range(4):
        cam.update(0.05)                   # 动画中途（0.2s < 0.4s）
    assert cam.view_anim_active
    cam.view_to(90.0, 0.0)                 # 改道新目标
    for _ in range(200):
        cam.update(0.05)
    assert abs((math.degrees(cam.azimuth) - 90.0) % 360.0) < 1e-6


def test_orbit_interrupts_view_anim(qapp):
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.view_to(90.0, 0.0)
    assert cam.view_anim_active
    cam.orbit(3.0, 1.0)                    # 用户拖拽 → 打断
    assert not cam.view_anim_active


def test_view_to_fly_mode(qapp):
    from scene.camera import OrbitCamera
    cam = OrbitCamera()
    cam.enter_fly()
    cam.view_to(90.0, 0.0)
    for _ in range(200):
        cam.update(0.05)
    assert abs((math.degrees(cam.fly_yaw) - 90.0) % 360.0) < 1e-6
    assert abs(math.degrees(cam.fly_pitch)) < 1e-6
    assert not cam.view_anim_active


# ---------------------------------------------------------------- gizmo
def _make_gizmo(qapp, az_deg=0.0, el_deg=0.0):
    from scene.camera import OrbitCamera
    from scene.view_gizmo import ViewGizmo
    cam = OrbitCamera()
    cam.azimuth = math.radians(az_deg)
    cam.elevation = math.radians(el_deg)
    g = ViewGizmo()
    g.sync_pose(cam)
    return g, cam


def test_gizmo_sync_pose_and_paint(qapp):
    g, cam = _make_gizmo(qapp, 35.0, 20.0)
    assert set(g._tips) == {"x", "y", "z"}
    img = QImage(g.size(), QImage.Format_ARGB32)
    g.render(img)                          # 离屏完整渲染不崩
    assert not img.isNull()


def test_gizmo_tip_geometry(qapp):
    """az=0/el=0：X 轴正对屏幕（负端隐藏）；Y 在屏幕右；Z 在屏幕上。"""
    from scene.view_gizmo import SIZE, AXIS_LEN
    g, _ = _make_gizmo(qapp, 0.0, 0.0)
    c = SIZE / 2.0
    assert g._tips["x"]["neg_vis"] is False        # X 轴两端投影重合 → 负端隐藏
    assert g._tips["y"]["neg_vis"] is True
    assert g.hit_test(c + AXIS_LEN, c) == "+y"     # Y 正端在屏幕右
    assert g.hit_test(c, c - AXIS_LEN) == "+z"     # Z 正端在屏幕上
    assert g.hit_test(c - AXIS_LEN, c) == "-y"     # Y 负端在屏幕左
    assert g.hit_test(c + 20, c + 20) is None      # 空白区域无命中
    # （中心处有正对屏幕的 X 正端点，属于命中而非空白）


def test_gizmo_positive_priority_on_overlap(qapp):
    """正负端点投影重合时优先命中正方向（需求 3.3）。"""
    g, _ = _make_gizmo(qapp, 35.0, 20.0)
    # 构造正负端点重合的极端情形（直接操纵缓存模拟几何重叠）
    t = g._tips["x"]
    t["neg_vis"] = True
    t["neg"] = t["pos"]
    assert g.hit_test(t["pos"].x(), t["pos"].y()) == "+x"


def test_gizmo_sync_only_on_change(qapp):
    """姿态不变时 sync_pose 不重绘自身（需求 2.3 性能约束）。"""
    g, cam = _make_gizmo(qapp, 35.0, 20.0)
    calls = []
    orig = g.update
    g.update = lambda *a, **k: calls.append(1)
    try:
        g.sync_pose(cam)                   # 姿态未变 → 不 update
        assert not calls
        cam.azimuth += 0.5                 # 姿态变化 → update
        g.sync_pose(cam)
        assert len(calls) == 1
    finally:
        g.update = orig


def test_gizmo_set_shown(qapp):
    g, _ = _make_gizmo(qapp)
    g.set_shown(False)
    assert g.isHidden()
    g.set_shown(True)
    assert not g.isHidden()


def test_gizmo_events_overridden(qapp):
    """滚轮/鼠标事件在 Gizmo 内被拦截（不冒泡触发主视图，需求 3.6）。"""
    from scene.view_gizmo import ViewGizmo
    assert "wheelEvent" in ViewGizmo.__dict__
    assert "mousePressEvent" in ViewGizmo.__dict__
    assert "mouseMoveEvent" in ViewGizmo.__dict__


# ---------------------------------------------------------------- viewport 集成
def test_viewport_gizmo_mapping(qapp):
    from scene.viewport import Viewport
    vp = Viewport()
    for key, (waz, wel) in {
        "+x": (0.0, 0.0), "-x": (180.0, 0.0),
        "+y": (90.0, 0.0), "-y": (-90.0, 0.0),
        "+z": (None, 89.9), "-z": (None, -89.9),
    }.items():
        az_before = math.degrees(vp.camera.azimuth)   # 本轮起始方位
        vp._gizmo_view(key)
        assert vp.camera.view_anim_active, key
        for _ in range(300):
            vp.camera.update(0.05)
        if waz is None:
            # 极点视角：az 保持本轮起始值（保持观察朝向，仅抬/压俯仰）
            assert abs(math.degrees(vp.camera.azimuth) - az_before) < 1e-6, key
        else:
            assert abs((math.degrees(vp.camera.azimuth) - waz) % 360.0) < 1e-6, key
        assert abs(math.degrees(vp.camera.elevation) - wel) < 1e-3, key
    vp._gizmo_view("+nope")                # 未知键：安全忽略
    assert not vp.camera.view_anim_active


def test_viewport_gizmo_visible_toggle(qapp):
    from scene.viewport import Viewport
    vp = Viewport()
    assert hasattr(vp, "_view_gizmo")
    vp.set_gizmo_visible(False)
    assert vp._view_gizmo.isHidden()
    vp.set_gizmo_visible(True)
    assert not vp._view_gizmo.isHidden()


def test_gizmo_view_constant_table(qapp):
    """映射表覆盖六向；az=None 表示保持方位（极点视角）。"""
    from scene.viewport import Viewport as _V
    t = _V._GIZMO_VIEWS
    assert set(t) == {"+x", "-x", "+y", "-y", "+z", "-z"}
    assert t["+z"][0] is None and t["-z"][0] is None


def test_app_settings_gizmo_roundtrip():
    from core import app_settings
    old = app_settings.get_show_view_gizmo()
    try:
        app_settings.set_show_view_gizmo(not old)
        assert app_settings.get_show_view_gizmo() is (not old)
    finally:
        app_settings.set_show_view_gizmo(old)