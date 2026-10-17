"""
loader.py —— 天体数据统一加载层

设计要点（对应需求 4.3 / 4.4 / 4.5 节）：
- 统一坐标系：J2000 黄道坐标系。赤道坐标(RA/Dec)经黄赤交角旋转转入。
- 缺失字段一律为 None，界面显示"未知"，禁止伪造（科学诚实性）。
- 系外行星平近点角未测定：相位取 M(J2000)=0 的可复现假设值（非随机数），
  仅影响沿轨道瞬时位置，不影响轨道形状/周期；文档中明确说明。
- 数据校验：字段非法（NaN/负数等）视为缺失，不抛异常、不崩溃。
"""
import math
import os
import sys
import numpy as np
from dataclasses import dataclass, field

from core.constants import (PARSEC_AU, OBLIQUITY_J2000_DEG, DEG2RAD, J2000_JD,
                            GRADE_A, GRADE_B, GRADE_C, M_SUN_PER_EARTH, AU_KM,
                            M_EARTH_KG)
from core.kepler import position_at_time, elements_to_position, solve_kepler, velocity_at_time
from core.time_system import datetime_to_jd
from data.solar_system import (SOLAR_PLANETS, SUN, SolarElements, MOONS, POLES,
                               ROTATION)
from data.exoplanets_builtin import BUILTIN_EXOPLANETS
from data.blackholes_builtin import BUILTIN_BLACKHOLES
from data.etno_builtin import get_all_etnos
from data.nearby_stars_builtin import get_nearby_stars
from data.interstellar_objects import INTERSTELLAR_OBJECTS
from data.artificial_satellites import ARTIFICIAL_SATELLITES

G_SI = 6.67430e-11
M_SUN_KG = 1.98892e30
AU_M = 1.495978707e11

# ---------- 坐标转换（全软件统一） ----------
def _equatorial_to_ecliptic(ra_deg: float, dec_deg: float) -> np.ndarray:
    """赤道单位方向向量 → 黄道单位方向向量（J2000）"""
    ra, dec, eps = ra_deg * DEG2RAD, dec_deg * DEG2RAD, OBLIQUITY_J2000_DEG * DEG2RAD
    x = math.cos(dec) * math.cos(ra)
    y = math.cos(dec) * math.sin(ra) * math.cos(eps) + math.sin(dec) * math.sin(eps)
    z = -math.cos(dec) * math.sin(ra) * math.sin(eps) + math.sin(dec) * math.cos(eps)
    return np.array([x, y, z], dtype=np.float64)


def host_star_ecliptic_pos(ra_deg: float, dec_deg: float, dist_pc: float) -> np.ndarray:
    """宿主恒星三维位置（AU，J2000 黄道系）：方向 × 距离"""
    if ra_deg is None or dec_deg is None or dist_pc is None:
        return None
    return _equatorial_to_ecliptic(ra_deg, dec_deg) * (dist_pc * PARSEC_AU)


def _safe_float(v, lo=None, hi=None):
    """非法数值 → None（缺失），缺失显示'未知'，不伪造"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    if lo is not None and f < lo:
        return None
    if hi is not None and f > hi:
        return None
    return f


BODY_TYPE_LABELS = {
    "star": "恒星（太阳）",
    "host_star": "宿主恒星",
    "planet_solar": "行星（太阳系）",
    "dwarf": "矮行星（太阳系）",
    "moon": "天然卫星",
    "satellite": "人造卫星",
    "planet_exo": "系外行星",
    "blackhole": "黑洞",
    "etno": "极端海外天体",
    "interstellar": "星际天体",
    "nearby_star": "近邻恒星",
}


@dataclass
class SystemGroup:
    """恒星系（系群）：一颗宿主恒星及其行星。

    太阳系为一特例（is_solar=True，含恒星「太阳」与天然卫星）。
    用于左侧天体树按「恒星系」归类展示，以及恒星系概览面板。
    """
    host: str
    is_solar: bool = False
    star: object = None                            # 恒星 Body（太阳系为太阳）
    planets: list = field(default_factory=list)    # 行星 / 矮行星
    moons: list = field(default_factory=list)      # 天然卫星（仅太阳系）
    satellites: list = field(default_factory=list) # 人造卫星（仅太阳系）
    spec: str = ""                                 # 恒星光度型（如 G2V、M8V）
    dist_pc: float = None                          # 恒星系距地球距离（pc）
    planet_count: int = None                       # 官方已确认行星数（sy_pnum）
    star_count: int = None                         # 系统恒星数（sy_snum）
    host_teff: float = None                        # 宿主恒星有效温度（K）
    host_radius_solar: float = None                # 宿主恒星半径（R☉）
    host_mass_solar: float = None                  # 宿主恒星质量（M☉）
    host_lum: float = None                         # 宿主星光度（log L☉）

    @property
    def n_planets(self) -> int:
        """本恒星系收录的成员行星数"""
        return len(self.planets)


@dataclass
class Body:
    """统一天体模型：太阳系行星 / 矮行星 / 恒星 / 系外行星"""
    name: str
    body_type: str
    grade: str                       # 精度等级 A/B/C
    color: tuple
    en_name: str = ""
    host: str = ""                   # 宿主恒星（太阳系行星为"太阳"）
    # —— JPL 近似根数（太阳系） ——
    elements: SolarElements = None
    # —— 开普勒根数（系外行星 / 通用） ——
    a_au: float = None
    e: float = None
    incl_deg: float = None
    period_days: float = None
    # —— 物理参数 ——
    radius_km: float = None
    mass_earth: float = None
    # —— 发现信息 ——
    disc_year: int = None
    method: str = ""
    data_source: str = ""            # 数据来源标注（详情面板展示）
    # —— 系外行星 / 恒星位置 ——
    dist_pc: float = None
    ra_deg: float = None
    dec_deg: float = None
    host_pos: np.ndarray = None      # 宿主恒星黄道坐标（AU）
    assumed_phase: bool = False      # 平近点角为假设值（M(J2000)=0）
    visible_mag: float = None        # 恒星视星等（背景渲染用）
    # —— 宿主恒星（系外行星所属恒星系） ——
    host_teff: float = None          # 宿主恒星有效温度（K）
    host_radius_solar: float = None  # 宿主恒星半径（R☉）
    host_mass_solar: float = None    # 宿主恒星质量（M☉）
    host_spec: str = ""              # 宿主恒星光度型（如 G2V）
    host_lum: float = None           # 宿主星光度（log L☉）
    host_age: float = None           # 宿主星年龄（Gyr）
    host_met: float = None           # 宿主星金属丰度 [Fe/H]（dex）
    sys_planet_count: int = None     # 该系统已确认行星数
    sys_star_count: int = None       # 该系统恒星数
    # —— 行星附加物理量 ——
    eq_temp: float = None            # 平衡温度（K）
    density: float = None            # 密度（g/cm³）
    # —— 天然卫星 ——
    parent: object = field(default=None, repr=False, compare=False)  # 母天体 Body
    parent_name: str = ""            # 母天体名称（地球/木星/…）
    plane: str = "equator"           # 卫星轨道面参考：equator=母行星赤道面 / ecliptic=黄道面
    retro: bool = False              # 逆行轨道（如海卫一）
    # —— 人造卫星 ——
    raan_deg: float = 0.0            # 升交点经度（度，星座代表值）
    sat_category: str = ""           # 轨道类型（低轨 LEO / 太阳同步 SSO / 中轨 MEO / 地球同步 GEO）
    sat_note: str = ""               # 任务说明
    agency: str = ""                 # 运营机构
    # —— 自转 ——
    rot_period_days: float = None    # 自转周期（恒星日，天；负值=逆行自转）
    pole_ecl: np.ndarray = None      # 自转轴方向（J2000 黄道系单位向量）
    # —— 黑洞 ——
    bh_type: str = ""                # 黑洞类型（恒星级/中等质量/超大质量）

    # ---------- 周期 ----------
    @property
    def period(self) -> float:
        """公转周期（天）；太阳系行星由半长轴推算（开普勒第三定律），系外行星用实测值"""
        if self.period_days:
            return self.period_days
        if self.a_au and self.body_type in ("planet_solar", "dwarf", "etno"):
            return 365.25 * self.a_au ** 1.5
        return None

    @property
    def mass_solar(self):
        if self.mass_earth is None:
            return None
        return self.mass_earth / M_SUN_PER_EARTH

    # ---------- 自转 ----------
    @property
    def rotation_direction(self):
        """自转方向：顺行 / 逆行（缺数据返回 None）"""
        if self.rot_period_days is None:
            return None
        return "逆行" if self.rot_period_days < 0 else "顺行"

    def orbit_normal(self) -> np.ndarray:
        """轨道面法向（J2000 黄道系单位向量）。

        行星/矮行星：由轨道倾角 i 与升交点经度 Ω 构造；
        天然卫星：取母行星赤道面（或黄道面）法向；系外行星：倾角已知时按 Ω=0 近似。
        缺参数返回 None（不伪造）。
        """
        if self.body_type in ("planet_solar", "dwarf", "etno") and self.elements is not None:
            i = self.elements.i * DEG2RAD
            Om = self.elements.Omega * DEG2RAD
            n = np.array([math.sin(i) * math.sin(Om),
                          -math.sin(i) * math.cos(Om),
                          math.cos(i)])
            return n / max(float(np.linalg.norm(n)), 1e-15)
        if self.body_type == "moon":
            u, v = self._moon_plane_basis()
            n = np.cross(u, v)
            return n / max(float(np.linalg.norm(n)), 1e-15)
        if self.body_type == "satellite":
            u, v = self._satellite_plane_basis()
            n = np.cross(u, v)
            return n / max(float(np.linalg.norm(n)), 1e-15)
        if self.incl_deg is not None:
            i = self.incl_deg * DEG2RAD
            return np.array([0.0, -math.sin(i), math.cos(i)])
        return None

    @property
    def axial_tilt_deg(self):
        """转轴倾角（度）：自转轴与轨道面法线的夹角。

        取向约定（与天文教科书一致）：顺行自转取 <90° 的一侧，逆行自转取 >90°
        的一侧。自转轴方向取 IAU WGCCRE 极轴（RA/Dec）转入黄道系；缺极轴或
        轨道面法向时返回 None。
        """
        if self.pole_ecl is None:
            return None
        h = self.orbit_normal()
        if h is None:
            return None
        p = self.pole_ecl / max(float(np.linalg.norm(self.pole_ecl)), 1e-15)
        c = float(np.dot(p, h))
        ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        retro = bool(self.rot_period_days is not None and self.rot_period_days < 0)
        if (ang > 90.0) != retro:        # 取向与自转方向不一致时取另一侧
            ang = 180.0 - ang
        return ang

    def spin_angle_at_jd(self, jd: float) -> float:
        """自转相位（弧度，随时间单调推进；逆行自转为负向）。

        相位零点取可复现假设值 W(J2000)=0（IAU 本初子午线角的常数项未收录），
        只影响子午线当前朝向，不影响自转速率/方向。
        """
        if not self.rot_period_days:
            return 0.0
        return 2.0 * math.pi * (jd - J2000_JD) / self.rot_period_days

    # ---------- 位置 ----------
    def position_at_jd(self, jd: float) -> np.ndarray:
        """三维位置（AU，J2000 黄道系）。恒星/黑洞返回宿主位置/原点。"""
        if self.body_type in ("star", "host_star", "blackhole", "interstellar", "nearby_star"):
            return self.host_pos.copy() if self.host_pos is not None else np.zeros(3)
        if self.body_type in ("planet_solar", "dwarf", "etno"):
            T = (jd - J2000_JD) / 36525.0
            el = self.elements
            return position_at_time(el.a, el.a_dot, el.e, el.e_dot, el.i, el.i_dot,
                                    el.L, el.L_dot, el.varpi, el.varpi_dot,
                                    el.Omega, el.Omega_dot, T)
        if self.body_type == "moon":
            # 天然卫星：母行星位置 + 相对母行星的开普勒轨道
            base = (self.parent.position_at_jd(jd)
                    if self.parent is not None else np.zeros(3))
            return base + self._moon_relative_pos(jd)
        if self.body_type == "satellite":
            # 人造卫星：地球位置 + 相对地球的开普勒轨道（轨道面含真实倾角）
            base = (self.parent.position_at_jd(jd)
                    if self.parent is not None else np.zeros(3))
            return base + self._satellite_relative_pos(jd)
        # 系外行星：宿主星位置 + 相对开普勒轨道
        if self.host_pos is None:
            return np.zeros(3)
        return self.host_pos + self._relative_pos(jd)

    def _moon_plane_basis(self):
        """卫星轨道面的正交基 (u, v)（J2000 黄道系单位向量）。

        母行星赤道面：由 POLES 的真实极轴（赤道坐标 RA/Dec）转入黄道系作为法向；
        月球取黄道面。轨道面近似约定见 solar_system.MOONS 注释。
        """
        if self.plane == "ecliptic" or self.parent is None:
            return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        pole = POLES.get(self.parent.name)
        if pole is None:
            return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        n = _equatorial_to_ecliptic(pole[0], pole[1])
        n = n / max(float(np.linalg.norm(n)), 1e-15)
        ref = np.array([0.0, 0.0, 1.0])
        if abs(float(np.dot(n, ref))) > 0.9:
            ref = np.array([1.0, 0.0, 0.0])
        u = np.cross(ref, n)
        u = u / max(float(np.linalg.norm(u)), 1e-15)
        v = np.cross(n, u)
        if self.retro:                     # 逆行轨道：反转轨道方向
            v = -v
        return u, v

    def _moon_relative_pos(self, jd: float) -> np.ndarray:
        """相对母行星的位置（AU）。相位取可复现假设值 M(J2000)=0。"""
        if not self.a_au:
            return np.zeros(3)
        e = self.e if self.e is not None else 0.0
        p = self.period_days or 1.0
        M = (2.0 * math.pi / p) * (jd - J2000_JD)
        E = solve_kepler(M, e)
        xv = self.a_au * (math.cos(E) - e)
        yv = self.a_au * math.sqrt(max(1.0 - e * e, 0.0)) * math.sin(E)
        u, v = self._moon_plane_basis()
        return xv * u + yv * v

    def _satellite_plane_basis(self):
        """人造卫星轨道面正交基 (u, v)（J2000 黄道系单位向量）。

        以**地球赤道面**为参考面，按倾角 i 与升交点经度 Ω 构造：
            轨道面法向（赤道系） n_eq = (sin i sin Ω, −sin i cos Ω, cos i)
            升交点方向（赤道系） u_eq = (cos Ω, sin Ω, 0)
        再绕 x 轴（春分点）旋转 −ε（黄赤交角）转入黄道系。
        Ω 为星座代表值；i 为实测倾角，故 98.2° 的太阳同步轨道等能得到正确朝向。
        """
        i = (self.incl_deg or 0.0) * DEG2RAD
        Om = (self.raan_deg or 0.0) * DEG2RAD
        eps = OBLIQUITY_J2000_DEG * DEG2RAD
        ce, se = math.cos(eps), math.sin(eps)
        n = np.array([math.sin(i) * math.sin(Om),
                      -math.sin(i) * math.cos(Om) * ce + math.cos(i) * se,
                      math.sin(i) * math.cos(Om) * se + math.cos(i) * ce])
        u = np.array([math.cos(Om),
                      math.sin(Om) * ce,
                      -math.sin(Om) * se])
        n = n / max(float(np.linalg.norm(n)), 1e-15)
        u = u / max(float(np.linalg.norm(u)), 1e-15)
        v = np.cross(n, u)
        return u, v

    def _satellite_relative_pos(self, jd: float) -> np.ndarray:
        """相对地球的位置（AU）。相位取可复现假设值 M(J2000)=0。"""
        if not self.a_au:
            return np.zeros(3)
        e = self.e if self.e is not None else 0.0
        p = self.period_days or 1.0
        M = (2.0 * math.pi / p) * (jd - J2000_JD)
        E = solve_kepler(M, e)
        xv = self.a_au * (math.cos(E) - e)
        yv = self.a_au * math.sqrt(max(1.0 - e * e, 0.0)) * math.sin(E)
        u, v = self._satellite_plane_basis()
        return xv * u + yv * v

    def _relative_pos(self, jd: float) -> np.ndarray:
        """相对宿主星的开普勒位置（AU）"""
        if not self.a_au:
            return np.zeros(3)
        e = self.e if self.e is not None else 0.0
        i = self.incl_deg if self.incl_deg is not None else 0.0
        p = self.period
        if not p:
            # 无周期则由半长轴近似（绕 1 M☉ 恒星），缺失时标"未知"
            p = 365.25 * (self.a_au ** 1.5)
        n = 2.0 * math.pi / p
        M = n * (jd - J2000_JD)          # 可复现假设：M(J2000)=0
        return elements_to_position(self.a_au, e, i, 0.0, 0.0, M)

    # ---------- 速度（km/s，解析） ----------
    def velocity_at_jd(self, jd: float) -> np.ndarray:
        """速度（km/s）。系外行星缺质量按 1 M☉ 中心估算，标注于文档。"""
        if self.body_type in ("star", "host_star", "blackhole", "interstellar", "nearby_star"):
            return np.zeros(3)
        if self.body_type == "moon":
            # 卫星：对位置做中心差分（轨道面由母行星极轴定向，解析式不便直接套用）
            dt = 0.01
            p1 = self.position_at_jd(jd - dt)
            p2 = self.position_at_jd(jd + dt)
            return (p2 - p1) * (AU_KM / (2.0 * dt * 86400.0))
        if self.body_type == "satellite":
            # 人造卫星：同样用中心差分（周期仅数十分钟，取更小步长保证精度）
            dt = 0.001
            p1 = self.position_at_jd(jd - dt)
            p2 = self.position_at_jd(jd + dt)
            return (p2 - p1) * (AU_KM / (2.0 * dt * 86400.0))
        if self.body_type in ("planet_solar", "dwarf", "etno"):
            el = self.elements
            T = (jd - J2000_JD) / 36525.0
            a = el.a + el.a_dot * T
            e = el.e + el.e_dot * T
            L = (el.L + el.L_dot * T) % 360.0
            varpi = (el.varpi + el.varpi_dot * T) % 360.0
            M = (L - varpi) * DEG2RAD
            omega = varpi - (el.Omega + el.Omega_dot * T)
            return velocity_at_time(a, e, el.i + el.i_dot * T,
                                    el.Omega + el.Omega_dot * T, omega, M,
                                    self.period or 365.25 * a ** 1.5,
                                    M_SUN_KG)
        # 系外行星：相对宿主星速度（恒星自行忽略）
        if not self.a_au:
            return np.zeros(3)
        e = self.e if self.e is not None else 0.0
        i = self.incl_deg if self.incl_deg is not None else 0.0
        p = self.period or 365.25 * (self.a_au ** 1.5)
        M = (2.0 * math.pi / p) * (jd - J2000_JD)
        return velocity_at_time(self.a_au, e, i, 0.0, 0.0, M, p, 0.0)

    _host_mass_solar = 1.0     # 中心天体质量（缺恒星质量数据时按 1 M☉）

    # ---------- 详情字段（缺失返回"未知"） ----------
    def field_unknown(self, v, fmt="{:.6g}", suffix=""):
        if v is None:
            return "未知"
        try:
            return fmt.format(v) + suffix
        except (TypeError, ValueError):
            return "未知"


# ---------- 太阳系加载 ----------
def load_solar_system() -> list:
    bodies = []
    sun = Body(name=SUN["name"], body_type="star", grade=GRADE_A,
               color=SUN["color"], en_name=SUN["en"],
               radius_km=SUN["radius_km"], mass_earth=SUN["mass_earth"],
               host_pos=np.zeros(3), data_source="坐标系原点（日心）",
               method="—")
    bodies.append(sun)
    for name, d in SOLAR_PLANETS.items():
        el = d["elements"]
        btype = "dwarf" if name == "冥王星" else "planet_solar"
        pole = POLES.get(name)
        pole_ecl = _equatorial_to_ecliptic(pole[0], pole[1]) if pole else None
        bodies.append(Body(
            name=name, body_type=btype, grade=GRADE_A, color=d["color"],
            en_name=d["en"], host="太阳", elements=el,
            a_au=el.a, e=el.e, incl_deg=el.i,
            radius_km=d["radius_km"], mass_earth=d["mass_earth"],
            disc_year=d["disc_year"], method=d["method"],
            rot_period_days=ROTATION.get(name), pole_ecl=pole_ecl,
            data_source="JPL 近似轨道根数（Standish，1800–2050 适用）",
        ))
    return bodies


# ---------- 天然卫星加载 ----------
def load_moons(parents_by_name: dict) -> list:
    """加载主要天然卫星（挂到母行星 Body 上，位置=母行星 + 相对开普勒轨道）

    轨道与物理参数为真实值；轨道面近似取母行星赤道面（由真实极轴定向），
    月球取黄道面；沿轨道相位为可复现假设值 M(J2000)=0。
    """
    out = []
    for name, d in MOONS.items():
        parent = parents_by_name.get(d["parent"])
        if parent is None:
            continue
        pole = POLES.get(name)
        pole_ecl = _equatorial_to_ecliptic(pole[0], pole[1]) if pole else None
        out.append(Body(
            name=name, body_type="moon", grade=GRADE_B, color=d["color"],
            en_name=d["en"], host="太阳", parent=parent, parent_name=d["parent"],
            a_au=d["a_km"] / AU_KM, e=d["e"], incl_deg=d.get("incl_deg"),
            period_days=d["period_days"], radius_km=d["radius_km"],
            mass_earth=d.get("mass_earth"), plane=d.get("plane", "equator"),
            retro=bool(d.get("retro", False)), assumed_phase=True,
            rot_period_days=ROTATION.get(name), pole_ecl=pole_ecl,
            disc_year=d.get("disc_year"), method=d.get("method", "望远镜观测"),
            data_source=("NASA/JPL 卫星轨道与物理参数（真实值）；轨道面近似取母行星"
                         "赤道面，相位为可复现假设值 M(J2000)=0"),
        ))
    return out


# ---------- 人造卫星加载 ----------
def load_artificial_satellites(parents_by_name: dict) -> list:
    """加载地球人造卫星（挂到地球 Body 上，位置 = 地球 + 相对开普勒轨道）。

    半长轴 a、偏心率 e、倾角 i、周期 T 为实测值；升交点经度 Ω 取星座代表值，
    相位为可复现假设值 M(J2000)=0。轨道面按地球赤道面 + 真实倾角构造，
    故太阳同步轨道（i≈98°）、极轨、中轨、地球同步等能得到正确朝向。
    """
    earth = parents_by_name.get("地球")
    if earth is None:
        return []
    out = []
    for d in ARTIFICIAL_SATELLITES:
        out.append(Body(
            name=d["name"], body_type="satellite", grade=GRADE_B,
            color=d["color"], en_name=d.get("en", ""),
            host="太阳", parent=earth, parent_name="地球",
            a_au=d["a_km"] / AU_KM, e=d["e"], incl_deg=d["incl_deg"],
            period_days=d["period_days"],
            radius_km=(d["size_m"] / 2000.0) if d.get("size_m") else None,
            mass_earth=(d["mass_kg"] / M_EARTH_KG) if d.get("mass_kg") else None,
            plane="equator", retro=False, assumed_phase=True,
            disc_year=d.get("launched"), method=d.get("agency", "官方任务数据"),
            raan_deg=d.get("raan_deg", 0.0),
            sat_category=d.get("cat", ""), sat_note=d.get("note", ""),
            agency=d.get("agency", ""),
            data_source=("NORAD 两行根数长期平均 / 各机构官方任务页（a/e/i/T 为实测值，"
                         "Ω 为星座代表值，相位为可复现假设值 M(J2000)=0）"),
        ))
    return out


# ---------- 系外行星加载（优先本地 CSV 完整目录，否则内置真实子集） ----------
EXO_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exoplanets.csv")

# 最近一次加载中，因缺宿主恒星位置（无距离，无法三维定位）被跳过的条目数
EXO_SKIPPED_NO_HOST = 0

# CSV → pickle 二进制缓存：命中时跳过 pandas 导入（约 2.9s）与 CSV
# 解析（约 0.9s）；以 CSV 的 mtime+size+缓存版本号三方校验，任一
# 变化即失效重建。版本号与 Body 字段结构相关，字段变更时需 +1。
_EXO_CACHE_VERSION = 1


def _cache_dir() -> str:
    """可写的程序目录（打包后为 exe 目录，与设置文件同目录；源码运行时为项目根）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exo_cache_path() -> str:
    return os.path.join(_cache_dir(), "exoplanets_cache.pkl")


def _try_load_exo_cache():
    """读取系外行星二进制缓存；未命中 / 过期 / 损坏时返回 None。"""
    csv, cache = EXO_CSV_PATH, _exo_cache_path()
    if not (os.path.exists(csv) and os.path.exists(cache)):
        return None
    try:
        st = os.stat(csv)
        import pickle
        with open(cache, "rb") as f:
            data = pickle.load(f)
        if (not isinstance(data, dict)
                or data.get("version") != _EXO_CACHE_VERSION
                or data.get("csv_mtime") != int(st.st_mtime)
                or data.get("csv_size") != st.st_size):
            return None
        bodies = data.get("bodies")
        if not isinstance(bodies, list) or not bodies:
            return None
        if not all(getattr(b, "body_type", None) == "planet_exo" for b in bodies[:8]):
            return None
        return bodies, int(data.get("skipped_no_host", 0))
    except Exception:
        return None


def _save_exo_cache(bodies: list, skipped: int):
    """原子写入缓存（先写 .tmp 再 os.replace，中断不留半文件）。"""
    try:
        import pickle
        st = os.stat(EXO_CSV_PATH)
        data = {"version": _EXO_CACHE_VERSION,
                "csv_mtime": int(st.st_mtime), "csv_size": st.st_size,
                "bodies": bodies, "skipped_no_host": skipped}
        tmp = _exo_cache_path() + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, _exo_cache_path())
    except Exception:
        pass


def load_exoplanets() -> list:
    global EXO_SKIPPED_NO_HOST
    EXO_SKIPPED_NO_HOST = 0
    if os.path.exists(EXO_CSV_PATH):
        cached = _try_load_exo_cache()
        if cached is not None:
            bodies, EXO_SKIPPED_NO_HOST = cached
            return bodies
        try:
            bodies = _load_exo_csv(EXO_CSV_PATH)
            if bodies:
                _save_exo_cache(bodies, EXO_SKIPPED_NO_HOST)
                return bodies
        except Exception:
            pass   # CSV 损坏时回退内置子集，给出提示日志
    return _load_builtin_exoplanets()


def _load_builtin_exoplanets() -> list:
    global EXO_SKIPPED_NO_HOST
    bodies = []
    for d in BUILTIN_EXOPLANETS:
        ra, dec, dist = d.get("ra"), d.get("dec"), d.get("dist_pc")
        hpos = host_star_ecliptic_pos(ra, dec, dist) if dist else None
        if hpos is None:
            EXO_SKIPPED_NO_HOST += 1
            continue
        # 精度分级：凌星行星有倾角→B；RV/成像无倾角→C
        has_i = d.get("incl") is not None
        grade = GRADE_B if (has_i and hpos is not None) else GRADE_C
        bodies.append(Body(
            name=d["name"], body_type="planet_exo", grade=grade,
            color=tuple(d.get("color", (0.85, 0.75, 0.55))),
            host=d["host"], a_au=d.get("a"), e=d.get("ecc"),
            incl_deg=d.get("incl"), period_days=d.get("period"),
            radius_km=(d["radius_earth"] * 6371.0) if d.get("radius_earth") else None,
            mass_earth=d.get("mass_earth"),
            disc_year=d.get("year"), method=d.get("method", "未知"),
            dist_pc=dist, ra_deg=ra, dec_deg=dec, host_pos=hpos,
            assumed_phase=True,
            data_source="NASA Exoplanet Archive（内置精选子集）",
        ))
    return bodies


def _load_exo_csv(path: str) -> list:
    """加载 NASA Exoplanet Archive 官方完整 CSV（列名见 download_exoplanets.py）

    优先使用 pscomppars 复合列（pl_bmasse/pl_rade，地球单位；含宿主恒星参数）；
    若为旧版 ps 列（pl_bmassj/pl_radj，木星单位）则自动换算，保证兼容。
    """
    import pandas as pd
    global EXO_SKIPPED_NO_HOST
    df = pd.read_csv(path, comment="#", low_memory=False)
    colmap = {
        "pl_name": "name", "hostname": "host", "pl_orbper": "period",
        "pl_orbsmax": "a", "pl_orbeccen": "ecc", "pl_orbincl": "incl",
        "pl_bmasse": "mass_earth", "pl_rade": "radius_earth",
        "pl_bmassj": "mass_jup", "pl_radj": "radius_jup",
        "pl_dens": "density", "pl_eqt": "eq_temp",
        "disc_year": "year", "discoverymethod": "method",
        "sy_dist": "dist_pc", "ra": "ra", "dec": "dec",
        "sy_snum": "sys_star_count", "sy_pnum": "sys_planet_count",
        "st_teff": "host_teff", "st_rad": "host_radius_solar",
        "st_mass": "host_mass_solar", "st_spectype": "host_spec",
        "st_lum": "host_lum", "st_age": "host_age", "st_met": "host_met",
    }
    cols = {k: v for k, v in colmap.items() if k in df.columns}
    n = len(df)
    recs = {v: df[k].tolist() for k, v in cols.items()}
    bodies = []
    for i in range(n):
        g = lambda key: recs.get(key, [None] * n)[i]
        name = g("name")
        if not isinstance(name, str) or not name.strip():
            continue
        # 质量（地球质量）：优先 pl_bmasse，其次 pl_bmassj×317.8
        mass_earth = _safe_float(g("mass_earth"), 0)
        if mass_earth is None:
            mj = _safe_float(g("mass_jup"), 0)
            mass_earth = mj * 317.8 if mj is not None else None
        # 半径（km）：优先 pl_rade，其次 pl_radj
        radius_km = _safe_float(g("radius_earth"), 0)
        if radius_km is not None:
            radius_km *= 6371.0
        else:
            rj = _safe_float(g("radius_jup"), 0)
            radius_km = rj * 69911.0 if rj is not None else None
        ra = _safe_float(g("ra"), 0, 360)
        dec = _safe_float(g("dec"), -90, 90)
        dist = _safe_float(g("dist_pc"), 0)
        hpos = host_star_ecliptic_pos(ra, dec, dist) if dist else None
        if hpos is None:
            # 缺宿主恒星位置（无距离）：无法在三维空间定位，不予收录，
            # 否则会被堆到原点（太阳）形成虚假团块（科学诚实性）
            EXO_SKIPPED_NO_HOST += 1
            continue
        has_i = _safe_float(g("incl"), 0, 180) is not None
        grade = GRADE_B if (has_i and hpos is not None) else GRADE_C
        spec = g("host_spec")
        bodies.append(Body(
            name=name.strip(), body_type="planet_exo", grade=grade,
            color=(0.85, 0.75, 0.55), host=str(g("host") or "未知"),
            a_au=_safe_float(g("a"), 0), e=_safe_float(g("ecc"), 0, 1),
            incl_deg=_safe_float(g("incl"), 0, 180),
            period_days=_safe_float(g("period"), 0),
            radius_km=radius_km, mass_earth=mass_earth,
            disc_year=_safe_float(g("year"), 1900, 2100),
            method=str(g("method") or "未知"),
            dist_pc=dist, ra_deg=ra, dec_deg=dec, host_pos=hpos,
            assumed_phase=True,
            host_teff=_safe_float(g("host_teff"), 0),
            host_radius_solar=_safe_float(g("host_radius_solar"), 0),
            host_mass_solar=_safe_float(g("host_mass_solar"), 0),
            host_spec=(str(spec) if isinstance(spec, str) else ""),
            host_lum=_safe_float(g("host_lum")),
            host_age=_safe_float(g("host_age"), 0),
            host_met=_safe_float(g("host_met")),
            sys_planet_count=_safe_float(g("sys_planet_count"), 0),
            sys_star_count=_safe_float(g("sys_star_count"), 0),
            eq_temp=_safe_float(g("eq_temp"), 0),
            density=_safe_float(g("density"), 0),
            data_source="NASA Exoplanet Archive（官方完整目录 pscomppars）",
        ))
    return bodies


# ---------- 宿主恒星：从系外行星数据中提取每颗唯一的宿主恒星，建成独立 Body ----------
# 宿主恒星原本只是行星记录上的附属字段（st_teff / st_mass / st_rad / st_spectype …），
# 这里把它们提升为一等天体对象，可选中、查看详情、参与引力网格下陷。
# 同一宿主星的多颗行星参数一致，取首条记录作为恒星参数来源。

R_SUN_KM = 695700.0          # 太阳半径（km），宿主恒星半径换算用


def extract_host_stars(exoplanets: list) -> list:
    """从系外行星列表中提取唯一宿主恒星，建成 host_star 类型 Body 列表。

    同一宿主星的多条行星记录参数一致，取首条作为恒星参数来源；
    位置即该宿主星的 host_pos（真实三维位置）；
    颜色由光谱型近似（与 Hipparcos 星场调色一致）。
    """
    seen = {}
    for p in exoplanets:
        if p.body_type != "planet_exo":
            continue
        key = p.host or "未知宿主"
        if key in seen:
            continue
        if p.host_pos is None:
            continue           # 无法三维定位的宿主星同样跳过
        # 恒星半径（km）：宿主星半径（太阳半径）× R_SUN_KM
        radius_km = None
        if p.host_radius_solar:
            radius_km = p.host_radius_solar * R_SUN_KM
        # 质量（地球质量）：宿主星质量（太阳质量）× M_SUN_PER_EARTH
        mass_earth = None
        if p.host_mass_solar:
            mass_earth = p.host_mass_solar * M_SUN_PER_EARTH
        # 颜色：光谱型 → 近似色温
        color = _bv_to_color(None, p.host_spec or "")
        seen[key] = Body(
            name=key,
            body_type="host_star",
            grade=GRADE_B,
            color=color,
            en_name=key,
            host="",
            host_pos=p.host_pos.copy(),
            dist_pc=p.dist_pc,
            ra_deg=p.ra_deg,
            dec_deg=p.dec_deg,
            radius_km=radius_km,
            mass_earth=mass_earth,
            host_teff=p.host_teff,
            host_radius_solar=p.host_radius_solar,
            host_mass_solar=p.host_mass_solar,
            host_spec=p.host_spec or "",
            host_lum=p.host_lum,
            host_age=p.host_age,
            host_met=p.host_met,
            sys_planet_count=p.sys_planet_count,
            sys_star_count=p.sys_star_count,
            data_source=("NASA Exoplanet Archive（宿主恒星参数 pscomppars；"
                         "位置由 RA/Dec + 三角视差换算）"),
        )
    return list(seen.values())


# ---------- 黑洞 ----------

def schwarzschild_radius_km(mass_solar: float) -> float:
    """史瓦西半径（km）：Rs = 2GM/c² ≈ 2.953 km × M/M☉"""
    return 2.953 * mass_solar


def load_blackholes() -> list:
    """加载精选黑洞数据集（blackholes_builtin.py）→ blackhole 类型 Body 列表。

    黑洞不可见（无实体球渲染），但参与引力网格下陷，形成极深的时空凹陷。
    史瓦西半径作为参考值存入 radius_km，仅用于详情显示。
    """
    bodies = []
    for d in BUILTIN_BLACKHOLES:
        ra = d.get("ra_deg")
        dec = d.get("dec_deg")
        dist = d.get("dist_pc")
        hpos = host_star_ecliptic_pos(ra, dec, dist) if dist else None
        if hpos is None:
            continue
        ms = d.get("mass_solar")
        mass_earth = ms * M_SUN_PER_EARTH if ms else None
        rs_km = schwarzschild_radius_km(ms) if ms else None
        bodies.append(Body(
            name=d["name"],
            body_type="blackhole",
            grade=GRADE_B,
            color=(0.05, 0.05, 0.08),     # 近乎纯黑，仅标记用
            en_name=d.get("en_name", ""),
            host="",
            host_pos=hpos,
            dist_pc=dist,
            ra_deg=ra,
            dec_deg=dec,
            radius_km=rs_km,
            mass_earth=mass_earth,
            disc_year=d.get("disc_year"),
            method=d.get("bh_type", ""),
            bh_type=d.get("bh_type", ""),
            data_source=d.get("data_source", "未知"),
        ))
    return bodies


# ---------- 极端海外天体 / 远距矮行星 ----------
def load_etnos() -> list:
    """加载 ETNO 与远距矮行星（etno_builtin.py）→ Body 列表。

    IAU 认定矮行星（Eris/Makemake/Haumea）为 dwarf 类型（与 Pluto 一致），
    其余远距天体为 etno 类型。均使用 SolarElements 轨道根数（绕太阳运动）。
    """
    bodies = []
    for d in get_all_etnos():
        el = d["el"]
        # IAU 认定的 3 颗矮行星用 dwarf 类型；其余用 etno
        btype = "dwarf" if d["en"].startswith(("Eris", "Makemake", "Haumea")) else "etno"
        bodies.append(Body(
            name=d["name"], body_type=btype, grade=GRADE_B,
            color=d["color"], en_name=d["en"], host="太阳",
            elements=el, a_au=el.a, e=el.e, incl_deg=el.i,
            radius_km=d.get("radius_km"), mass_earth=d.get("mass_earth"),
            disc_year=d.get("disc_year"), method=d.get("method", ""),
            data_source=d.get("data_source", "MPC/JPL 轨道根数"),
        ))
    return bodies


# ---------- 近邻恒星（无系外行星的近邻恒星） ----------
def load_nearby_stars(existing_hosts: set = None) -> list:
    """加载近邻恒星（nearby_stars_builtin.py）→ Body 列表。

    跳过已在系外行星表中作为宿主恒星收录的恒星（去重）。
    位置由 RA/Dec + 距离换算（与宿主恒星一致）。
    """
    existing_hosts = existing_hosts or set()
    bodies = []
    for d in get_nearby_stars():
        # 去重：跳过已作为系外行星宿主星收录的恒星
        if d["name"] in existing_hosts or d.get("spec", "") == "":
            continue
        ra, dec, dist = d["ra_deg"], d["dec_deg"], d["dist_pc"]
        hpos = host_star_ecliptic_pos(ra, dec, dist)
        if hpos is None:
            continue
        spec = d.get("spec", "")
        color = _bv_to_color(None, spec)
        mass_earth = d["mass_solar"] * M_SUN_PER_EARTH if d.get("mass_solar") else None
        radius_km = d["radius_solar"] * R_SUN_KM if d.get("radius_solar") else None
        bodies.append(Body(
            name=d["name"], body_type="nearby_star", grade=GRADE_B,
            color=color, en_name=d.get("name", ""),
            host="", host_pos=hpos,
            dist_pc=dist, ra_deg=ra, dec_deg=dec,
            radius_km=radius_km, mass_earth=mass_earth,
            visible_mag=d.get("vmag"),
            host_spec=spec,
            host_teff=d.get("teff"),
            host_radius_solar=d.get("radius_solar"),
            host_mass_solar=d.get("mass_solar"),
            data_source=("RECONS / CNS5 近邻恒星表（Gaia DR3 视差换算距离）"),
        ))
    return bodies


# ---------- 星际天体 ----------
def _perihelion_pos(q_au, i_deg, Omega_deg, omega_deg):
    """从轨道根数计算近日点三维位置（AU，J2000 黄道系）。

    双曲轨道（e>1）标准开普勒方程不适用，但近日点位置仅由
    q、i、Omega、omega 决定，与偏心率无关。
    """
    q = q_au
    om = math.radians(omega_deg)
    i = math.radians(i_deg)
    Om = math.radians(Omega_deg)
    # 近日点在轨道面上: (q*cos(omega), q*sin(omega), 0)
    # 旋转序列: Rz(Omega) * Rx(i) * Rz(omega)
    x = q * math.cos(om)
    y = q * math.sin(om)
    # 绕 x 轴旋转 i
    y2 = y * math.cos(i)
    z2 = y * math.sin(i)
    # 绕 z 轴旋转 Omega
    X = x * math.cos(Om) - y2 * math.sin(Om)
    Y = x * math.sin(Om) + y2 * math.cos(Om)
    Z = z2
    return np.array([X, Y, Z], dtype=np.float64)


def load_interstellar_objects() -> list:
    """加载已确认星际天体（interstellar_objects.py）→ Body 列表。

    双曲轨道（e>1），以近日点位置作为静态定位。
    """
    bodies = []
    for d in INTERSTELLAR_OBJECTS:
        pos = _perihelion_pos(d["q_au"], d["i_deg"], d["Omega_deg"], d["omega_deg"])
        bodies.append(Body(
            name=d["name"], body_type="interstellar", grade=GRADE_B,
            color=(0.75, 0.70, 0.60), en_name=d["en"], host="太阳",
            host_pos=pos, a_au=d["q_au"], e=d["e"], incl_deg=d["i_deg"],
            disc_year=d.get("disc_year"),
            method="星际天体（双曲轨道 e>{})".format(d["e"]),
            radius_km=d.get("diameter_km"),
            data_source=d.get("data_source", "MPC 轨道根数"),
        ))
    return bodies


# ---------- 银河系背景恒星（ESA Hipparcos 官方星表，可选本地 CSV） ----------
# 与「天象/地表」面板共用的小亮星表（stars_builtin）不同：这里是给 3D 视口
# 用的稠密星场，仅用于渲染，不参与地平坐标计算（面板用 matplotlib 逐点绘制，
# 上千颗即明显卡顿，故两者分离）。
HIPPARCOS_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "hipparcos.csv")

# 渲染星等上限：越暗越多（V<=6.5 约 8.8k、<=8.0 约 41k、<=9.0 约 82k）。
# 取 9.0 以获得足够「银河带密度」；点精灵单次 draw call，GPU 负载可忽略。
HIPPARCOS_MAG_LIMIT = 9.0


def _bv_to_color(bv, spectral: str):
    """B-V 色指数（优先用光谱型）→ 恒星 RGB 近似色（黑体色温示意）。"""
    s = (spectral or "").strip().upper()[:1]
    table = {
        "O": (0.70, 0.80, 1.00), "B": (0.75, 0.84, 1.00),
        "A": (0.90, 0.93, 1.00), "F": (1.00, 0.98, 0.90),
        "G": (1.00, 0.95, 0.78), "K": (1.00, 0.85, 0.62),
        "M": (1.00, 0.74, 0.52),
    }
    if s in table:
        return table[s]
    if bv is None:
        return (0.90, 0.90, 0.95)
    if bv < 0.00:
        return (0.72, 0.81, 1.00)
    if bv < 0.30:
        return (0.84, 0.89, 1.00)
    if bv < 0.58:
        return (0.96, 0.96, 1.00)
    if bv < 0.81:
        return (1.00, 0.95, 0.82)
    if bv < 1.40:
        return (1.00, 0.86, 0.66)
    return (1.00, 0.75, 0.55)


def load_hipparcos(mag_limit: float = HIPPARCOS_MAG_LIMIT):
    """加载 ESA Hipparcos 主星表（本地 CSV）→ 3D 视口背景星场。

    返回 (data, max_dist)：
        data     —— (N,7) float32 顶点数组：x,y,z(AU) + r,g,b + size(px)，
                    坐标为 J2000 黄道系真实三维位置（方向 × 视差换算距离）；
        max_dist —— 最远恒星距离（AU），供渲染时自适应远裁剪面。
    文件不存在或损坏时返回 (None, 0.0)，视口回退到内置亮星表。
    """
    if not os.path.exists(HIPPARCOS_CSV_PATH):
        return None, 0.0
    import csv as _csv
    hip, ra_l, dec_l, mag_l, plx_l, bv_l, sp_l = [], [], [], [], [], [], []
    try:
        with open(HIPPARCOS_CSV_PATH, "r", encoding="utf-8", newline="") as fh:
            rows = (ln for ln in fh if not ln.startswith("#"))
            rd = _csv.reader(rows)
            next(rd, None)                       # 跳过表头
            for r in rd:
                if len(r) < 6:
                    continue
                try:
                    mag = float(r[3])
                    plx = float(r[4])
                except (ValueError, IndexError):
                    continue
                if not (plx > 0.0) or mag > mag_limit:
                    continue
                hip.append(r[0]); ra_l.append(float(r[1])); dec_l.append(float(r[2]))
                mag_l.append(mag); plx_l.append(plx)
                try:
                    bv_l.append(float(r[5]) if r[5] else None)
                except ValueError:
                    bv_l.append(None)
                sp_l.append(r[6] if len(r) > 6 else "")
    except Exception:
        return None, 0.0
    if not ra_l:
        return None, 0.0

    # 赤道(RA/Dec) → 黄道单位方向（与全软件统一的 J2000 黄道系一致，向量化）
    ra = np.radians(np.asarray(ra_l, dtype=np.float64))
    dec = np.radians(np.asarray(dec_l, dtype=np.float64))
    eps = math.radians(OBLIQUITY_J2000_DEG)
    cd, sd = np.cos(dec), np.sin(dec)
    dirs = np.stack([cd * np.cos(ra),
                     cd * np.sin(ra) * math.cos(eps) + sd * math.sin(eps),
                     -cd * np.sin(ra) * math.sin(eps) + sd * math.cos(eps)], axis=1)
    dist_au = (1000.0 / np.asarray(plx_l, dtype=np.float64)) * PARSEC_AU
    # 视差极小（<0.5 mas）的恒星换算距离可达数万秒差距，属测量噪声、不可靠，
    # 会无谓撑大渲染远裁剪面；按 2000 pc 上限截断（方向不变，仅收敛半径）。
    dist_au = np.minimum(dist_au, 2000.0 * PARSEC_AU)
    pos = dirs * dist_au[:, None]

    n = len(ra_l)
    size = np.clip(5.2 - np.asarray(mag_l, dtype=np.float64) * 1.15, 1.0, 11.0)
    color = np.array([_bv_to_color(bv_l[i], sp_l[i]) for i in range(n)],
                     dtype=np.float32)
    data = np.hstack([pos, color, size[:, None]]).astype(np.float32)
    return data, float(dist_au.max())


def load_all_bodies_staged(progress_cb=None) -> tuple:
    """加载全部天体（分阶段版本，供启动画面报告进度）。

    progress_cb(percent, stage_msg) 在阶段边界被调用，进度依次为
    5/10/25/40/65/80/95/100；传 None 时与 load_all_bodies 等价。
    返回 (bodies, stats)。
    """

    def _report(pct, msg):
        if progress_cb is not None:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    _report(5, "正在加载太阳系天体…")
    solar = load_solar_system()
    parents = {b.name: b for b in solar}
    _report(10, "太阳系天体就绪")
    moons = load_moons(parents)
    satellites = load_artificial_satellites(parents)
    _report(25, "卫星数据就绪")
    exo = load_exoplanets()
    _report(40, "系外行星就绪")
    host_stars = extract_host_stars(exo)
    blackholes = load_blackholes()
    _report(65, "宿主恒星与黑洞就绪")
    etnos = load_etnos()
    interstellars = load_interstellar_objects()
    _report(80, "外缘天体就绪")
    # 近邻恒星去重：跳过已作为系外行星宿主星收录的恒星
    existing_hosts = {hs.name for hs in host_stars}
    nearby_stars = load_nearby_stars(existing_hosts)
    _report(95, "近邻恒星就绪")
    stats = {
        "solar_count": len(solar),
        "moon_count": len(moons),
        "satellite_count": len(satellites),
        "exo_count": len(exo),
        "host_star_count": len(host_stars),
        "blackhole_count": len(blackholes),
        "etno_count": len(etnos),
        "interstellar_count": len(interstellars),
        "nearby_star_count": len(nearby_stars),
        "exo_skipped_no_host": EXO_SKIPPED_NO_HOST,
        "exo_source": "CSV 完整目录" if os.path.exists(EXO_CSV_PATH) else "内置精选子集",
    }
    _report(100, "数据加载完成")
    return (solar + moons + satellites + exo + host_stars + blackholes + etnos
            + interstellars + nearby_stars), stats


def load_all_bodies() -> tuple:
    """加载全部天体：太阳系 + 天然卫星 + 系外行星 + 宿主恒星 + 黑洞
    + 极端海外天体 + 近邻恒星 + 星际天体。

    返回 (bodies, stats)
    """
    return load_all_bodies_staged(None)


# ---------- 恒星系（系群）分组 ----------
def group_by_system(bodies) -> list:
    """把全部天体按「恒星系（系群）」归类：一颗宿主恒星 + 其行星。

    - 太阳系（is_solar=True）：太阳 + 8 行星 + 矮行星 + 天然卫星，恒为第 1 项；
    - 系外行星按宿主恒星（hostname）归并；同一宿主星的全部行星合成一个恒星系；
      宿主恒星 Body 挂在该系群下，可单独选中查看；
    - 黑洞单独归为「黑洞」顶层分组（不在恒星系树内，另行展示）；
    - 排序：行星数降序 → 名称升序（多行星系统靠前，便于浏览 TRAPPIST-1 等典型系）。

    返回 SystemGroup 列表（不含任何随机性，纯确定性归并）。
    """
    sun = None
    solar_planets, solar_moons, solar_sats, etnos = [], [], [], []
    exo = {}
    host_star_map = {}       # {hostname: host_star Body}
    blackholes, nearby_stars, interstellars = [], [], []
    for b in bodies:
        if b.body_type == "star":
            sun = b
        elif b.body_type == "host_star":
            host_star_map[b.name] = b
        elif b.body_type == "moon":
            solar_moons.append(b)
        elif b.body_type == "satellite":
            solar_sats.append(b)
        elif b.body_type in ("planet_solar", "dwarf"):
            solar_planets.append(b)
        elif b.body_type == "etno":
            etnos.append(b)
        elif b.body_type == "planet_exo":
            exo.setdefault(b.host or "未知宿主", []).append(b)
        elif b.body_type == "blackhole":
            blackholes.append(b)
        elif b.body_type == "nearby_star":
            nearby_stars.append(b)
        elif b.body_type == "interstellar":
            interstellars.append(b)

    groups = []
    if sun is not None or solar_planets:
        solar_planets.sort(key=lambda b: (b.a_au is None, b.a_au or 0.0))
        groups.append(SystemGroup(
            host="太阳", is_solar=True, star=sun,
            planets=solar_planets, moons=solar_moons, satellites=solar_sats,
            spec="G2V", planet_count=len(solar_planets), star_count=1,
            host_teff=5772.0, host_radius_solar=1.0, host_mass_solar=1.0))

    # ETNO 单独分组（均绕太阳运动，但位于太阳系外缘）
    if etnos:
        etnos.sort(key=lambda b: (b.a_au is None, b.a_au or 0.0))
        etno_group = SystemGroup(
            host="极端海外天体", is_solar=False,
            planets=etnos,
            spec="—", planet_count=0, star_count=len(etnos),
        )
        groups.append(etno_group)

    # 近邻恒星单独分组
    if nearby_stars:
        nearby_stars.sort(key=lambda b: (b.dist_pc is None, b.dist_pc or 0.0))
        ns_group = SystemGroup(
            host="近邻恒星", is_solar=False,
            planets=nearby_stars,
            spec="—", planet_count=0, star_count=len(nearby_stars),
        )
        groups.append(ns_group)

    # 星际天体单独分组
    if interstellars:
        is_group = SystemGroup(
            host="星际天体", is_solar=False,
            planets=interstellars,
            spec="—", planet_count=0, star_count=len(interstellars),
        )
        groups.append(is_group)

    exo_groups = []
    for host, plist in exo.items():
        plist.sort(key=lambda b: (b.a_au is None, b.a_au or 0.0))
        first = plist[0]
        exo_groups.append(SystemGroup(
            host=host, is_solar=False,
            star=host_star_map.get(host),
            planets=plist,
            spec=first.host_spec or "", dist_pc=first.dist_pc,
            planet_count=first.sys_planet_count, star_count=first.sys_star_count,
            host_teff=first.host_teff, host_radius_solar=first.host_radius_solar,
            host_mass_solar=first.host_mass_solar, host_lum=first.host_lum))
    exo_groups.sort(key=lambda g: (-g.n_planets, g.host.lower()))

    # 黑洞单独作为一个特殊系群（便于在天体树中独立分组展示）
    if blackholes:
        bh_group = SystemGroup(
            host="黑洞", is_solar=False,
            planets=[],  # 黑洞不是行星，用 star 字段承载
            spec="—",
            planet_count=0,
            star_count=len(blackholes),
            host_teff=None, host_radius_solar=None, host_mass_solar=None,
        )
        # 把黑洞列表暂存到 planets 字段里（由树面板识别 body_type 做特殊处理）
        bh_group.planets = blackholes
        groups.append(bh_group)

    return groups + exo_groups