"""
solar_system.py —— 太阳系内置数据（客观真实）

轨道根数来源：JPL / Caltech《Keplerian Elements for Approximate Positions of the
Major Planets》（E.M. Standish），J2000.0 历元 + 每世纪变率，适用期 1800–2050 AD，
内行星位置误差约 arcmin 量级（等级 A：真实三维）。

物理参数（半径/质量）来源：NASA JPL 行星事实表。
地球采用"地月系质心（EM Bary）"轨道（JPL 表约定），文档中说明。
"""
from dataclasses import dataclass, field

# JPL 近似轨道根数：
#   a(AU), a_dot(AU/世纪), e, e_dot, i(度), i_dot, L(度), L_dot,
#   varpi(近日点经度,度), varpi_dot, Omega(升交点经度,度), Omega_dot
@dataclass
class SolarElements:
    a: float; a_dot: float
    e: float; e_dot: float
    i: float; i_dot: float
    L: float; L_dot: float
    varpi: float; varpi_dot: float
    Omega: float; Omega_dot: float


SOLAR_PLANETS = {
    "水星": dict(
        en="Mercury", elements=SolarElements(
            0.38709927, 0.00000037, 0.20563593, 0.00001906, 7.00497902, -0.00594749,
            252.25032350, 149472.67411175, 77.45779628, 0.16047689, 48.33076593, -0.12534081),
        radius_km=2439.7, mass_earth=0.0553, color=(0.62, 0.60, 0.58),
        disc_year=None, method="古代观测"),
    "金星": dict(
        en="Venus", elements=SolarElements(
            0.72333566, 0.00000390, 0.00677672, -0.00004107, 3.39467605, -0.00078890,
            181.97909950, 58517.81538729, 131.60246718, 0.00268329, 76.67984255, -0.27769418),
        radius_km=6051.8, mass_earth=0.815, color=(0.93, 0.83, 0.60),
        disc_year=None, method="古代观测"),
    "地球": dict(
        en="Earth (EM Bary)", elements=SolarElements(
            1.00000261, 0.00000562, 0.01671123, -0.00004392, -0.00001531, -0.01294668,
            100.46457166, 35999.37244981, 102.93768193, 0.32327364, 0.0, 0.0),
        radius_km=6371.0, mass_earth=1.0, color=(0.35, 0.55, 0.90),
        disc_year=None, method="古代观测"),
    "火星": dict(
        en="Mars", elements=SolarElements(
            1.52371034, 0.00001847, 0.09339410, 0.00007882, 1.84969142, -0.00813131,
            -4.55343205, 19140.30268499, -23.94362959, 0.44441088, 49.55953891, -0.29257343),
        radius_km=3389.5, mass_earth=0.107, color=(0.80, 0.42, 0.28),
        disc_year=None, method="古代观测"),
    "木星": dict(
        en="Jupiter", elements=SolarElements(
            5.20288700, -0.00011607, 0.04838624, -0.00013253, 1.30439695, -0.00183714,
            34.39644051, 3034.74612775, 14.72847983, 0.21252668, 100.47390909, 0.20469106),
        radius_km=69911.0, mass_earth=317.8, color=(0.85, 0.72, 0.55),
        disc_year=None, method="古代观测"),
    "土星": dict(
        en="Saturn", elements=SolarElements(
            9.53667594, -0.00125060, 0.05386179, -0.00050991, 2.48599187, 0.00193609,
            49.95424423, 1222.49362201, 92.59887831, -0.41897216, 113.66242448, -0.28867794),
        radius_km=58232.0, mass_earth=95.2, color=(0.88, 0.80, 0.58),
        disc_year=None, method="古代观测"),
    "天王星": dict(
        en="Uranus", elements=SolarElements(
            19.18916464, -0.00196176, 0.04725744, -0.00004397, 0.77263783, -0.00242939,
            313.23810451, 428.48202785, 170.95427630, 0.40805281, 74.01692503, 0.04240589),
        radius_km=25362.0, mass_earth=14.5, color=(0.55, 0.80, 0.82),
        disc_year=1781, method="望远镜发现（W. Herschel）"),
    "海王星": dict(
        en="Neptune", elements=SolarElements(
            30.06992276, 0.00026291, 0.00859048, 0.00005105, 1.77004347, 0.00035372,
            -55.12002969, 218.45945325, 44.96476227, -0.32241464, 131.78422574, -0.00508664),
        radius_km=24622.0, mass_earth=17.1, color=(0.35, 0.48, 0.85),
        disc_year=1846, method="轨道预测发现（Le Verrier / Galle）"),
    "冥王星": dict(
        en="Pluto (dwarf planet)", elements=SolarElements(
            39.48211675, -0.00031596, 0.24882730, 0.00005170, 17.14001206, 0.00004818,
            238.92903833, 145.20780515, 224.06891629, -0.04062942, 110.30393684, -0.01183482),
        radius_km=1188.3, mass_earth=0.00218, color=(0.76, 0.68, 0.62),
        disc_year=1930, method="望远镜发现（C. Tombaugh）"),
}

# 太阳（中心天体，坐标系原点）
SUN = dict(
    name="太阳", en="Sun", body_type="star",
    radius_km=695700.0, mass_earth=333000.0, color=(1.0, 0.82, 0.35))

# 可视化参考环带（示意区域，非个体天体——区域位置真实，界面明确标注"示意"）
REFERENCE_BELTS = [
    dict(name="小行星带", a_min=2.2, a_max=3.2, color=(0.5, 0.5, 0.45),
         note="主小行星带真实分布区域：2.2–3.2 AU（示意区域，非个体天体）"),
    dict(name="柯伊伯带", a_min=30.0, a_max=50.0, color=(0.4, 0.55, 0.6),
         note="柯伊伯带真实分布区域：30–50 AU（示意区域，非个体天体）"),
]

# JPL 星历适用范围（界面提示用）：1800–2050 AD
EPHEMERIS_VALID_YEARS = (1800, 2050)


# ---------- 主要天然卫星（客观真实参数） ----------
# 轨道与物理参数来源：NASA/JPL Solar System Dynamics 卫星表、IAU 行星卫星工作组。
# 建模约定（科学诚实性）：
#   * 轨道面近似取**母行星赤道面**（plane="equator"，由 POLES 的真实极轴定向），
#     月球轨道接近黄道面故取 plane="ecliptic"；
#   * 沿轨道相位（平近点角）未逐颗测定 → 取可复现假设值 M(J2000)=0（非随机数），
#     只影响当前瞬时位置，不影响轨道形状/半长轴/周期；
#   * 海卫一 Triton 为逆行轨道（retro=True）。
MOONS = {
    "月球": dict(en="Moon", parent="地球", a_km=384400.0, e=0.0549,
                 incl_deg=5.145, period_days=27.3217, radius_km=1737.4,
                 mass_earth=0.012300, color=(0.72, 0.70, 0.66),
                 plane="ecliptic", retro=False, disc_year=None, method="古代观测"),
    "火卫一": dict(en="Phobos", parent="火星", a_km=9376.0, e=0.0151,
                   incl_deg=1.08, period_days=0.31891, radius_km=11.27,
                   mass_earth=1.78e-9, color=(0.55, 0.50, 0.45),
                   disc_year=1877, method="望远镜发现（A. Hall）"),
    "火卫二": dict(en="Deimos", parent="火星", a_km=23463.0, e=0.0002,
                   incl_deg=1.79, period_days=1.263, radius_km=6.2,
                   mass_earth=4.0e-10, color=(0.60, 0.55, 0.48),
                   disc_year=1877, method="望远镜发现（A. Hall）"),
    "木卫一": dict(en="Io", parent="木星", a_km=421700.0, e=0.0041,
                   incl_deg=0.05, period_days=1.7691, radius_km=1821.6,
                   mass_earth=0.014950, color=(0.92, 0.85, 0.45),
                   disc_year=1610, method="望远镜发现（伽利略）"),
    "木卫二": dict(en="Europa", parent="木星", a_km=671034.0, e=0.009,
                   incl_deg=0.47, period_days=3.5512, radius_km=1560.8,
                   mass_earth=0.008040, color=(0.85, 0.80, 0.72),
                   disc_year=1610, method="望远镜发现（伽利略）"),
    "木卫三": dict(en="Ganymede", parent="木星", a_km=1070412.0, e=0.0013,
                   incl_deg=0.20, period_days=7.1546, radius_km=2634.1,
                   mass_earth=0.024810, color=(0.65, 0.60, 0.55),
                   disc_year=1610, method="望远镜发现（伽利略）"),
    "木卫四": dict(en="Callisto", parent="木星", a_km=1882709.0, e=0.0074,
                   incl_deg=0.19, period_days=16.689, radius_km=2410.3,
                   mass_earth=0.018010, color=(0.45, 0.40, 0.36),
                   disc_year=1610, method="望远镜发现（伽利略）"),
    "土卫六": dict(en="Titan", parent="土星", a_km=1221870.0, e=0.0288,
                   incl_deg=0.35, period_days=15.945, radius_km=2574.7,
                   mass_earth=0.022520, color=(0.85, 0.62, 0.30),
                   disc_year=1655, method="望远镜发现（C. Huygens）"),
    "土卫二": dict(en="Enceladus", parent="土星", a_km=237948.0, e=0.0047,
                   incl_deg=0.02, period_days=1.3702, radius_km=252.1,
                   mass_earth=1.81e-5, color=(0.92, 0.94, 0.95),
                   disc_year=1789, method="望远镜发现（W. Herschel）"),
    "天卫三": dict(en="Titania", parent="天王星", a_km=435910.0, e=0.0011,
                   incl_deg=0.34, period_days=8.7062, radius_km=788.4,
                   mass_earth=5.69e-4, color=(0.62, 0.60, 0.58),
                   disc_year=1787, method="望远镜发现（W. Herschel）"),
    "天卫四": dict(en="Oberon", parent="天王星", a_km=583520.0, e=0.0014,
                   incl_deg=0.06, period_days=13.4632, radius_km=761.4,
                   mass_earth=5.15e-4, color=(0.55, 0.52, 0.50),
                   disc_year=1787, method="望远镜发现（W. Herschel）"),
    "海卫一": dict(en="Triton", parent="海王星", a_km=354759.0, e=0.000016,
                   incl_deg=156.9, period_days=5.8769, radius_km=1353.4,
                   mass_earth=3.58e-3, color=(0.80, 0.78, 0.75),
                   plane="equator", retro=True, disc_year=1846,
                   method="望远镜发现（W. Lassell）"),
    "冥卫一": dict(en="Charon", parent="冥王星", a_km=19591.0, e=0.0002,
                   incl_deg=0.08, period_days=6.3872, radius_km=606.0,
                   mass_earth=2.66e-4, color=(0.68, 0.66, 0.63),
                   disc_year=1978, method="望远镜发现（J. Christy）"),
}

# 行星自转极轴方向（IAU/J2000 赤道坐标 RA/Dec，度）
# 来源：IAU Working Group on Cartographic Coordinates and Rotational Elements (WGCCRE 2015)
# 用途：① 行星环与卫星轨道面定向；② 自转轴三维朝向与转轴倾角计算
POLES = {
    "水星": (281.0103, 61.4155),
    "金星": (272.76, 67.16),
    "地球": (0.0, 90.0),
    "火星": (317.681, 52.887),
    "木星": (268.057, 64.495),
    "土星": (40.589, 83.537),
    "天王星": (257.311, -15.175),
    "海王星": (299.36, 43.46),
    "冥王星": (132.993, -6.163),
    # 月球：IAU WGCCRE 2015 极轴常数项 α₀=269.9949° δ₀=66.5392°（J2000）
    # 用途：地表视角的月球自转轴；其余天然卫星缺极轴时按「潮汐锁定取轨道面法向」回退
    "月球": (269.9949, 66.5392),
}

# 行星自转周期（恒星日，单位：天；负值 = 逆行自转）
# 来源：IAU WGCCRE 2015 / NASA JPL 行星事实表（恒星日 sidereal rotation period）
ROTATION = {
    "水星": 58.6462,
    "金星": -243.025,      # 逆行自转
    "地球": 0.99726968,
    "火星": 1.02595676,
    "木星": 0.41354,
    "土星": 0.44401,
    "天王星": -0.71833,    # 逆行自转（转轴几乎躺倒）
    "海王星": 0.67125,
    "冥王星": -6.38723,    # 逆行自转
    # 月球：恒星日自转周期 = 恒星月（潮汐锁定），IAU WGCCRE 2015 自转速率
    "月球": 27.321661,
}

# 行星环（内/外半径以母行星半径为单位的真实值；来源：NASA 行星环表）
# profile="saturn" 时按真实环带结构（D/C/B/卡西尼环缝/A）烘焙径向透明度
RINGS = {
    "木星": dict(inner=1.40, outer=3.11, color=(0.74, 0.68, 0.60), alpha=0.16,
                 bands="jupiter",
                 note="木星环系（晕环 + 主环 + 木卫五/木卫十四薄纱环，1979 旅行者 1 号发现）"),
    "土星": dict(inner=1.11, outer=2.269, color=(0.88, 0.82, 0.68), alpha=0.62,
                 profile="saturn",
                 note="土星主环系（D/C/B/卡西尼环缝/A 环，真实径向结构）"),
    "天王星": dict(inner=1.478, outer=4.030, color=(0.62, 0.74, 0.84), alpha=0.42,
                   bands="uranus",
                   note="天王星环系（1977 掩星发现，13 条窄暗环，ε 环最亮最宽，μ 环最外侧最宽）"),
    "海王星": dict(inner=1.68, outer=2.55, color=(0.58, 0.66, 0.76), alpha=0.30,
                   bands="neptune",
                   note="海王星环系（1989 旅行者 2 号确认，Galle/Le Verrier/Lassell/Arago/Adams）"),
}

# 离散窄环的环带结构：[(内半径, 外半径, 相对不透明度 0–1), ...]（以母行星半径为单位）
# 来源：NASA Planetary Rings Fact Sheet / JPL Solar System Dynamics
RING_BANDS = {
    # 木星：晕环（内、厚、极暗）→ 主环（最亮）→ 两段薄纱环（外、极暗）
    "jupiter": [
        (1.400, 1.710, 0.10),    # Halo 晕环
        (1.710, 1.810, 1.00),    # Main 主环（最亮）
        (1.810, 2.550, 0.10),    # Amalthea 薄纱环（木卫五）
        (2.550, 3.110, 0.05),    # Thebe 薄纱环（木卫十四）
    ],
    # 天王星：13 条窄环（ζ/6/5/4/α/β/η/γ/δ/λ/ε/ν/μ），ε 环最亮最宽
    # 半径取自 NASA Planetary Rings Fact Sheet（R_U = 25559 km），换算为母行星半径倍数
    "uranus": [
        (1.478, 1.484, 0.15),    # ζ（1986U2R，最内侧暗环）
        (1.635, 1.640, 0.50),    # 6
        (1.649, 1.654, 0.50),    # 5
        (1.664, 1.669, 0.50),    # 4
        (1.748, 1.753, 0.55),    # α
        (1.792, 1.797, 0.55),    # β
        (1.856, 1.861, 0.45),    # η
        (1.889, 1.894, 0.60),    # γ
        (1.899, 1.904, 0.55),    # δ
        (1.953, 1.958, 0.30),    # λ
        (1.995, 2.010, 1.00),    # ε（最亮最宽）
        (2.586, 2.735, 0.10),    # ν（宽而暗的尘埃环）
        (3.365, 4.030, 0.08),    # μ（最外侧宽尘埃环）
    ],
    # 海王星：Galle / Le Verrier / Lassell（宽薄尘埃带）/ Arago / Adams
    "neptune": [
        (1.688, 1.696, 0.35),    # Galle
        (2.144, 2.152, 0.40),    # Le Verrier
        (2.152, 2.306, 0.07),    # Lassell（宽薄尘埃带）
        (2.306, 2.314, 0.35),    # Arago
        (2.536, 2.544, 0.70),    # Adams（含弧段）
    ],
}


def saturn_ring_alpha(r: float) -> float:
    """土星环径向透明度剖面（r 以土星半径为单位）——真实环带结构"""
    if r < 1.239:
        return 0.10          # D 环（极暗）
    if r < 1.527:
        return 0.34          # C 环（暗）
    if r < 1.951:
        return 1.00          # B 环（最亮最密）
    if r < 2.025:
        return 0.06          # 卡西尼环缝
    return 0.72              # A 环（含恩克环缝，简化）


def ring_bands_for(name: str):
    """返回行星环的离散环带列表 [(r0, r1, alpha), ...]（母行星半径为单位）。

    profile="saturn" 的行星（土星）由连续剖面细分成 60 段环带，
    其余行星取 RING_BANDS 中显式定义的窄环/环带。无数据返回 None。
    """
    cfg = RINGS.get(name)
    if not cfg:
        return None
    key = cfg.get("bands")
    if key:
        return list(RING_BANDS.get(key, []))
    if cfg.get("profile") == "saturn":
        inner, outer, n = cfg["inner"], cfg["outer"], 60
        return [(inner + (outer - inner) * k / n,
                 inner + (outer - inner) * (k + 1) / n,
                 saturn_ring_alpha(0.5 * (2 * inner + (outer - inner) * (2 * k + 1) / n)))
                for k in range(n)]
    return None