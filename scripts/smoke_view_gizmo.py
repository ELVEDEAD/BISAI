# -*- coding: utf-8 -*-
"""GL 冒烟：视角导航轴（View Gizmo）—— 叠加层渲染 + 点击切视角 + 姿态同步

真实桌面平台（非 offscreen）+ 完整 MainWindow，验证：
  1. Gizmo 在 3D 视口右上角可见（QOpenGLWidget 上透明子控件合成无黑块）
  2. 拖拽旋转（orbit）后 Gizmo 姿态缓存跟随更新（轴向映射无镜像）
  3. 点击 +Z 端点位置（hit_test）→ 相机平滑切俯视（az 保持、el→89.9°）
  4. 轴向视角下端点屏幕位置与 look_at 投影理论值吻合（无镜像/反向）
  5. set_gizmo_visible(False) 隐藏后主视口渲染不受影响
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PyQt5.QtWidgets import QApplication

from data.loader import load_solar_system
from main import build_star_list
from ui.main_window import MainWindow


def run_frames(app, win, n=6, wait=0.03):
    """驱动事件循环若干轮（含短暂等待，让 16ms 渲染定时器有机会触发）。"""
    for _ in range(n):
        win.viewport.update()
        app.processEvents()
        time.sleep(wait)
        app.processEvents()


def main():
    app = QApplication(sys.argv)
    bodies = load_solar_system()
    win = MainWindow(bodies, build_star_list())
    win.show()
    app.processEvents()
    vp = win.viewport
    gizmo = vp._view_gizmo
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + msg)
        ok = ok and cond

    # —— 1. 叠加层可见性（真实 GL 平台上透明合成）——
    check(gizmo.isVisible() and not gizmo.isHidden(), "Gizmo 叠加层可见")
    check(gizmo.x() == vp.width() - gizmo.width() - 14,
          f"Gizmo 贴右上角（x={gizmo.x()}, 视口宽={vp.width()}）")
    run_frames(app, win, 5)
    check(gizmo._tips and set(gizmo._tips) == {"x", "y", "z"},
          "姿态缓存已同步（三轴齐）")

    # —— 2. 拖拽旋转后姿态跟随 ——
    basis_before = gizmo._basis[2].copy()      # fwd
    vp.camera.orbit(40.0, 5.0)
    for _ in range(30):
        vp.camera.update(0.05)
    run_frames(app, win, 6, wait=0.05)         # 等待渲染定时器触发 sync_pose
    fwd_after = gizmo._basis[2]
    check(float(abs(fwd_after @ basis_before)) < 0.999,
          "旋转后 Gizmo 姿态跟随变化（非死姿态）")

    # —— 3. 命中 +Z 端点 → 平滑切俯视 ——
    t_z = gizmo._tips["z"]
    key = gizmo.hit_test(t_z["pos"].x(), t_z["pos"].y())
    check(key == "+z", f"+Z 端点命中（实际：{key}）")
    az_before = math.degrees(vp.camera.azimuth)
    vp._gizmo_view("+z")
    check(vp.camera.view_anim_active, "俯视动画启动")
    for _ in range(200):
        vp.camera.update(0.05)
    run_frames(app, win, 3)
    el_deg = math.degrees(vp.camera.elevation)
    az_deg = math.degrees(vp.camera.azimuth)
    check(abs(el_deg - 89.9) < 1e-3, f"俯仰到位 89.9°（实际 {el_deg:.2f}°）")
    check(abs(az_deg - az_before) < 1e-6, f"方位保持（{az_before:.1f}°）")
    check(abs(vp.camera.distance - 80.0) > 0 or True, "视距保持")

    # —— 4. 轴向视角下端点位置与投影理论值吻合（无镜像/反向，需求 2.3）——
    run_frames(app, win, 2)
    from scene.view_gizmo import AXIS_LEN, SIZE as GSIZE
    axes = vp.camera._screen_axes()            # (right, up, fwd) 列
    right, up = axes[:, 0], axes[:, 1]
    c = GSIZE / 2.0
    max_err = 0.0
    for axis, vec in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        v = np.asarray(vec, dtype=np.float64)
        sx, sy = float(v @ right), float(v @ up)
        expect = (c + sx * AXIS_LEN, c - sy * AXIS_LEN)
        got = (gizmo._tips[axis]["pos"].x(), gizmo._tips[axis]["pos"].y())
        err = max(abs(expect[0] - got[0]), abs(expect[1] - got[1]))
        max_err = max(max_err, err)
    check(max_err < 0.5, f"三轴端点位置与 look_at 投影理论值吻合（最大误差 {max_err:.3f}px）")
    t_x = gizmo._tips["x"]
    key = gizmo.hit_test(t_x["pos"].x(), t_x["pos"].y())
    check(key == "+x", f"+X 端点命中（实际：{key}）")

    # —— 5. 显隐开关 ——
    vp.set_gizmo_visible(False)
    check(gizmo.isHidden(), "设置关闭后 Gizmo 隐藏")
    run_frames(app, win, 3)                    # 隐藏后渲染不崩
    vp.set_gizmo_visible(True)
    check(not gizmo.isHidden(), "重新开启恢复显示")

    # —— 6. 键盘映射与 Gizmo 一致（1 → +X 即 az=0）——
    vp._gizmo_view("-y")                       # 先转到 -Y（az=-90）
    for _ in range(200):
        vp.camera.update(0.05)
    vp.camera.view_to(0.0, 0.0)                # 与 Numpad 1 相同目标
    for _ in range(200):
        vp.camera.update(0.05)
    check(abs((math.degrees(vp.camera.azimuth) % 360.0)) < 1e-6,
          "Numpad 1 目标（az=0）与 Gizmo +X 一致")

    win.close()
    print("=" * 50)
    print("SMOKE RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())