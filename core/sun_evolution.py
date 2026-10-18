"""
sun_evolution.py —— 太阳物理演化模型（年龄 → 半径/光度/温度/质量）

数据来源与近似级别（文档「太阳系物理演化」第六节要求）：
- 演化节点取自 Schröder & Connon Smith (2008, MNRAS 386, 155) 太阳演化模型：
  RGB tip 半径约 256 R☉（≈1.2 AU）、AGB 终质量 0.546 M☉；
- 光度不由节点表直接给出，而由斯特藩-玻尔兹曼定律 L = R²·(T/T☉)⁴ 从半径与
  温度派生，保证三者物理自洽；
- 白矮星冷却按 Mestel 冷却律（T ∝ t^-0.4 量级）取离散节点；
- 主序段光度每 11 亿年约 +10%、半径约 +6%（标准太阳演化近似）。

时间基准：age_gyr 为太阳绝对年龄（当前 4.58 Gyr）。演化推进 = 仿真时间超出
当前的年数。过去（age < 4.58）不模拟，钳制到当前值。

轨道外移（行星命运「机制二」）：太阳 AGB 质量损失使行星轨道角动量守恒外移，
a ∝ M^(-k)。k=1 为绝热质量损失标准情形；「逃逸」模式取 k=1.2（更彻底的质量
损失/更早损失），使地球轨道在 RGB tip 期（R≈1.2 AU）恰好外移到贴边掠过；
「吞噬」模式按 Schröder & Connon Smith (2008)：潮汐拖拽（τ ∝ R_sun⁵/d⁶，
膨胀后急剧增强）压过外移，地球净内移，被吞噬。潮汐衰减为净效应参数化，
非逐项积分（近似级别：定性正确）。
"""
import bisect
from dataclasses import dataclass

from core.constants import AU_KM, R_SUN_KM, J2000_JD

# 太阳当前年龄（Gyr）；主序剩余约 5.05 Gyr（S&C 2008）
SUN_NOW_AGE_GYR = 4.58
SOLAR_RADIUS_AU = R_SUN_KM / AU_KM          # ≈ 0.00465 AU

# 阶段常量（字符串，便于 i18n 与日志）
PHASE_MAIN_SEQUENCE = "主序"
PHASE_SUBGIANT_RGB = "红巨星分支"
PHASE_HORIZONTAL_BRANCH = "水平分支（核心氦燃烧）"
PHASE_AGB = "渐近巨星分支"
PHASE_PLANETARY_NEBULA = "行星状星云"
PHASE_WHITE_DWARF = "白矮星"

# 演化节点表：(age_gyr, R☉, Teff K, M☉)
# 光度由 L = R²·(T/5778)⁴ 派生。关键节点见模块 docstring。
_NODES = [
    (4.58, 1.000, 5778.0, 1.000),    # 现在
    (6.00, 1.072, 5750.0, 1.000),    # 主序：每 ~1.1 Gyr L+10%、R+6%
    (7.50, 1.155, 5720.0, 1.000),
    (9.63, 1.400, 6300.0, 1.000),    # 主序末端（现在 +50.5 亿年；L≈2.5 L☉）
    (10.10, 2.300, 5100.0, 1.000),   # 亚巨星
    (10.60, 8.000, 4700.0, 1.000),   # RGB 上升
    (11.20, 60.00, 4000.0, 0.980),   # RGB（太阳风质量损失开始）
    (11.80, 140.0, 3100.0, 0.900),   # RGB 后期
    (12.18, 256.0, 2700.0, 0.848),   # RGB tip：R≈1.2 AU（S&C 2008）
    (12.22, 10.00, 4600.0, 0.848),   # 氦闪后水平分支（核心氦燃烧，简化陡降）
    (12.32, 40.00, 3600.0, 0.700),   # E-AGB
    (12.38, 170.0, 3000.0, 0.546),   # AGB tip（热脉动峰值；S&C 2008 终质量 0.546 M☉）
    (12.40, 0.020, 90000.0, 0.546),  # 行星状星云抛射后·年轻白矮星（中心星）
    (12.50, 0.013, 50000.0, 0.546),  # 白矮星（约地球大小）
    (13.00, 0.013, 30000.0, 0.546),
    (14.00, 0.013, 20000.0, 0.546),
    (16.00, 0.013, 12000.0, 0.546),
    (20.00, 0.013, 8000.0, 0.546),   # Mestel 冷却律近似
]

_AGES = [n[0] for n in _NODES]
_T_SUN = 5778.0


@dataclass(frozen=True)
class SunState:
    """某一年龄下太阳的状态（单位：太阳单位 / K）"""
    age_gyr: float
    radius_solar: float
    luminosity_solar: float
    teff_k: float
    mass_solar: float
    phase: str

    @property
    def radius_au(self) -> float:
        return self.radius_solar * SOLAR_RADIUS_AU


def _phase_of(age: float) -> str:
    if age < 9.63:
        return PHASE_MAIN_SEQUENCE
    if age <= 12.18:
        return PHASE_SUBGIANT_RGB
    if age < 12.30:
        return PHASE_HORIZONTAL_BRANCH
    if age < 12.40:
        return PHASE_AGB
    if age <= 12.46:
        return PHASE_PLANETARY_NEBULA
    return PHASE_WHITE_DWARF


def sun_state(age_gyr: float) -> SunState:
    """太阳在某绝对年龄（Gyr）的状态；过去钳制到当前，未来超过表尾沿冷却律延伸"""
    age = max(float(age_gyr), SUN_NOW_AGE_GYR)
    i = bisect.bisect_right(_AGES, age) - 1
    i = max(0, min(i, len(_NODES) - 2))
    a0, r0, t0, m0 = _NODES[i]
    a1, r1, t1, m1 = _NODES[i + 1]
    if a1 > a0:
        w = (age - a0) / (a1 - a0)
    else:
        w = 0.0
    w = max(0.0, min(1.0, w))
    # 对数插值（跨多个量级更平滑），质量线性
    r = r0 * (r1 / r0) ** w
    t = t0 * (t1 / t0) ** w
    m = m0 + (m1 - m0) * w
    lum = r * r * (t / _T_SUN) ** 4
    return SunState(age, r, lum, t, m, _phase_of(age))


def max_radius_au_between(age1: float, age2: float) -> float:
    """区间 [min, max] 内太阳光球的最大半径（AU）——时间跳转期间的吞噬判定。

    直接跳到白矮星期会越过 RGB tip 时刻（12.18 Gyr），若按跳转后的
    当前光球判定，内侧行星会被漏吞；本函数取区间覆盖到的节点最大
    半径（对数插值下单调段极值在节点/端点上）。过去钳制到现在。
    """
    a_lo = max(min(age1, age2), SUN_NOW_AGE_GYR)
    a_hi = max(max(age1, age2), SUN_NOW_AGE_GYR)
    r_max = max(sun_state(a_lo).radius_solar,
                sun_state(a_hi).radius_solar)
    for a, r, _t, _m in _NODES:
        if a_lo <= a <= a_hi:
            r_max = max(r_max, r)
    return r_max * SOLAR_RADIUS_AU



# ---------- 时间换算 ----------
def age_from_jd(jd: float) -> float:
    """儒略日 → 太阳绝对年龄（Gyr）"""
    return SUN_NOW_AGE_GYR + (jd - J2000_JD) / 365.25 / 1e9


def jd_from_age(age_gyr: float) -> float:
    """太阳绝对年龄（Gyr）→ 儒略日"""
    return J2000_JD + (age_gyr - SUN_NOW_AGE_GYR) * 1e9 * 365.25


# ---------- 黑体颜色 ----------
def blackbody_rgb(teff_k: float):
    """黑体温度 → sRGB 近似（Tanner Helland 色温算法，1000–40000 K）

    白矮星早期（>40000 K）钳制到 40000 K（深蓝），视觉足够。
    """
    t = max(1000.0, min(float(teff_k), 40000.0)) / 100.0
    if t <= 66.0:
        r = 255.0
    else:
        r = 329.698727446 * (t - 60.0) ** -0.1332047592
    if t <= 66.0:
        g = 99.4708025861 * _ln(t) - 161.1195681661
    else:
        g = 288.1221695283 * (t - 60.0) ** -0.0755148492
    if t >= 66.0:
        b = 255.0
    elif t <= 19.0:
        b = 0.0
    else:
        b = 138.5177312231 * _ln(t - 10.0) - 305.0447927307
    rgb = [max(0.0, min(255.0, c)) / 255.0 for c in (r, g, b)]
    return rgb


def _ln(x):
    import math
    return math.log(x)


# ---------- 行星命运 ----------
# 地球命运模式（模块级配置，viewport/设置可改）：
#   "escape"  （默认）：质量损失外移占上风，地球贴边掠过红巨星、幸存被烤焦
#   "engulf"：潮汐拖拽占上风（S&C 2008），地球被吞噬
EARTH_FATE = "escape"


def orbit_expansion(mass_solar: float, body_name: str = "") -> float:
    """太阳质量损失 → 行星轨道外移因子（角动量守恒 a ∝ M^-k）

    - 一般行星/默认：k = 1.0（绝热质量损失标准情形）
    - 地球 "escape" 模式：k = 1.2（外移更彻底 → RGB tip 期贴边掠过幸存）
    - 地球 "engulf" 模式：外移 × 0.92 的潮汐净内移参数化（S&C 2008：潮汐拖拽
      τ ∝ R_sun⁵/d⁶，红巨星膨胀后压过外移）
    近似级别：定性正确，非逐项积分。
    """
    m = max(float(mass_solar), 0.546)
    k = 1.0
    f = 1.0
    if body_name == "地球":
        if EARTH_FATE == "escape":
            k = 1.2
        else:
            f = 0.92
    return m ** -k * f


def is_engulfed(sun_radius_au: float, orbit_au: float) -> bool:
    """吞噬判定（机制一）：太阳光球半径 ≥ 天体轨道半径"""
    return sun_radius_au >= orbit_au