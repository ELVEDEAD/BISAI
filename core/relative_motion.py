"""
relative_motion.py —— 双行星相对运动分析（模块 F 核心计算）

支持 4 种参考系：
    行星A为原点 / 行星B为原点 / 质心为原点 / 宿主恒星(太阳)为原点

输出：
    相对轨迹三维曲线、相对距离序列、相对速度序列、
    最近/最远距离、当前距离、会合周期、精度等级判定

精度分级（见 6.2 节，必须标注）：
    同属太阳系 → 等级A（真实三维）
    同属一个系外恒星系统 → 取决于轨道参数完整度（等级B/C）
    分属不同恒星系统 → 明确说明含义不同，切换恒星参考系
"""
import math
import numpy as np
from dataclasses import dataclass, field
from core.kepler import solve_kepler, synodic_period, position_at_time
from core.constants import DEG2RAD, GRADE_A, GRADE_B, GRADE_C

REF_A = "A"           # 以行星A为原点
REF_B = "B"           # 以行星B为原点
REF_BARY = "bary"     # 质心
REF_STAR = "star"     # 宿主恒星（太阳/恒星）

REF_LABELS = {
    REF_A: "以 {a} 为原点",
    REF_B: "以 {b} 为原点",
    REF_BARY: "以两者质心为原点",
    REF_STAR: "以宿主恒星为原点",
}


@dataclass
class RelativeResult:
    """双行星相对运动分析结果（全部基于真实轨道数据，可复现）"""
    body_a: str
    body_b: str
    ref_frame: str
    jd_start: float
    jd_end: float
    n_samples: int
    times_jd: np.ndarray = None
    rel_positions: np.ndarray = None      # (n,3) 相对轨迹（AU，黄道系）
    distances: np.ndarray = None          # (n,) 相对距离（AU）
    speeds: np.ndarray = None             # (n,) 相对速率（km/s），缺数据时为 nan
    min_distance: float = float("nan")    # 最小相对距离（AU）
    max_distance: float = float("nan")    # 最大相对距离（AU）
    current_distance: float = float("nan")
    synodic_days: float = float("nan")    # 会合周期（天），同系统才有意义
    grade: str = GRADE_C
    grade_note: str = ""
    same_system: bool = True              # 是否同一恒星系统
    has_velocity: bool = False            # 双方均有速度数据才可算相对速度


def classify_pair(body_a, body_b) -> tuple:
    """
    判定两颗行星的精度等级与系统关系（6.2 节要求）
    返回 (grade, note, same_system)
    """
    a_star = (body_a.host or "").strip()
    b_star = (body_b.host or "").strip()
    if body_a.body_type == "planet_solar" and body_b.body_type == "planet_solar":
        return (GRADE_A,
                "两颗行星同属太阳系，三维相对运动基于 JPL 近似星历，真实可靠（等级A）。",
                True)
    if a_star and b_star and a_star.lower() == b_star.lower():
        if body_a.grade == GRADE_C or body_b.grade == GRADE_C:
            return (GRADE_C,
                    f"两颗行星同属 {a_star} 系统，但轨道倾角等参数缺失，相对轨迹为投影近似（等级C）。",
                    True)
        return (GRADE_B,
                f"两颗行星同属 {a_star} 系统，相对轨迹基于近似轨道根数（等级B）。",
                True)
    if (body_a.body_type == "planet_solar") != (body_b.body_type == "planet_solar"):
        return (GRADE_B,
                "两颗行星分属太阳系与系外恒星系统，此结果实为两个恒星系统间的相对运动，"
                "与同一系统内行星相对运动含义不同，建议切换恒星参考系分析（等级B，恒星距离为实测/近似）。",
                False)
    return (GRADE_B,
            "两颗行星分属不同恒星系统，此结果为两个恒星系统间的相对运动，"
            "并非同一系统内的行星相对运动，含义不同（等级B）。",
            False)


def compute_relative(body_a, body_b, ref_frame: str, jd_start: float, jd_end: float,
                     n_samples: int = 360) -> RelativeResult:
    """
    计算两颗行星在给定参考系与时间范围内的相对运动

    body_a / body_b：天体数据对象（需提供 position_at_jd 接口与质量）
    """
    grades, note, same_sys = classify_pair(body_a, body_b)
    t = np.linspace(jd_start, jd_end, n_samples)

    pos_a = np.array([body_a.position_at_jd(jd) for jd in t])
    pos_b = np.array([body_b.position_at_jd(jd) for jd in t])

    # ---------- 参考系处理 ----------
    bary_fallback = False
    if ref_frame == REF_A:
        origin = pos_a
        rel = pos_b - pos_a
    elif ref_frame == REF_B:
        origin = pos_b
        rel = pos_a - pos_b
    elif ref_frame == REF_BARY:
        ma, mb = body_a.mass_solar, body_b.mass_solar
        if ma is None or mb is None or (ma + mb) <= 0:
            # 质量数据缺失：质心不可得，诚实回退为宿主恒星参考系（不伪造质量值）
            ref_frame = REF_STAR
            bary_fallback = True
            origin = np.zeros_like(pos_a)
            rel = pos_a - pos_b
        else:
            total = ma + mb
            origin = (pos_a * (mb / total)) + (pos_b * (ma / total))
            rel = (pos_a - origin) - (pos_b - origin)
    else:  # REF_STAR
        origin = np.zeros_like(pos_a)
        rel = pos_a - pos_b
    if bary_fallback:
        note += "（注：一方质量数据缺失，质心不可得，已回退为宿主恒星参考系显示）"

    dist = np.linalg.norm(rel, axis=1)

    # ---------- 相对速度（仅当双方均能提供解析速度时） ----------
    speeds = None
    has_vel = False
    try:
        va = np.array([body_a.velocity_at_jd(jd) for jd in t])
        vb = np.array([body_b.velocity_at_jd(jd) for jd in t])
        rel_v = va - vb
        speeds = np.linalg.norm(rel_v, axis=1)
        has_vel = (not np.any(np.isnan(speeds)))
    except (NotImplementedError, AttributeError):
        speeds = np.full(n_samples, np.nan)

    # ---------- 会合周期（仅同一中心天体） ----------
    syn = float("nan")
    if same_sys:
        try:
            p1, p2 = body_a.period, body_b.period
            if p1 and p2 and p1 > 0 and p2 > 0:
                syn = synodic_period(p1, p2)
        except Exception:
            syn = float("nan")

    cur_dist = float(np.linalg.norm(
        body_a.position_at_jd(t[-1]) - body_b.position_at_jd(t[-1])))

    return RelativeResult(
        body_a=body_a.name, body_b=body_b.name, ref_frame=ref_frame,
        jd_start=jd_start, jd_end=jd_end, n_samples=n_samples,
        times_jd=t, rel_positions=rel, distances=dist, speeds=speeds,
        min_distance=float(np.nanmin(dist)), max_distance=float(np.nanmax(dist)),
        current_distance=cur_dist, synodic_days=syn,
        grade=grades, grade_note=note, same_system=same_sys,
        has_velocity=has_vel,
    )