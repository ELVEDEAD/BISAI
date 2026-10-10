"""
download_exoplanets.py —— 下载 NASA Exoplanet Archive 官方完整系外行星目录（可选联网更新）

功能：
    从 NASA Exoplanet Archive TAP 服务下载「已确认行星」官方完整目录
    （pscomppars 表，6375 颗，2026-10 快照），保存为 data/exoplanets.csv；
    软件启动时优先加载该文件（loader.load_exoplanets）。

    相比 ps 表，pscomppars 提供「每颗行星一行」的复合参数，并含宿主恒星参数
    （温度/半径/质量/光谱型/光度/年龄/金属丰度），用于按「恒星系」分组展示。

用法：
    python data/download_exoplanets.py

说明：
    - 本脚本为可选的在线更新工具，软件离线亦可运行（内置精选子集）。
    - 数据来源标注：NASA Exoplanet Archive（pscomppars 表），下载时间记入文件头注释。
    - 注意：TAP 查询不要使用 LIMIT/TOP，会返回 400。
"""
import sys
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

COLUMNS = [
    # 行星
    "pl_name", "hostname", "pl_orbper", "pl_orbsmax", "pl_orbeccen", "pl_orbincl",
    "pl_bmasse", "pl_rade", "pl_dens", "pl_eqt", "disc_year", "discoverymethod",
    # 系统
    "sy_snum", "sy_pnum", "sy_dist", "ra", "dec",
    # 宿主恒星
    "st_teff", "st_rad", "st_mass", "st_spectype", "st_lum", "st_age", "st_met",
]
QUERY = "select " + ",".join(COLUMNS) + " from pscomppars"

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exoplanets.csv")


def main():
    params = urllib.parse.urlencode({"query": QUERY, "format": "csv"})
    url = f"{TAP_URL}?{params}"
    print("正在从 NASA Exoplanet Archive 下载官方完整目录（pscomppars）...")
    print(f"URL: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlanetViewer/1.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[错误] 下载失败：{e}")
        print("请检查网络连接后重试；离线状态下软件将使用内置精选子集。")
        sys.exit(1)

    header = (
        "# NASA Exoplanet Archive — Planetary Systems Composite Parameters (pscomppars)\n"
        f"# 下载时间: {datetime.now(timezone.utc).isoformat()}\n"
        "# 字段: pl_name,hostname,pl_orbper(d),pl_orbsmax(AU),pl_orbeccen,pl_orbincl(deg),\n"
        "#       pl_bmasse(Mearth),pl_rade(Rearth),pl_dens(g/cm3),pl_eqt(K),disc_year,\n"
        "#       discoverymethod,sy_snum,sy_pnum,sy_dist(pc),ra(deg),dec(deg),\n"
        "#       st_teff(K),st_rad(Rsun),st_mass(Msun),st_spectype,st_lum(logLsun),st_age(Gyr),st_met(dex)\n"
    )
    lines = data.strip().splitlines()
    n_rows = max(0, len(lines) - 1)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")
    print(f"[完成] 共 {n_rows} 颗行星，已保存到 {OUT_PATH}")


if __name__ == "__main__":
    main()