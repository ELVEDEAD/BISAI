# -*- coding: utf-8 -*-
"""GL 冒烟：系外宿主恒星演化吞噬 —— 跳深未来 → 恒星膨胀吞噬其行星 →
左侧树同步隐藏 → 跳回现在恢复。真实桌面平台 + 完整 MainWindow。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from core.constants import J2000_JD
from core.sun_evolution import jd_from_age, SUN_NOW_AGE_GYR
from data.loader import load_all_bodies
from main import build_star_list
from ui.main_window import MainWindow


def run_frames(app, win, n=3):
    for _ in range(n):
        win.viewport.update()
        app.processEvents()


def main():
    app = QApplication(sys.argv)
    bodies, _stats = load_all_bodies()
    win = MainWindow(bodies, build_star_list())
    win.show()
    app.processEvents()
    vp = win.viewport
    tree = win.tree_panel
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + msg)
        ok = ok and cond

    # —— 1. 跳到红巨星极大节点（Δ=+7.6 Gyr）：区间判定覆盖大量宿主演化期 ——
    jd_tip = jd_from_age(12.18)
    vp.clock.jump_to(jd_tip)
    run_frames(app, win)
    exo_engulfed = [vp.bodies[i] for i in vp._engulfed
                    if vp.bodies[i].body_type == "planet_exo"]
    solar_engulfed = [vp.bodies[i].name for i in vp._engulfed
                      if vp.bodies[i].body_type != "planet_exo"]
    print(f"INFO  太阳吞噬: {solar_engulfed}")
    print(f"INFO  系外吞噬: {len(exo_engulfed)} 颗 "
          f"(样例: {[b.name for b in exo_engulfed[:5]]})")
    check(len(exo_engulfed) > 0, "深未来有系外行星被宿主恒星吞噬")
    # 恒星演化渲染应用（半径偏离原值）
    import numpy as np
    if vp._star_evo_idx is not None and len(vp._star_evo_idx):
        diff = (vp._radius_km[vp._star_evo_idx]
                != vp._radius_km0[vp._star_evo_idx])
        check(int(diff.sum()) > 0,
              f"宿主恒星渲染已演化（{int(diff.sum())} 颗半径/颜色已改）")
    # 树同步：被吞系外行星在树中隐藏
    vanished_exo = {b.name for b in exo_engulfed}
    check(vanished_exo <= tree._vanished,
          f"树同步隐藏系外行星（缺 {len(vanished_exo - tree._vanished)}）")
    # 事件日志含系外吞噬
    ev = [e[2] for e in vp.evolution_events]
    check(any("演化膨胀吞噬行星" in t for t in ev), "事件日志含系外吞噬记录")

    # —— 2. 跳回现在：全部恢复 ——
    vp.clock.jump_to(J2000_JD)
    run_frames(app, win)
    check(len(vp._engulfed) == 0, "跳回现在全部恢复（含系外）")
    check(len(tree._vanished) == 0, "树条目全部恢复")
    if vp._star_evo_idx is not None and len(vp._star_evo_idx):
        same = np.array_equal(vp._radius_km[vp._star_evo_idx],
                              vp._radius_km0[vp._star_evo_idx],
                              equal_nan=True)
        check(same, "宿主恒星半径/颜色恢复主序原值")

    win.close()
    print("RESULT", "ALL_PASS" if ok else "HAS_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())