"""
phenomena.py —— 天象推演（合相 / 冲日 / 方照 / 大距 / 行星合相 / 凌日）

原理
----
以地球为观测点（地心视位置），在 J2000 黄道坐标系下由三维位置计算
**视黄经**与**视角距**，把每种天象化为某个时间标量函数的零点或极值，
用「粗扫描 + 变号二分 / 黄金分割」细化得到事件时刻。全部为解析计算，
可复现、无随机数。

各天象的判定
------------
* 合日 / 冲日：目标地心黄经 − 太阳地心黄经 Δλ 满足 sinΔλ=0；Δλ≈0 为合、
  Δλ≈180 为冲（cosΔλ 符号区分）。
* 方照：太阳-地球-目标夹角（距角）过 90°。
* 大距：内行星距角的局部极大值（东大距 / 西大距）。
* 行星合相：两天体地心黄经相同（Δλ≈0），另附真实角距（含黄纬差）。
* 凌日：内行星「下合」且最小视角距小于太阳视半径（候选，见下）。

科学诚实性
----------
* 位置来自 JPL 近似星历（1800–2050，内行星约 arcmin 级），故事件时刻误差约
  数分钟至数小时；**凌日**几何极为敏感，结果标注为「候选」并需人工复核。
* 天然卫星沿轨相位为可复现假设值 M(J2000)=0，绝对时刻无预测意义，故
  **不推演卫星食 / 凌 / 掩**（避免伪造）。
"""
import math
from dataclasses import dataclass, field

import numpy as np

from core.constants import DEG2RAD, AU_KM, J2000_JD
from core.time_system import jd_to_datetime

# ---------- 事件类型 ----------
KIND_OPPOSITION = "opposition"
KIND_CONJUNCTION_SUN = "conjunction_sun"
KIND_GREATEST_ELONGATION = "greatest_elongation"
KIND_QUADRATURE = "quadrature"
KIND_CONJUNCTION_PAIR = "conjunction_pair"
KIND_TRANSIT = "transit"

KIND_LABELS = {
    KIND_OPPOSITION: "冲日",
    KIND_CONJUNCTION_SUN: "合日",
    KIND_GREATEST_ELONGATION: "大距",
    KIND_QUADRATURE: "方照",
    KIND_CONJUNCTION_PAIR: "行星合相",
    KIND_TRANSIT: "凌日（候选）",
}

SUN_RADIUS_KM = 695700.0
OBSERVER_DEFAULT = "地球"

# 各类型适用的目标天体（供 UI 过滤）：内行星 / 外行星
INFERIOR = ("水星", "金星")


@dataclass
class Phenomenon:
    """一次天象事件"""
    kind: str
    jd: float
    label: str                       # 事件描述，如 "火星冲日"
    detail: str = ""                 # 角距 / 黄经差等数值
    bodies: tuple = ()               # 相关天体名
    note: str = ""                   # 备注（精度/说明）

    @property
    def datetime_str(self) -> str:
        return jd_to_datetime(self.jd).strftime("%Y-%m-%d %H:%M")

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


# ---------- 几何工具 ----------
def _pos(body, jd: float) -> np.ndarray:
    return np.asarray(body.position_at_jd(jd), dtype=np.float64)


def _lon_deg(v: np.ndarray) -> float:
    """黄道视黄经（度，0–360）"""
    return math.degrees(math.atan2(float(v[1]), float(v[0]))) % 360.0


def _separation_deg(v1: np.ndarray, v2: np.ndarray) -> float:
    """两向量夹角（度）"""
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-15 or n2 < 1e-15:
        return float("nan")
    c = float(np.dot(v1, v2) / (n1 * n2))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def elongation_deg(obs, target, jd: float) -> float:
    """距角：从观测者看「目标」与「太阳」的夹角（度，0–180）"""
    e = _pos(obs, jd)
    return _separation_deg(_pos(target, jd) - e, -e)


def _dlon_sun(obs, target, jd: float) -> float:
    """目标地心黄经 − 太阳地心黄经（度，0–360）"""
    e = _pos(obs, jd)
    lam_t = _lon_deg(_pos(target, jd) - e)
    lam_s = _lon_deg(-e)
    return (lam_t - lam_s) % 360.0


# ---------- 数值细化 ----------
def _bisect(f, a: float, b: float, iters: int = 60) -> float:
    fa = f(a)
    for _ in range(iters):
        m = 0.5 * (a + b)
        fm = f(m)
        if fm == 0.0:
            return m
        if fa * fm < 0.0:
            b = m
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


def _find_roots(f, jd0: float, jd1: float, step: float) -> list:
    """扫描 + 二分：f 在 [jd0, jd1] 内的变号根"""
    roots = []
    jd = jd0
    fa = f(jd)
    guard = 0
    while jd < jd1 and guard < 200000:
        guard += 1
        nxt = min(jd + step, jd1)
        fb = f(nxt)
        if fa == 0.0:
            roots.append(jd)
        elif fa * fb < 0.0:
            roots.append(_bisect(f, jd, nxt))
        jd, fa = nxt, fb
    return roots


def _golden(f, a: float, b: float, mode: str = "max", iters: int = 80) -> float:
    """黄金分割求极值（mode: max / min）"""
    gr = (math.sqrt(5.0) - 1.0) / 2.0
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if (fc > fd) == (mode == "max"):
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = f(d)
    return 0.5 * (a + b)


def _find_extrema(f, jd0: float, jd1: float, step: float, mode: str = "max") -> list:
    """扫描 + 黄金分割：f 的局部极值时刻"""
    xs = np.arange(jd0, jd1 + step * 0.5, step)
    if len(xs) < 3:
        return []
    sign = 1.0 if mode == "max" else -1.0
    ys = [sign * f(float(x)) for x in xs]
    out = []
    for k in range(1, len(xs) - 1):
        if ys[k] >= ys[k - 1] and ys[k] >= ys[k + 1]:
            out.append(_golden(f, float(xs[k - 1]), float(xs[k + 1]), mode))
    return out


def _min_near(f, jd_c: float, half: float = 2.0, n: int = 81):
    """在 jd_c 附近细扫后黄金分割求最小，返回 (jd_min, value)"""
    xs = np.linspace(jd_c - half, jd_c + half, n)
    ys = [f(float(x)) for x in xs]
    k = int(np.argmin(ys))
    if 0 < k < n - 1:
        jm = _golden(f, float(xs[k - 1]), float(xs[k + 1]), mode="min")
    else:
        jm = float(xs[k])
    return jm, f(jm)


# ---------- 扫描步长 ----------
def synodic_days(a, b) -> float:
    """会合周期（天）"""
    p1, p2 = a.period, b.period
    if not p1 or not p2:
        return 365.25
    d = abs(1.0 / p1 - 1.0 / p2)
    if d < 1e-12:
        return 36525.0
    return 1.0 / d


def _step_for(obs, target, div: float = 60.0) -> float:
    return max(0.5, min(20.0, synodic_days(obs, target) / div))


# ---------- 各天象搜索 ----------
def _sun_align(obs, target, jd0, jd1, step, want):
    """合日 / 冲日：返回 [(jd, Δλ)]"""
    f = lambda jd: math.sin(_dlon_sun(obs, target, jd) * DEG2RAD)
    out = []
    for r in _find_roots(f, jd0, jd1, step):
        d = _dlon_sun(obs, target, r)
        is_conj = math.cos(d * DEG2RAD) > 0.0
        if (want == "conjunction") == is_conj:
            out.append((r, d))
    return out


def _is_superior(obs, target) -> bool:
    a_obs = obs.a_au or 1.0
    a_t = target.a_au
    return a_t is not None and a_t > a_obs


# ---------- 统一入口 ----------
def _get(bodies, name):
    if name is None:
        return None
    if isinstance(bodies, dict):
        return bodies.get(name)
    return next((b for b in bodies if b.name == name), None)


def search(kind: str, bodies, jd0: float, jd1: float,
           target: str = None, target_b: str = None,
           observer_name: str = OBSERVER_DEFAULT) -> list:
    """在 [jd0, jd1] 内推演指定天象，返回 Phenomenon 列表（按时间升序）。

    kind         事件类型（KIND_*）
    bodies       天体集合（list[Body] 或 dict{name: Body}）
    target       目标天体名（合日/冲日/方照/大距/凌日）
    target_b     第二目标天体名（仅「行星合相」用）
    observer_name 观测点天体名（默认地球）
    """
    obs = _get(bodies, observer_name)
    if obs is None or jd1 <= jd0:
        return []
    try:
        if kind == KIND_CONJUNCTION_PAIR:
            return _search_pair(obs, bodies, jd0, jd1, target, target_b)
        tgt = _get(bodies, target)
        if tgt is None:
            return []
        if kind == KIND_OPPOSITION:
            return _search_opposition(obs, tgt, jd0, jd1)
        if kind == KIND_CONJUNCTION_SUN:
            return _search_conjunction_sun(obs, tgt, jd0, jd1)
        if kind == KIND_QUADRATURE:
            return _search_quadrature(obs, tgt, jd0, jd1)
        if kind == KIND_GREATEST_ELONGATION:
            return _search_greatest_elongation(obs, tgt, jd0, jd1)
        if kind == KIND_TRANSIT:
            return _search_transit(obs, tgt, jd0, jd1)
    except Exception:
        return []          # 数据缺失等异常 → 空结果，不崩溃
    return []


def _search_opposition(obs, tgt, jd0, jd1) -> list:
    if not _is_superior(obs, tgt):
        return []
    step = _step_for(obs, tgt)
    out = []
    for jd, _d in _sun_align(obs, tgt, jd0, jd1, step, "opposition"):
        el = elongation_deg(obs, tgt, jd)
        out.append(Phenomenon(
            KIND_OPPOSITION, jd, f"{tgt.name}冲日",
            f"地心距角 {el:.2f}°（≈180°）", (tgt.name,),
            "整夜可见、距离最近、最亮"))
    return out


def _search_conjunction_sun(obs, tgt, jd0, jd1) -> list:
    step = _step_for(obs, tgt)
    out = []
    for jd, d in _sun_align(obs, tgt, jd0, jd1, step, "conjunction"):
        el = elongation_deg(obs, tgt, jd)
        dd = d if d < 180.0 else d - 360.0        # 有符号黄经差
        note = "地心黄经与太阳相同"
        if not _is_superior(obs, tgt):
            # 内行星：判断下合 / 上合（下合时行星位于日-地连线的近地一侧）
            inferior = float(np.dot(_pos(tgt, jd), _pos(obs, jd))) > 0.0
            note += "；下合（行星在日地之间）" if inferior else "；上合（行星在太阳远侧）"
        out.append(Phenomenon(
            KIND_CONJUNCTION_SUN, jd, f"{tgt.name}合日",
            f"黄经差 {dd:+.3f}°（≈0°）｜视角距 {el:.2f}°", (tgt.name,), note))
    return out


def _search_quadrature(obs, tgt, jd0, jd1) -> list:
    if not _is_superior(obs, tgt):
        return []          # 方照仅对地外行星有意义
    step = _step_for(obs, tgt)
    f = lambda jd: elongation_deg(obs, tgt, jd) - 90.0
    out = []
    for jd in _find_roots(f, jd0, jd1, step):
        el = elongation_deg(obs, tgt, jd)
        out.append(Phenomenon(
            KIND_QUADRATURE, jd, f"{tgt.name}方照",
            f"地心距角 {el:.2f}°（≈90°）", (tgt.name,),
            "距角 90°，适合观测相位/阴影"))
    return out


def _search_greatest_elongation(obs, tgt, jd0, jd1) -> list:
    step = _step_for(obs, tgt)
    f = lambda jd: elongation_deg(obs, tgt, jd)
    out = []
    for jd in _find_extrema(f, jd0, jd1, step, mode="max"):
        el = f(jd)
        # 东大距：目标黄经在太阳以东（昏见）；西大距：以西（晨见）
        east = ((_lon_deg(_pos(tgt, jd) - _pos(obs, jd))
                 - _lon_deg(-_pos(obs, jd))) % 360.0) < 180.0
        tag = "东大距（昏见）" if east else "西大距（晨见）"
        out.append(Phenomenon(
            KIND_GREATEST_ELONGATION, jd, f"{tgt.name}{tag}",
            f"最大距角 {el:.2f}°", (tgt.name,),
            "内行星距角极大，观测良机"))
    return out


def _search_pair(obs, bodies, jd0, jd1, name_a, name_b) -> list:
    a = _get(bodies, name_a)
    b = _get(bodies, name_b)
    if a is None or b is None or a is b:
        return []
    step = max(0.5, min(20.0, synodic_days(a, b) / 60.0))
    f = lambda jd: math.sin(
        ((_lon_deg(_pos(b, jd) - _pos(obs, jd))
          - _lon_deg(_pos(a, jd) - _pos(obs, jd))) % 360.0) * DEG2RAD)
    out = []
    for jd in _find_roots(f, jd0, jd1, step):
        d = ((_lon_deg(_pos(b, jd) - _pos(obs, jd))
              - _lon_deg(_pos(a, jd) - _pos(obs, jd))) % 360.0)
        if math.cos(d * DEG2RAD) <= 0.0:
            continue                      # 只取同黄经（Δλ≈0），排除 Δλ≈180
        e = _pos(obs, jd)
        sep = _separation_deg(_pos(a, jd) - e, _pos(b, jd) - e)
        out.append(Phenomenon(
            KIND_CONJUNCTION_PAIR, jd, f"{a.name}合{b.name}",
            f"视角距 {sep:.3f}°", (a.name, b.name),
            "地心黄经相同；角距含黄纬差，近距为「合」、极近为「合相」"))
    return out


def _search_transit(obs, tgt, jd0, jd1) -> list:
    """凌日（候选）：内行星下合且最小视角距小于太阳视半径"""
    if _is_superior(obs, tgt):
        return []
    step = max(0.5, min(20.0, synodic_days(obs, tgt) / 60.0))
    out = []
    for jd_c, _d in _sun_align(obs, tgt, jd0, jd1, step, "conjunction"):
        e_c = _pos(obs, jd_c)
        p_c = _pos(tgt, jd_c)
        if float(np.dot(p_c, e_c)) <= 0.0:
            continue                      # 上合（行星在太阳远侧），非凌日
        # 下合：行星位于日-地连线的近地一侧（同一日心方向）
        sep = lambda jd: _separation_deg(_pos(tgt, jd) - _pos(obs, jd), -_pos(obs, jd))
        jd_min, smin = _min_near(sep, jd_c, half=2.0, n=81)
        d_sun = float(np.linalg.norm(_pos(obs, jd_min)))
        sun_rad = math.degrees(math.asin(min(1.0, SUN_RADIUS_KM / (d_sun * AU_KM))))
        if smin < sun_rad:
            # 精度提示按行星区分：水星轨道快（~48 km/s），1 角分黄经误差
            # ≈ 5 小时；金星凌日对星历误差更敏感（2012 实测偏差 ~10.5 小时）
            acc = ("基于 JPL 近似星历，时刻误差约 ±3 小时，仅供参考"
                   if tgt.name == "水星"
                   else "基于 JPL 近似星历，时刻误差约 ±0.5 天，仅供参考")
            out.append(Phenomenon(
                KIND_TRANSIT, jd_min, f"{tgt.name}凌日",
                f"最小视角距 {smin:.4f}° < 太阳视半径 {sun_rad:.4f}°",
                (tgt.name,),
                "候选事件：" + acc + "，具体时刻与可见性需复核"))
    return out


# ---------- UI 辅助 ----------
def candidates(kind: str, bodies) -> list:
    """返回某天象类型可选的目标天体名列表"""
    planets = [b for b in bodies
               if b.body_type in ("planet_solar", "dwarf")]
    names = [b.name for b in planets]
    if kind == KIND_OPPOSITION or kind == KIND_QUADRATURE:
        return [n for n in names if n not in INFERIOR]     # 外行星
    if kind == KIND_GREATEST_ELONGATION or kind == KIND_TRANSIT:
        return [n for n in names if n in INFERIOR]          # 内行星
    return names                                            # 合日 / 行星合相


def needs_pair(kind: str) -> bool:
    return kind == KIND_CONJUNCTION_PAIR