"""
observer.py —— 观测者地面视角（地平坐标 / 升落时刻）

把「站在某个经纬度、某个时刻抬头看到的天空」算出来：
    赤道坐标 (RA/Dec) --(当地恒星时 + 纬度)--> 地平坐标 (高度角 alt / 方位角 az)

公式
----
* 格林尼治平恒星时 GMST(度) = 280.46061837 + 360.98564736629·(JD − 2451545.0)
* 当地恒星时 LST = GMST + 东经（度）
* 时角 H = LST − RA
* sin(alt) = sin δ·sin φ + cos δ·cos φ·cos H
* az = atan2(−cos δ·sin H, sin δ·cos φ − cos δ·sin φ·cos H)，自北起向东量

科学诚实性
----------
* 行星地心位置取自 JPL 近似星历（1800–2050），高度角误差约 arcmin 级；
* 未逐点建模大气折射，日出/日落采用标准折射修正 h₀ = −0.833°；
* 未作周日视差修正（行星视差 < 1′，月球除外）；
* 天然卫星（含月球）轨道相位为可复现假设值，绝对位置无预测意义，故不参与星空绘制。
"""
import math

from datetime import datetime

import numpy as np

from core.constants import J2000_JD, OBLIQUITY_J2000_DEG, DEG2RAD
from core.time_system import jd_to_datetime, datetime_to_jd

# 观测地点预设（名称, 纬度°, 东经°, 时区小时）
CITIES = [
    ("上海", 31.23, 121.47, 8.0), ("北京", 39.90, 116.41, 8.0),
    ("广州", 23.13, 113.26, 8.0), ("成都", 30.66, 104.07, 8.0),
    ("乌鲁木齐", 43.83, 87.62, 8.0), ("哈尔滨", 45.80, 126.53, 8.0),
    ("拉萨", 29.65, 91.14, 8.0), ("三亚", 18.25, 109.51, 8.0),
    ("香港", 22.32, 114.17, 8.0),
    ("东京", 35.68, 139.69, 9.0), ("新加坡", 1.35, 103.82, 8.0),
    ("悉尼", -33.87, 151.21, 10.0),
    ("伦敦", 51.51, -0.13, 0.0), ("纽约", 40.71, -74.01, -5.0),
    ("洛杉矶", 34.05, -118.24, -8.0),
    ("基多（赤道）", -0.18, -78.47, -5.0), ("开普敦", -33.92, 18.42, 2.0),
    ("北极圈（摩尔曼斯克）", 68.97, 33.08, 3.0),
    ("北极点", 89.9, 0.0, 0.0), ("南极点", -89.9, 0.0, 0.0),
]

# 太阳的升落判据：日面中心高度 −0.833°（含大气折射 34′ 与日面半径 16′）
SUN_RISE_ALT = -0.833
# 暮光高度：民用 / 航海 / 天文
TWILIGHT_LEVELS = [("民用暮光", -6.0), ("航海暮光", -12.0), ("天文暮光", -18.0)]

EARTH_NAME = "地球"


# ---------- 时间与坐标 ----------
def local_datetime(jd_utc: float, tz_hours: float) -> datetime:
    """UTC 儒略日 → 当地时刻（仅做时区平移，不含夏令时）"""
    return jd_to_datetime(jd_utc + tz_hours / 24.0)


def utc_jd_of_local_noon(jd_utc: float, tz_hours: float) -> float:
    """返回「当地日期当天正午」对应的 UTC 儒略日，用于取当日升落事件"""
    dt = local_datetime(jd_utc, tz_hours)
    local_noon = datetime_to_jd(datetime(dt.year, dt.month, dt.day, 12))
    return local_noon - tz_hours / 24.0


def local_sidereal_deg(jd: float, lon_deg: float) -> float:
    """当地平恒星时（度，0–360）"""
    gmst = 280.46061837 + 360.98564736629 * (jd - J2000_JD)
    return (gmst + lon_deg) % 360.0


def ecliptic_to_equatorial_vec(v) -> np.ndarray:
    """J2000 黄道坐标向量 → J2000 赤道坐标向量（绕 x 轴转 −ε）"""
    x, y, z = (float(v[0]), float(v[1]), float(v[2]))
    eps = OBLIQUITY_J2000_DEG * DEG2RAD
    return np.array([x,
                     y * math.cos(eps) - z * math.sin(eps),
                     y * math.sin(eps) + z * math.cos(eps)], dtype=np.float64)


def vec_to_ra_dec(v) -> tuple:
    """赤道坐标向量 → (赤经°, 赤纬°)"""
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-15:
        return None, None
    u = v / n
    ra = math.degrees(math.atan2(float(u[1]), float(u[0]))) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, float(u[2])))))
    return ra, dec


def altaz(ra_deg: float, dec_deg: float, lat_deg: float, lst_deg: float) -> tuple:
    """赤道坐标 (RA/Dec) + 纬度 + 当地恒星时 → (高度角°, 方位角°)

    方位角自正北起、向东为正（0=N，90=E，180=S，270=W）。
    """
    H = (lst_deg - ra_deg) * DEG2RAD
    d = dec_deg * DEG2RAD
    p = lat_deg * DEG2RAD
    sin_alt = math.sin(d) * math.sin(p) + math.cos(d) * math.cos(p) * math.cos(H)
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    az = math.degrees(math.atan2(
        -math.cos(d) * math.sin(H),
        math.sin(d) * math.cos(p) - math.cos(d) * math.sin(p) * math.cos(H)))
    return alt, az % 360.0


# ---------- 天体地心方向 ----------
def _get(bodies, name):
    if isinstance(bodies, dict):
        return bodies.get(name)
    return next((b for b in bodies if b.name == name), None)


def geocentric_ra_dec(body, jd: float, earth) -> tuple:
    """天体的地心赤道坐标 (RA°, Dec°)。太阳取 −地球日心位置。"""
    try:
        g = (np.asarray(body.position_at_jd(jd), dtype=np.float64)
             - np.asarray(earth.position_at_jd(jd), dtype=np.float64))
    except Exception:
        return None, None
    if float(np.linalg.norm(g)) < 1e-12:
        return None, None
    return vec_to_ra_dec(ecliptic_to_equatorial_vec(g))


def sun_alt(jd: float, lat_deg: float, lon_deg: float, sun=None, earth=None) -> float:
    """太阳高度角（度）"""
    if sun is None or earth is None:
        return float("nan")
    ra, dec = geocentric_ra_dec(sun, jd, earth)
    if ra is None:
        return float("nan")
    alt, _ = altaz(ra, dec, lat_deg, local_sidereal_deg(jd, lon_deg))
    return alt


# ---------- 星空快照 ----------
def sky_snapshot(jd: float, lat_deg: float, lon_deg: float, bodies, stars=None) -> list:
    """当前时刻的天体地平坐标列表。

    返回 [{name, kind, alt, az, mag, size, color, below}]；
    kind ∈ {sun, planet, dwarf, star}（star 为背景亮星）。
    """
    earth = _get(bodies, EARTH_NAME)
    if earth is None:
        return []
    lst = local_sidereal_deg(jd, lon_deg)
    out = []

    for b in bodies:
        if b.body_type == "moon":
            continue                      # 相位为假设值，位置无预测意义
        if b.body_type not in ("star", "planet_solar", "dwarf"):
            continue
        ra, dec = geocentric_ra_dec(b, jd, earth)
        if ra is None:
            continue
        alt, az = altaz(ra, dec, lat_deg, lst)
        kind = "sun" if b.body_type == "star" else b.body_type
        out.append({"name": b.name, "kind": kind, "alt": alt, "az": az,
                    "ra": ra, "dec": dec, "below": alt < 0.0,
                    "size": 9.0 if kind == "sun" else 5.0,
                    "color": b.color})

    for s in (stars or ()):
        name, unit, size, color = s[0], s[1], s[2], s[3]
        ra, dec = vec_to_ra_dec(ecliptic_to_equatorial_vec(np.asarray(unit, float)))
        if ra is None:
            continue
        alt, az = altaz(ra, dec, lat_deg, lst)
        out.append({"name": name, "kind": "star", "alt": alt, "az": az,
                    "ra": ra, "dec": dec, "below": alt < 0.0,
                    "size": float(size), "color": tuple(color)})
    return out


def sun_path(jd: float, lat_deg: float, lon_deg: float, bodies,
             hours: float = 24.0, n: int = 240):
    """一个地方日内的太阳视运动轨迹（az, alt），用于画日轨线"""
    sun = _get(bodies, "太阳")
    earth = _get(bodies, EARTH_NAME)
    if sun is None or earth is None:
        return None, None
    jds = np.linspace(jd - hours / 2.0, jd + hours / 2.0, n)
    az, alt = [], []
    for j in jds:
        ra, dec = geocentric_ra_dec(sun, j, earth)
        if ra is None:
            return None, None
        a, z = altaz(ra, dec, lat_deg, local_sidereal_deg(j, lon_deg))
        alt.append(a)
        az.append(z)
    return np.array(az), np.array(alt)


# ---------- 升落时刻 ----------
def _crossings(jds, vals, level: float) -> list:
    """数组 vals 相对 level 的穿越点（线性内插 + 二分细化），返回 (jd, 上行?)"""
    out = []
    for i in range(len(jds) - 1):
        v0, v1 = vals[i] - level, vals[i + 1] - level
        if v0 == 0.0:
            out.append((float(jds[i]), v1 > 0.0))
        elif v0 * v1 < 0.0:
            a, b = float(jds[i]), float(jds[i + 1])
            for _ in range(40):
                m = 0.5 * (a + b)
                vm = np.interp(m, jds, vals) - level
                if (v0 < 0.0) == (vm < 0.0):
                    a = m
                else:
                    b = m
            out.append((0.5 * (a + b), v1 > 0.0))
    return out


def sun_events(jd0: float, lat_deg: float, lon_deg: float, bodies) -> dict:
    """当日（jd0 前后各半天）的太阳事件：日出/日落/中天 + 三档暮光。

    极昼/极夜时 rise/set 为 None，并以 polar 字段标注。
    """
    sun = _get(bodies, "太阳")
    earth = _get(bodies, EARTH_NAME)
    if sun is None or earth is None:
        return {}
    n = 721                                   # 2 分钟步长
    jds = np.linspace(jd0 - 0.5, jd0 + 0.5, n)
    alts = np.array([sun_alt(float(j), lat_deg, lon_deg, sun, earth) for j in jds])
    if not np.all(np.isfinite(alts)):
        return {}

    k = int(np.argmax(alts))
    res = {"transit": float(jds[k]), "max_alt": float(alts[k]),
           "min_alt": float(np.min(alts)),
           "day_hours": float(np.sum(alts > SUN_RISE_ALT) * (1.0 / (n - 1)) * 24.0)}

    rises, sets = [], []
    for jd, up in _crossings(jds, alts, SUN_RISE_ALT):
        (rises if up else sets).append(jd)
    res["rise"] = min(rises) if rises else None
    res["set"] = max(sets) if sets else None
    res["polar_day"] = not rises and not sets and res["min_alt"] > SUN_RISE_ALT
    res["polar_night"] = not rises and not sets and res["max_alt"] < SUN_RISE_ALT

    for label, level in TWILIGHT_LEVELS:
        rr, ss = [], []
        for jd, up in _crossings(jds, alts, level):
            (rr if up else ss).append(jd)
        res[label] = (min(rr) if rr else None, max(ss) if ss else None)
    return res


def alt_az_text(alt: float, az: float) -> str:
    """高度角 / 方位角的中文描述"""
    if alt is None:
        return "未知"
    dirs = ["正北", "东北", "正东", "东南", "正南", "西南", "正西", "西北"]
    d = dirs[int(((az + 22.5) % 360.0) // 45.0)]
    return f"高度 {alt:+.1f}°  方位 {az:.1f}°（{d}）"