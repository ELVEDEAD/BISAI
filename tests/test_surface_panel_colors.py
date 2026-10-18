# -*- coding: utf-8 -*-
"""test_surface_panel_colors.py —— 地表视角天空配色 QColor 兼容性（防回归）

2026-10-18 用户报告：地表视角切到上海/北京后全景画布崩溃
"绘制失败: QColor(...) argument 1 has unexpected type 'float'"。
根因：太阳高度角落在 _SKY_ANCHORS 锚点之间时 _lerp3 插值出 float 元组，
地平雾线 QColor(hor_c[0], ...) 直接收 float（Qt 只接受 int）。
"""
from PyQt5.QtGui import QColor

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.surface_panel import _sky_colors


@pytest.mark.parametrize("alt", [-18.0, -12.3, -6.0, -3.7, -0.4, 0.0,
                                 4.2, 9.9, 10.0, 25.0, None])
def test_sky_colors_int_tuple(alt):
    """任何太阳高度角下配色均为 int 元组（含锚点间插值分支）"""
    top_c, hor_c = _sky_colors(alt)
    for c in (top_c, hor_c):
        assert len(c) == 3
        for v in c:
            assert isinstance(v, int), f"{alt}° 时颜色分量 {v!r} 非 int"
            assert 0 <= v <= 255


def test_qcolor_accepts_sky_colors():
    """配色可直接构造 QColor（复现原崩溃路径：地平雾线 4 参构造）"""
    for alt in (-12.3, -3.7, 4.2):
        _top, hor_c = _sky_colors(alt)
        col = QColor(hor_c[0], hor_c[1], hor_c[2], 90)
        assert col.isValid()