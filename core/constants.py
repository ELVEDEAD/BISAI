"""
constants.py —— 物理与天文常数、单位规范、尺度层级定义

单位约定（全软件统一，见 08_数据来源与精度说明.md）：
    距离：AU（天文单位）
    时间：天（儒略日差值）
    质量：太阳质量（M_sun）
    角度：度（存储与显示），计算时转换为弧度

坐标系约定（全软件统一）：
    太阳系天体：J2000 黄道坐标系（日心）
    系外行星及恒星：J2000 赤道坐标(RA/Dec) → 经黄赤交角旋转 → J2000 黄道坐标系
    所有渲染、轨道计算、相对运动分析统一使用同一坐标系，保证模块间位置一致。
"""
import math

# ---------- 基本常数（来源：IAU 2015 / NASA JPL） ----------
AU_M = 1.495978707e11          # 1 天文单位 = 米（精确值）
AU_KM = 1.495978707e8          # 1 天文单位 = 千米（精确值）
PARSEC_AU = 206264.806247096   # 1 秒差距（pc）= AU
LY_AU = 63241.07708807546      # 1 光年 = AU
JULIAN_YEAR_DAYS = 365.25      # 儒略年（天）
J2000_JD = 2451545.0           # J2000.0 历元（2000-01-01 12:00 TT）

# 质量（kg）
M_SUN_KG = 1.98892e30
M_EARTH_KG = 5.9722e24
M_JUPITER_KG = 1.898e27
M_SUN_PER_EARTH = M_SUN_KG / M_EARTH_KG      # 1 太阳质量 = 地球质量数
M_SUN_PER_JUP = M_SUN_KG / M_JUPITER_KG      # 1 太阳质量 = 木星质量数

# 半径（km）
R_SUN_KM = 695700.0
R_EARTH_KM = 6371.0
R_JUPITER_KM = 69911.0

# 引力常数（SI），用于速度估算
G_SI = 6.67430e-11

# 辐射与原子常数（SI 精确值，来源：CODATA 2018 / SI 2019 定义）
C_LIGHT_M_S = 299792458.0          # 光速（m/s，精确值）
H_PLANCK_J_S = 6.62607015e-34      # 普朗克常数（J·s，精确值）
K_B_J_PER_K = 1.380649e-23         # 玻尔兹曼常数（J/K，精确值）
SIGMA_SB = 5.670374419e-8          # 斯特藩-玻尔兹曼常数（W·m⁻²·K⁻⁴）
M_HYDROGEN_KG = 1.6735575e-27      # 氢原子质量（kg）
WIEN_B_NM_K = 2.897771955e6        # 维恩位移定律常数（nm·K）

# J2000 平黄赤交角（度），用于赤道坐标 → 黄道坐标转换
OBLIQUITY_J2000_DEG = 23.4392911

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

# ---------- 精度分级（科学诚实性要求，见 4.5 节） ----------
GRADE_A = "A"   # 真实三维：太阳系天体，JPL 近似星历，三维坐标可靠
GRADE_B = "B"   # 近似三维：有较完整轨道根数/实测距离的系外行星
GRADE_C = "C"   # 投影近似：参数大量缺失，倾角按 0 或假设值处理

GRADE_DESCRIPTION = {
    "A": "等级A（真实三维）：位置基于 JPL 近似星历（1800–2050 年有效），三维坐标真实可靠。",
    "B": "等级B（近似三维）：轨道根数/恒星距离来自实测，三维位置为近似估算。",
    "C": "等级C（投影近似）：轨道倾角等参数未知，按假设值投影显示，仅反映周期与尺度。",
}

# ---------- 尺度层级（对数缩放，见 3.3 节） ----------
SCALE_TIERS = [
    ("行星系统级", 1e-8, 1e-2),      # 1e-8 AU ≈ 1500 km（行星表面~卫星系）
    ("恒星系级",  1e-2, 1e3),        # 行星轨道 ~ 太阳系边缘（~1e3 AU）
    ("星际级",    1e3, 1e7),         # 邻近恒星（pc 量级）~ 银河系局部
    ("银河系级",  1e7, 1e10),        # 银河系尺度（~1e9 AU ≈ 1.5e4 pc）
]

def scale_tier_name(dist_au: float) -> str:
    """根据当前视距（AU）返回尺度层级名称"""
    d = max(abs(dist_au), 1e-12)
    for name, lo, hi in SCALE_TIERS:
        if lo <= d < hi:
            return name
    if d < SCALE_TIERS[0][1]:
        return SCALE_TIERS[0][0]
    return SCALE_TIERS[-1][0]

# 光速：1 AU 的光行时间（秒），来源：IAU 定义 c = 299792458 m/s，AU = 1.495978707e11 m
LIGHT_TIME_S_PER_AU = 499.004783836


def format_light_time(au: float) -> str:
    """光行时间格式化：距离(AU) → 光传播所需时间（秒/分/小时/天/年）"""
    t = abs(au) * LIGHT_TIME_S_PER_AU
    if t < 1e-3:
        return f"{t * 1e6:.2f} 微秒"
    if t < 60.0:
        return f"{t:.3f} 秒"
    if t < 3600.0:
        return f"{t / 60.0:.2f} 分"
    if t < 86400.0:
        return f"{t / 3600.0:.2f} 小时"
    if t < 86400.0 * 365.25:
        return f"{t / 86400.0:.2f} 天"
    return f"{t / (86400.0 * 365.25):.3f} 年"


def format_distance(au: float, unit: str = "auto") -> str:
    """距离格式化显示：auto 时按量级自动选择单位，数值带单位"""
    d = abs(au)
    if unit == "AU":
        return f"{au:.4g} AU"
    if unit == "km":
        return f"{au * AU_KM:.4g} km"
    if unit == "ly":
        return f"{au / LY_AU:.4g} 光年"
    # auto
    if d < 1e-2:
        return f"{au * AU_KM:,.0f} km"
    if d < 1e3:
        return f"{au:.4g} AU"
    if d < LY_AU:
        return f"{d / PARSEC_AU:.4g} pc"
    return f"{d / LY_AU:.4g} 光年"