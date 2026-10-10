# -*- coding: utf-8 -*-
"""生成应用图标 assets/app.ico（深色圆角底 + 橙金色行星 + 浅蓝行星环）

用途：打包时通过 PyInstaller --icon 指定，替换掉默认的 PyInstaller 图标。
说明：默认 PyInstaller 图标被大量恶意样本使用，是杀软启发式误报的常见特征之一，
      换成自定义图标可降低误报概率，同时更符合参赛作品形象。
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT_DIR, exist_ok=True)

S = 512
BG = (24, 24, 28, 255)
PLANET = (232, 125, 13, 255)
PLANET_HI = (255, 190, 110, 255)
RING = (150, 200, 255, 235)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

d.rounded_rectangle([0, 0, S - 1, S - 1], radius=96, fill=BG)

cx, cy, r = 256, 264, 124
ring_box = [cx - 196, cy - 56, cx + 196, cy + 56]

d.arc(ring_box, start=180, end=360, fill=RING, width=22)      # 行星后方半环
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PLANET)       # 行星本体
d.ellipse([cx - 92, cy - 96, cx - 20, cy - 24], fill=PLANET_HI)  # 受光高光
d.arc(ring_box, start=0, end=180, fill=RING, width=22)         # 行星前方半环

out = os.path.join(OUT_DIR, "app.ico")
img.save(out, format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(os.path.join(OUT_DIR, "app.png"), format="PNG")
print("已生成:", out)
print("尺寸:", os.path.getsize(out), "bytes")