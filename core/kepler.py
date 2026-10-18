"""
kepler.py —— 开普勒轨道计算（核心科学模块）

- 牛顿迭代解开普勒方程 E - e·sinE = M
- 轨道根数 → J2000 黄道坐标系日心三维位置（可复现、无随机数）
- 轨道线采样（用于三维轨迹绘制）
- 解析速度（vis-viva + 轨道平面旋转），用于相对运动速度曲线

适用边界（见 09_局限性与风险声明.md）：
- 开普勒轨道为二体近似，忽略行星间摄动与相对论效应
- JPL 近似轨道根数（含世纪变率）在 1800–2050 年精度较好（内行星约 arcmin 级）
- 长期外推误差累积，UI 需在超出适用范围时提示
"""
import math
import numpy as np
from core.constants import DEG2RAD, RAD2DEG, AU_KM


def solve_kepler(M: float, e: float) -> float:
    """解开普勒方程 M = E - e·sinE，返回偏近点角 E（弧度）"""
    M = (M + math.pi) % (2 * math.pi) - math.pi   # 归一化到 [-π, π]
    if e < 0.8:
        E = M
    else:
        E = math.copysign(math.pi, M) if M != 0 else math.pi
    for _ in range(60):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        dE = f / fp
        E -= dE
        if abs(dE) < 1e-12:
            break
    return E


def elements_to_position(a: float, e: float, i_deg: float,
                         Omega_deg: float, omega_deg: float, M_rad: float) -> np.ndarray:
    """
    轨道根数 → J2000 黄道坐标系三维位置（单位 AU）

    参数：
        a        半长轴（AU）
        e        偏心率
        i_deg    轨道倾角（度）
        Omega_deg 升交点经度（度）
        omega_deg 近心点幅角（度）
        M_rad    平近点角（弧度）
    """
    E = solve_kepler(M_rad, e)
    # 轨道平面内坐标
    xv = a * (math.cos(E) - e)
    yv = a * math.sqrt(max(1.0 - e * e, 0.0)) * math.sin(E)

    i = i_deg * DEG2RAD
    Omega = Omega_deg * DEG2RAD
    w = omega_deg * DEG2RAD

    cosw, sinw = math.cos(w), math.sin(w)
    cosO, sinO = math.cos(Omega), math.sin(Omega)
    cosi, sini = math.cos(i), math.sin(i)

    # 标准轨道平面 → 参考平面旋转矩阵
    x = (cosw * cosO - sinw * sinO * cosi) * xv + (-sinw * cosO - cosw * sinO * cosi) * yv
    y = (cosw * sinO + sinw * cosO * cosi) * xv + (-sinw * sinO + cosw * cosO * cosi) * yv
    z = (sinw * sini) * xv + (cosw * sini) * yv
    return np.array([x, y, z], dtype=np.float64)


def solve_kepler_vec(M: np.ndarray, e: np.ndarray, iters: int = 32) -> np.ndarray:
    """解开普勒方程（向量化）：对 M/e 数组一次性求解，返回偏近点角 E 数组。

    牛顿迭代固定次数（不做逐元素收敛判断），适用于批量计算（如数千颗系外行星）；
    对高偏心率（e > 0.9）调用方可用标量 solve_kepler 校正残余。
    """
    M = (M + math.pi) % (2.0 * math.pi) - math.pi
    E = np.where(e < 0.8, M, np.where(M >= 0.0, math.pi, -math.pi))
    for _ in range(iters):
        f = E - e * np.sin(E) - M
        E = E - f / (1.0 - e * np.cos(E))
    return E


def exo_relative_positions_vec(a: np.ndarray, e: np.ndarray, i_deg: np.ndarray,
                               M: np.ndarray) -> np.ndarray:
    """系外行星相对宿主星位置（向量化，AU，J2000 黄道系）。

    等价于 elements_to_position(a, e, i, Ω=0, ω=0, M)：
    升交点经度与近心点幅角未测定，取可复现假设值 0（与标量实现一致）。
    """
    E = solve_kepler_vec(M, e)
    xv = a * (np.cos(E) - e)
    yv = a * np.sqrt(np.clip(1.0 - e * e, 0.0, None)) * np.sin(E)
    i = np.radians(i_deg)
    cosi, sini = np.cos(i), np.sin(i)
    return np.stack([xv, cosi * yv, sini * yv], axis=1)


def position_at_time(a0: float, da: float, e0: float, de: float,
                     i0: float, di: float, L0: float, dL: float,
                     varpi0: float, dvarpi: float, Omega0: float, dOmega: float,
                     T: float) -> np.ndarray:
    """
    JPL 近似轨道根数（含世纪变率）→ 任意儒略世纪数 T 下的日心黄道位置（AU）

    T = (JD - 2451545.0) / 36525
    根数：a, e, I, L, long.peri.(ϖ), long.node.(Ω)，变率为每世纪变化量
    """
    a = a0 + da * T
    e = e0 + de * T
    i = (i0 + di * T) % 360.0
    L = (L0 + dL * T) % 360.0
    varpi = (varpi0 + dvarpi * T) % 360.0
    Omega = (Omega0 + dOmega * T) % 360.0

    M = (L - varpi) * DEG2RAD           # 平近点角
    omega = varpi - Omega               # 近心点幅角
    return elements_to_position(a, e, i, Omega, omega, M)


def sample_orbit(a: float, e: float, i_deg: float, Omega_deg: float,
                 omega_deg: float, n_points: int = 256,
                 closed: bool = False) -> np.ndarray:
    """
    沿椭圆轨道均匀采样 n_points 个点（偏近点角均匀），返回 (n,3) 数组（AU）
    用于绘制完整轨道线——形状由真实轨道根数决定（客观轨迹）

    closed=False：返回 n_points 个点（起点=终点相位 0，不重复）；
    closed=True ：末尾追加首点（共 n_points+1 个），轨道线严格闭合，
                  供 LINE_STRIP 类绘制使用（GL 线段索引相邻对即天然闭环）。
    """
    E = np.linspace(0.0, 2.0 * math.pi, n_points, endpoint=False)
    xv = a * (np.cos(E) - e)
    yv = a * np.sqrt(max(1.0 - e * e, 0.0)) * np.sin(E)

    i = i_deg * DEG2RAD
    Omega = Omega_deg * DEG2RAD
    w = omega_deg * DEG2RAD
    cosw, sinw = math.cos(w), math.sin(w)
    cosO, sinO = math.cos(Omega), math.sin(Omega)
    cosi, sini = math.cos(i), math.sin(i)

    x = (cosw * cosO - sinw * sinO * cosi) * xv + (-sinw * cosO - cosw * sinO * cosi) * yv
    y = (cosw * sinO + sinw * cosO * cosi) * xv + (-sinw * sinO + cosw * cosO * cosi) * yv
    z = (sinw * sini) * xv + (cosw * sini) * yv
    pts = np.stack([x, y, z], axis=1)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    return pts


def velocity_at_time(a: float, e: float, i_deg: float, Omega_deg: float,
                     omega_deg: float, M_rad: float, period_days: float,
                     mu_kg: float) -> np.ndarray:
    """
    解析轨道速度（J2000 黄道坐标系，单位 km/s）

    由 dE/dt = n/(1 - e·cosE)、n = 2π/period 与 vis-viva 关系推出，
    mu_km3_s2 = G·M_center（km³/s²）
    """
    E = solve_kepler(M_rad, e)
    n = 2.0 * math.pi / max(period_days * 86400.0, 1e-9)   # rad/s
    denom = max(1.0 - e * math.cos(E), 1e-9)
    dEdt = n / denom

    dxv = -a * math.sin(E)
    dyv = a * math.sqrt(max(1.0 - e * e, 0.0)) * math.cos(E)
    # dxv 单位 AU、dEdt 单位 1/s → 速度 AU/s；乘 1 AU 的千米数换算为 km/s
    vx = dxv * dEdt * AU_KM
    vy = dyv * dEdt * AU_KM

    i = i_deg * DEG2RAD
    Omega = Omega_deg * DEG2RAD
    w = omega_deg * DEG2RAD
    cosw, sinw = math.cos(w), math.sin(w)
    cosO, sinO = math.cos(Omega), math.sin(Omega)
    cosi, sini = math.cos(i), math.sin(i)

    x = (cosw * cosO - sinw * sinO * cosi) * vx + (-sinw * cosO - cosw * sinO * cosi) * vy
    y = (cosw * sinO + sinw * cosO * cosi) * vx + (-sinw * sinO + cosw * cosO * cosi) * vy
    z = (sinw * sini) * vx + (cosw * sini) * vy
    _ = mu_kg
    return np.array([x, y, z], dtype=np.float64)


def mean_anomaly(period_days: float, M0_rad: float, dt_days: float) -> float:
    """由参考历元平近点角推进 dt 天得到当前平近点角（弧度）"""
    n = 2.0 * math.pi / max(period_days, 1e-9)
    return M0_rad + n * dt_days


def synodic_period(p1_days: float, p2_days: float) -> float:
    """会合周期（天）：1 / |1/P1 - 1/P2|，仅对同一中心天体有意义"""
    if p1_days <= 0 or p2_days <= 0 or abs(p1_days - p2_days) < 1e-12:
        return float("inf")
    return abs(1.0 / (1.0 / p1_days - 1.0 / p2_days))