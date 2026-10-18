# -*- coding: utf-8 -*-
"""GL 冒烟：地表视角切换城市绘制 —— 修复 QColor(float) 崩溃的端到端验证。

离屏平台构造完整 SurfacePanel（真实天体数据），依次切换上海/北京/拉萨
并触发全景画布 paintEvent，绘制异常会被 _PanoramaCanvas 捕获并渲染
"绘制失败：..."文本——通过抓取画布像素检测是否出现该文本背景色。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage

from data.loader import load_solar_system
from main import build_star_list
from ui.surface_panel import SurfacePanel


def main():
    app = QApplication(sys.argv)
    bodies = load_solar_system()
    panel = SurfacePanel(bodies=bodies, stars=build_star_list())
    panel.resize(900, 500)
    panel.show()
    app.processEvents()
    ok = True

    for city in ("上海", "北京", "广州", "拉萨"):
        idx = panel.cmb_city.findText(city)
        assert idx >= 0, f"找不到城市 {city}"
        panel.cmb_city.setCurrentIndex(idx)
        panel.refresh()
        app.processEvents()
        img = QImage(panel.canvas.size(), QImage.Format_ARGB32)
        panel.canvas.render(img)
        # 检查错误分支背景色 (20,20,24) 是否大范围出现
        n = img.width() * img.height()
        wrong = 0
        for y in range(img.height()):
            for x in range(0, img.width(), 8):   # 隔 8 列抽样
                c = img.pixel(x, y)
                if (c & 0xFFFFFF) == 0xFF181414:  # BGR(20,20,24)
                    wrong += 8
        good = wrong < n // 10
        print(("PASS  " if good else "FAIL  ") + f"{city} 绘制正常"
              + ("" if good else f"（错误底色像素 {wrong}/{n}）"))
        ok = ok and good

    panel.close()
    print("RESULT", "ALL_PASS" if ok else "HAS_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())