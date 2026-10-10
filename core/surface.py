"""
surface.py —— 星球地表视角（任意天体的地平坐标）

与 core/observer.py 的分工
--------------------------
* observer.py 只服务「地球上的观测者」：用 GMST + 经纬度算地平坐标；
* surface.py 把观测者泛化到任意天体表面（地球 / 月球 / 火星 / 各大行星…）：
      观测点位置 = 该天体的日心位置（观测点距天体中心的高度忽略，见下）
      天顶方向   = 由天体自转轴 pole_ecl + 自转相位 W(jd) 与表面经纬度确定
      目标方向   = 目标位置 − 观测点位置（恒星按无穷远只取方向）

坐标与公式（全部在 J2000 黄道系下计算）
---------------------------------------
* 自转轴 p：Body.pole_ecl（IAU WGCCRE 极轴转入黄道系）
* 赤道面正交基 (e1, e2, p)：e1 = normalize(cross(−z_ecl, p))，e2 = cross(p, e1)
  对地球该基恰为「春分点方向 / 赤道 y 轴 / 北天极」，故与 observer.py 完全自洽
* 天顶 Z = cosφ·cosλ·e1 + cosφ·sinλ·e2 + sinφ·p，λ = 经度 + 自转相位 W
* 北向 N = p 在水平面上的投影（归一化）；东向 E = N × Z
* 高度角 alt = asin(d̂·Z)；方位角 az = atan2(d̂·E, d̂·N)，自正北起向东为正

科学诚实性
----------
* 地球：自转相位直接取 GMST（与 observer.py 同一公式），可与「地面视角」互校；
* 其他天体：本初子午线角常数项 W(J2000) 未收录，取可复现假设 W(J2000)=0，
  只影响经度的绝对零点，不影响自转速率/方向与星空的相对运动；
* 潮汐锁定卫星缺自转周期时，按「自转周期 = 公转周期、自转轴 = 轨道面法向」回退——
  这正是潮汐锁定的物理定义，不是伪造；
* 未建模大气折射、地形遮挡、光行差；恒星视差忽略（< 1″）；
* 天体相位（如月相、金星位相）不参与绘制，一律按整圆盘示意；
* 观测点位于天体中心 + 半径处，未计入自转离心与地形海拔。
"""
import math

import numpy as np

from core.constants import J2000_JD, DEG2RAD
from core.observer import local_sidereal_deg

AU_KM = 1.495978707e8
EARTH = "地球"
SUN = "太阳"

# 太阳在 1 AU 处的视星等（IAU 常用值），作为反射光天体亮度的基准
SUN_MAG_1AU = -26.74

# 几何反照率（无量纲）。来源：NASA/JPL 行星事实表；月球为球面反照率近似值。
ALBEDO = {
    "水星": 0.142, "金星": 0.689, "地球": 0.434, "火星": 0.170,
    "木星": 0.538, "土星": 0.499, "天王星": 0.488, "海王星": 0.442,
    "冥王星": 0.52, "月球": 0.136,
}
DEFAULT_ALBEDO = 0.30

# 允许站上去看的地表预设（名称 → 该天体默认地形风格）
SURFACE_PRESETS = {
    "地球": ("地球（你在这里）", "hills"),
    "月球": ("月球", "craters"),
    "火星": ("火星", "dunes"),
    "水星": ("水星", "craters"),
    "金星": ("金星", "hills"),
    "木星": ("木星（云顶）", "clouds"),
    "土星": ("土星（云顶）", "clouds"),
    "天王星": ("天王星（云顶）", "clouds"),
    "海王星": ("海王星（云顶）", "clouds"),
    "冥王星": ("冥王星", "craters"),
}


# ---------- 自转 ----------
def spin_period_days(body):
    """自转周期（天，恒星日；负值 = 逆行）。潮汐锁定卫星回退为公转周期。"""
    if getattr(body, "rot_period_days", None):
        return float(body.rot_period_days)
    if body.body_type == "moon" and getattr(body, "period_days", None):
        return float(body.period_days)
    return None


def spin_axis(body):
    """自转轴单位向量（J2000 黄道系）。缺极轴的潮汐锁定卫星取轨道面法向。"""
    p = getattr(body, "pole_ecl", None)
    if p is not None:
        p = np.asarray(p, dtype=np.float64)
        n = float(np.linalg.norm(p))
        if n > 1e-12:
            return p / n
    if body.body_type == "moon":
        h = body.orbit_normal()
        if h is not None:
            h = np.asarray(h, dtype=np.float64)
            n = float(np.linalg.norm(h))
            if n > 1e-12:
                return h / n
    return None


def spin_assumed(body) -> bool:
    """自转参数是否为回退假设（缺真实极轴/周期）"""
    if getattr(body, "pole_ecl", None) is not None and getattr(body, "rot_period_days", None):
        return False
    return body.body_type == "moon"


def spin_phase_rad(body, jd: float) -> float:
    """自转相位（弧度）。

    地球取 GMST（与 observer.py 自洽）；其他天体取 W(J2000)=0 的可复现假设。
    """
    if body.name == EARTH:
        return math.radians(local_sidereal_deg(jd, 0.0))
    P = spin_period_days(body)
    if not P:
        return 0.0
    return 2.0 * math.pi * (jd - J2000_JD) / P


def _equatorial_basis(p):
    """赤道面正交基 (e1, e2)，满足 e1 × e2 = p。

    对地球：e1 = 春分点方向，e2 = 赤道 y 轴（即与 observer.py 的赤道系一致）。
    """
    ref = np.array([0.0, 0.0, -1.0])
    if abs(float(np.dot(p, ref))) > 0.999:
        ref = np.array([1.0, 0.0, 0.0])
    e1 = np.cross(ref, p)
    n = float(np.linalg.norm(e1))
    if n < 1e-12:
        e1 = np.cross(np.array([1.0, 0.0, 0.0]), p)
        n = float(np.linalg.norm(e1))
    e1 = e1 / max(n, 1e-15)
    e2 = np.cross(p, e1)
    return e1, e2


# ---------- 观测者局部地平坐标系 ----------
def observer_frame(body, jd: float, lat_deg: float, lon_deg: float):
    """地表观测者的局部地平坐标系。

    返回 {"origin": 位置(AU), "zenith"/"north"/"east": 单位向量,
          "spin_period": 天, "assumed": bool}；缺自转数据返回 None。
    """
    p = spin_axis(body)
    if p is None:
        return None
    e1, e2 = _equatorial_basis(p)
    W = spin_phase_rad(body, jd)
    lam = math.radians(float(lon_deg)) + W
    phi = math.radians(float(lat_deg))

    Z = (math.cos(phi) * math.cos(lam) * e1
         + math.cos(phi) * math.sin(lam) * e2
         + math.sin(phi) * p)
    nz = float(np.linalg.norm(Z))
    if nz < 1e-12:
        return None
    Z = Z / nz

    N = p - float(np.dot(p, Z)) * Z
    nn = float(np.linalg.norm(N))
    if nn < 1e-9:                       # 恰在极点：北向退化，取 e1 的水平分量
        N = e1 - float(np.dot(e1, Z)) * Z
        nn = float(np.linalg.norm(N))
        if nn < 1e-9:
            return None
    N = N / nn
    E = np.cross(N, Z)
    ne = float(np.linalg.norm(E))
    if ne < 1e-12:
        return None
    E = E / ne

    try:
        origin = np.asarray(body.position_at_jd(jd), dtype=np.float64)
    except Exception:
        return None
    if not np.all(np.isfinite(origin)):
        return None
    return {"origin": origin, "zenith": Z, "north": N, "east": E,
            "spin_period": spin_period_days(body), "assumed": spin_assumed(body)}


def altaz_of_dir(d, frame) -> tuple:
    """方向向量（黄道系）→ (高度角°, 方位角°)"""
    d = np.asarray(d, dtype=np.float64)
    n = float(np.linalg.norm(d))
    if n < 1e-15:
        return None, None
    u = d / n
    c = float(np.dot(u, frame["zenith"]))
    alt = math.degrees(math.asin(max(-1.0, min(1.0, c))))
    az = math.degrees(math.atan2(float(np.dot(u, frame["east"])),
                                 float(np.dot(u, frame["north"])))) % 360.0
    return alt, az


# ---------- 亮度与视直径 ----------
def angular_diameter_deg(radius_km, dist_au) -> float:
    """视直径（度）= 2·atan(R/Δ)"""
    if not radius_km or not dist_au or dist_au <= 0:
        return 0.0
    return 2.0 * math.degrees(math.atan(float(radius_km) / (float(dist_au) * AU_KM)))


def apparent_magnitude(body, target_pos, observer_pos, radius_km):
    """视星等（以太阳在 1 AU 处的 −26.74 为基准）。

    * 自发光（太阳）：m = m☉(1AU) + 5·lg Δ
    * 反射光（行星/卫星）：m = m☉(1AU) − 2.5·lg[ 反照率·(R/Δ)²·(1/r)² ]
      其中 r 为目标日心距、Δ 为观测者到目标的距离（同单位即可，此处均取 AU）

    校验：满月 −13.1（实测约 −12.7）、木星 −2.5、金星 −4.2、
          从月球看「满地」−16.9（比满月亮约 40~100 倍）——量级均与实测相符。
    """
    delta = float(np.linalg.norm(np.asarray(target_pos, dtype=np.float64)
                                 - np.asarray(observer_pos, dtype=np.float64)))
    if delta <= 0:
        return None
    if body.body_type == "star":
        return SUN_MAG_1AU + 5.0 * math.log10(delta)
    if not radius_km:
        return None
    r = float(np.linalg.norm(np.asarray(target_pos, dtype=np.float64)))
    if r <= 0:
        return None
    ratio = (ALBEDO.get(body.name, DEFAULT_ALBEDO)
             * (float(radius_km) / AU_KM / delta) ** 2 * (1.0 / r) ** 2)
    if ratio <= 0:
        return None
    return SUN_MAG_1AU - 2.5 * math.log10(ratio)


def star_mag_from_size(star_size: float) -> float:
    """由 build_star_list 的绘制尺寸反推星等（仅用于排序/示意）"""
    return (5.0 - float(star_size)) / 1.15


# ---------- 快照 ----------
def _find(bodies, name):
    if isinstance(bodies, dict):
        return bodies.get(name)
    return next((b for b in bodies if b.name == name), None)


def surface_snapshot(body, jd: float, lat_deg: float, lon_deg: float,
                     bodies, stars=None) -> list:
    """站在 body 表面 (lat, lon) 处、时刻 jd 看到的天体列表。

    返回 [{name, kind, alt, az, ang_diam, mag, color, radius_km, dist_au}]；
    kind ∈ {sun, planet, dwarf, moon, star}，按视星等升序（最亮在前）。
    """
    frame = observer_frame(body, jd, lat_deg, lon_deg)
    if frame is None:
        return []
    origin = frame["origin"]

    out = []
    for b in bodies:
        if b is body:
            continue
        if b.body_type == "planet_exo":
            continue                     # 系外行星：宿主距离下不可见，且缺大气/相位参数
        if b.body_type not in ("star", "planet_solar", "dwarf", "moon"):
            continue
        try:
            pos = np.asarray(b.position_at_jd(jd), dtype=np.float64)
        except Exception:
            continue
        if not np.all(np.isfinite(pos)):
            continue
        delta = pos - origin
        dist = float(np.linalg.norm(delta))
        if dist < 1e-9:
            continue
        alt, az = altaz_of_dir(delta, frame)
        if alt is None:
            continue

        mag = apparent_magnitude(b, pos, origin, b.radius_km)
        if mag is None:
            mag = 30.0                   # 缺半径/反照率的反射天体：方向保留，亮度置极暗
        out.append({
            "name": b.name, "kind": "sun" if b.body_type == "star" else b.body_type,
            "alt": alt, "az": az,
            "ang_diam": angular_diameter_deg(b.radius_km, dist),
            "mag": float(mag), "color": tuple(b.color) if b.color else (0.9, 0.9, 0.9),
            "radius_km": b.radius_km, "dist_au": dist,
        })

    for s in (stars or ()):
        name, unit, size, color = s[0], s[1], s[2], s[3]
        alt, az = altaz_of_dir(np.asarray(unit, dtype=np.float64), frame)
        if alt is None:
            continue
        out.append({
            "name": name, "kind": "star", "alt": alt, "az": az,
            "ang_diam": 0.0, "mag": star_mag_from_size(size),
            "color": tuple(color), "radius_km": None, "dist_au": None,
            "star_size": float(size),
        })

    out.sort(key=lambda o: o["mag"])     # 视星等升序：最亮在前
    return out


def sun_altitude(body, jd: float, lat_deg: float, lon_deg: float, bodies):
    """太阳在该地表观测点的高度角（度）；不可用时返回 None"""
    frame = observer_frame(body, jd, lat_deg, lon_deg)
    sun = _find(bodies, SUN)
    if frame is None or sun is None:
        return None
    try:
        d = np.asarray(sun.position_at_jd(jd), dtype=np.float64) - frame["origin"]
    except Exception:
        return None
    alt, _ = altaz_of_dir(d, frame)
    return alt


def sun_daily_path(body, jd: float, lat_deg: float, lon_deg: float, bodies,
                   hours: float = 24.0, n: int = 240):
    """一个当地日内的太阳视运动轨迹 (az, alt)，用于画日轨线；不可用返回 (None, None)"""
    sun = _find(bodies, SUN)
    if sun is None:
        return None, None
    jds = np.linspace(jd - hours / 2.0, jd + hours / 2.0, n)
    az, alt = [], []
    for j in jds:
        frame = observer_frame(body, float(j), lat_deg, lon_deg)
        if frame is None:
            return None, None
        try:
            d = np.asarray(sun.position_at_jd(float(j)), dtype=np.float64) - frame["origin"]
        except Exception:
            return None, None
        a, z = altaz_of_dir(d, frame)
        if a is None:
            return None, None
        alt.append(a)
        az.append(z)
    return np.array(az), np.array(alt)


# ---------- 可选天体清单 ----------
def surface_capable_bodies(bodies) -> list:
    """可提供地表视角的天体（太阳系行星/矮行星/天然卫星，且能定出自转轴）"""
    out = []
    for b in bodies:
        if b.body_type not in ("planet_solar", "dwarf", "moon"):
            continue
        if spin_axis(b) is None:
            continue
        out.append(b)
    return out


def default_lat_lon(body):
    """默认观测点：地球取上海，其他天体取赤道本初子午线附近"""
    if body.name == EARTH:
        return 31.23, 121.47
    return 0.0, 0.0