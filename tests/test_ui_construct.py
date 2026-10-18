"""test_ui_construct.py —— UI 构造路径防回归（Timeline / MainWindow）

2026-10-18 教训：timeline.py 用了 SUN_NOW_AGE_GYR/jd_from_age 却没导入，
NameError 在 MainWindow 构造时才爆（py_compile 查不出、核心测试覆盖不到）。
本文件离屏构造真实控件，保证 UI 构造路径可执行。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_timeline_constructs(qapp):
    """Timeline 构造 + 演化下拉填充（回归：SUN_NOW_AGE_GYR 未定义 NameError）"""
    from core.time_system import SimulationClock
    from ui.timeline import Timeline

    tl = Timeline(SimulationClock())
    labels = [tl.cmb_evolution.itemText(i)
              for i in range(tl.cmb_evolution.count())]
    assert any("现在" in s for s in labels)
    assert tl.cmb_evolution.count() >= 6


def test_main_window_constructs(qapp):
    """MainWindow 完整构造（含全部面板 + 工具栏 + 演化日志入口）"""
    from data.loader import load_solar_system
    from main import build_star_list
    from ui.main_window import MainWindow

    bodies = load_solar_system()
    win = MainWindow(bodies, build_star_list())
    assert hasattr(win, "_show_evolution_log")
    assert hasattr(win.viewport, "evolution_events")
    win.close()