# -*- coding: utf-8 -*-
"""GL 冒烟：吞噬语义（时间条件复活）—— RGB tip 吞噬 → 白矮星不复活 → 跳回恢复
真实桌面平台（非 offscreen）+ 完整 MainWindow，验证：
  1. RGB tip 时水星/金星被吞，engulfChanged 信号使左侧树同步隐藏
  2. 推进到白矮星期：被吞天体不复活（旧 bug 全部复活）
  3. 跳回现在：恢复显示，树条目恢复
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from core.sun_evolution import SUN_NOW_AGE_GYR, jd_from_age
from data.loader import load_solar_system
from main import build_star_list
from ui.main_window import MainWindow


def run_frames(app, win, n=3):
    for _ in range(n):
        win.viewport.update()
        app.processEvents()


def main():
    app = QApplication(sys.argv)
    bodies = load_solar_system()
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

    # —— 1. RGB tip（12.18 Gyr）：水星 0.31 AU、金星 0.72 AU 均入 1.19 AU 光球 ——
    jd_tip = jd_from_age(12.18)
    vp.clock.jump_to(jd_tip)
    run_frames(app, win)
    engulfed_names = sorted(vp.bodies[i].name for i in vp._engulfed)
    check("水星" in engulfed_names, f"RGB tip 吞噬水星（实际：{engulfed_names}）")
    check(bool(engulfed_names), "吞噬列表非空")
    check(tree._vanished == set(engulfed_names),
          f"树同步隐藏（树：{sorted(tree._vanished)}）")
    print(f"INFO  engulfChanged 去重后应只发 1 次：{vp._vanished_emitted}")

    # —— 2. 白矮星期（12.5 Gyr）：时间晚于吞噬时刻 → 不复活 ——
    jd_wd = jd_from_age(12.50)
    vp.clock.jump_to(jd_wd)
    run_frames(app, win)
    wd_engulfed = sorted(vp.bodies[i].name for i in vp._engulfed)
    check(wd_engulfed == engulfed_names,
          f"白矮星期不复活（实际：{wd_engulfed}，期望：{engulfed_names}）")
    check(tree._vanished == set(engulfed_names), "树保持隐藏")

    # —— 3. 跳回现在：时间早于吞噬时刻 → 恢复 ——
    from core.constants import J2000_JD
    vp.clock.jump_to(J2000_JD)
    run_frames(app, win)
    check(len(vp._engulfed) == 0,
          f"跳回现在全部恢复（剩余：{sorted(vp.bodies[i].name for i in vp._engulfed)}）")
    check(len(tree._vanished) == 0, "树条目恢复")
    check(not vp._shatter_hidden, "无残留撕裂隐藏")

    win.close()
    print("RESULT", "ALL_PASS" if ok else "HAS_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())