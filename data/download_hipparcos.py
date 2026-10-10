"""
download_hipparcos.py —— 下载 ESA Hipparcos 主星表官方目录（可选联网更新）

功能：
    从 CDS VizieR TAP 服务下载 ESA Hipparcos 主星表（I/239/hip_main，共 118218 颗）
    的精选字段，保存为 data/hipparcos.csv；软件启动时优先加载该文件
    （data/loader.py 的 load_hipparcos），用于渲染真实的银河系背景恒星。

    字段：HIP（星表编号）、RAICRS/DEICRS（J2000 赤道坐标，度）、
          Vmag（视星等）、Plx（三角视差，mas → 距离 pc）、B-V（色指数）、SpType（光谱型）。

用法：
    python data/download_hipparcos.py

说明：
    - 本脚本为可选的在线更新工具，软件离线亦可运行（回退到内置亮星表）。
    - 数据来源标注：ESA Hipparcos Catalogue（ESA 1997），经 CDS VizieR I/239 分发。
    - 反爬说明：cdsarc.cds.unistra.fr 的 ftp 目录受 Anubis 保护，故改用
      tapvizier.cds.unistra.fr 的 TAP 接口（返回 CSV，可正常访问）。
"""
import sys
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"

# 仅取渲染所需字段（B-V 含连字符，ADQL 中需加双引号）
QUERY = ('select HIP,RAICRS,DEICRS,Vmag,Plx,"B-V",SpType '
         'from "I/239/hip_main" where Plx > 0 and Vmag is not null')

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hipparcos.csv")


def main():
    params = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL",
                                     "FORMAT": "csv", "QUERY": QUERY})
    url = f"{TAP_URL}?{params}"
    print("正在从 CDS VizieR 下载 ESA Hipparcos 主星表（I/239/hip_main）...")
    print(f"URL: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlanetViewer/1.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[错误] 下载失败：{e}")
        print("请检查网络连接后重试；离线状态下软件将使用内置亮星表。")
        sys.exit(1)

    header = (
        "# ESA Hipparcos Catalogue (I/239/hip_main) — 经 CDS VizieR TAP 分发\n"
        f"# 下载时间: {datetime.now(timezone.utc).isoformat()}\n"
        "# 字段: HIP,RAICRS(deg),DEICRS(deg),Vmag,Plx(mas),B-V,SpType\n"
        "# 距离由三角视差换算：d(pc) = 1000 / Plx(mas)\n"
    )
    lines = data.strip().splitlines()
    n_rows = max(0, len(lines) - 1)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")
    print(f"[完成] 共 {n_rows} 颗恒星，已保存到 {OUT_PATH}")


if __name__ == "__main__":
    main()