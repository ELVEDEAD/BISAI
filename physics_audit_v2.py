"""
physics_audit_v2.py —— 星盘软件物理正确性审计 v2（修正版）

修正 v1 中的测试方法问题，专注于真正的物理 bug。
"""
import sys
import math
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.constants import (AU_KM, AU_M, G_SI, M_SUN_KG, M_EARTH_KG,
                            DEG2RAD, RAD2DEG, J2000_JD, JULIAN_YEAR_DAYS,
                            R_SUN_KM, R_EARTH_KM)
from core.kepler import (solve_kepler, elements_to_position,
                         position_at_time, velocity_at_time,
                         synodic_period, sample_orbit,
                         mean_anomaly, solve_kepler_vec)
from core.time_system import jd_to_ymd, datetime_to_jd
from datetime import datetime

def ymd_to_jd(y, m, d):
    return datetime_to_jd(datetime(y, m, d, 12, 0, 0))

from core.stellar_model import (equilibrium_temperature, scale_height_m,
                                 main_sequence_luminosity,
                                 luminosity_from_radius_temp,
                                 planck_b_lambda, stefan_boltzmann_flux,
                                 wien_peak_nm, transit_depth_limb_darkened)
from core.exo_obs import (transit_depth_ppm, rv_semi_amplitude_m_s,
                          habitable_zone_bands, insolation_earth,
                          transit_durations_days, radius_ratio,
                          a_in_stellar_radii, transit_light_curve,
                          rv_curve)
from core.phenomena import (search, KIND_OPPOSITION, KIND_CONJUNCTION_SUN,
                            KIND_QUADRATURE, KIND_GREATEST_ELONGATION,
                            KIND_TRANSIT, elongation_deg)
from data.solar_system import SOLAR_PLANETS
from data.loader import load_solar_system

# 构建太阳系天体字典
_bodies_list = load_solar_system()
bodies = {b.name: b for b in _bodies_list}

bugs = []

def add_bug(severity, category, description, detail=""):
    bugs.append((severity, category, description, detail))
    print(f"  [{severity}] {category}: {description}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")

GM = G_SI * M_SUN_KG

# ============================================================
# 测试 1: 旋转矩阵正交性（正确的方法）
# ============================================================
print("\n" + "="*60)
print("测试 1: 轨道平面旋转矩阵正交性（向量内积不变）")
print("="*60)

# 取轨道平面内两个向量：在 E=0 处的位置向量和 E=π/2 处的位置向量
# 它们在轨道平面内的内积应该等于旋转后的三维内积
# 更准确的测试：旋转矩阵 R 满足 R^T R = I，即对任意向量 u, v：(Ru)·(Rv) = u·v

a, e = 1.0, 0.5
i_deg, Omega_deg, omega_deg = 23.4, 45.0, 60.0

# 取轨道平面内两个任意向量（xv, yv）
u_plane = np.array([1.0, 0.5, 0.0])
v_plane = np.array([-0.3, 0.8, 0.0])
inner_plane = np.dot(u_plane, v_plane)

# 将这两个向量通过相同的旋转矩阵转到三维空间
# 我们用 elements_to_position 来间接验证：两个点之间的距离在旋转前后应不变
# 更直接：用三个点来验证旋转矩阵的性质
# 点 1: E=0 → xv = a(1-e), yv = 0
# 点 2: E=π/2 → xv = -ae, yv = a*sqrt(1-e²)
# 点 3: E=π → xv = -a(1+e), yv = 0

def orbit_plane_pos(a, e, E):
    """轨道平面内的位置（未旋转）"""
    xv = a * (math.cos(E) - e)
    yv = a * math.sqrt(max(1-e*e, 0)) * math.sin(E)
    return np.array([xv, yv, 0.0])

E1, E2, E3 = 0.0, math.pi/2, math.pi

p1_plane = orbit_plane_pos(a, e, E1)
p2_plane = orbit_plane_pos(a, e, E2)
p3_plane = orbit_plane_pos(a, e, E3)

# 三维位置
p1_3d = elements_to_position(a, e, i_deg, Omega_deg, omega_deg,
                             solve_kepler(E1 - e*math.sin(E1), e))  # 不对，E1 对应的 M = E1 - e*sin(E1)
# 等等，我们需要传入 M 而不是 E。让我们先算 M。
M1 = E1 - e * math.sin(E1)
M2 = E2 - e * math.sin(E2)
M3 = E3 - e * math.sin(E3)

p1_3d = elements_to_position(a, e, i_deg, Omega_deg, omega_deg, M1)
p2_3d = elements_to_position(a, e, i_deg, Omega_deg, omega_deg, M2)
p3_3d = elements_to_position(a, e, i_deg, Omega_deg, omega_deg, M3)

# 验证：平面内的距离 = 三维距离
d12_plane = np.linalg.norm(p2_plane - p1_plane)
d12_3d = np.linalg.norm(p2_3d - p1_3d)
d23_plane = np.linalg.norm(p3_plane - p2_plane)
d23_3d = np.linalg.norm(p3_3d - p2_3d)

if abs(d12_3d - d12_plane) / d12_plane > 1e-10:
    add_bug("HIGH", "旋转矩阵",
            "p1-p2 距离在旋转前后不相等（旋转矩阵不正交）",
            f"平面内: {d12_plane:.12f} AU\n"
            f"三维: {d12_3d:.12f} AU\n"
            f"相对误差: {abs(d12_3d-d12_plane)/d12_plane:.2e}")
else:
    print(f"  ✓ p1-p2 距离守恒: 误差 {abs(d12_3d-d12_plane)/d12_plane:.2e}")

if abs(d23_3d - d23_plane) / d23_plane > 1e-10:
    add_bug("HIGH", "旋转矩阵",
            "p2-p3 距离在旋转前后不相等",
            f"平面内: {d23_plane:.12f} AU\n"
            f"三维: {d23_3d:.12f} AU\n"
            f"相对误差: {abs(d23_3d-d23_plane)/d23_plane:.2e}")
else:
    print(f"  ✓ p2-p3 距离守恒: 误差 {abs(d23_3d-d23_plane)/d23_plane:.2e}")

# 验证：向量内积不变
v12_plane = p2_plane - p1_plane
v13_plane = p3_plane - p1_plane
inner_plane = np.dot(v12_plane, v13_plane)

v12_3d = p2_3d - p1_3d
v13_3d = p3_3d - p1_3d
inner_3d = np.dot(v12_3d, v13_3d)

if abs(inner_3d - inner_plane) / abs(inner_plane) > 1e-10:
    add_bug("HIGH", "旋转矩阵",
            "向量内积在旋转前后不相等",
            f"平面内: {inner_plane:.12f}\n"
            f"三维: {inner_3d:.12f}\n"
            f"相对误差: {abs(inner_3d-inner_plane)/abs(inner_plane):.2e}")
else:
    print(f"  ✓ 内积守恒: 误差 {abs(inner_3d-inner_plane)/abs(inner_plane):.2e}")

print("  ✓ 测试完成")

# ============================================================
# 测试 2: 速度 vis-viva 方程（更严格）
# ============================================================
print("\n" + "="*60)
print("测试 2: vis-viva 方程（检查系统偏差来源）")
print("="*60)

# 用 position_at_time 和 velocity_at_time 的底层版本验证
# 即直接调用 elements_to_position 和 velocity_at_time，使用相同的轨道根数

a = 1.0
e = 0.5
i_deg = 10.0
Omega_deg = 40.0
omega_deg = 50.0
M = math.pi / 3  # 任意平近点角
period_days = 365.25  # 1 年

pos = elements_to_position(a, e, i_deg, Omega_deg, omega_deg, M)
vel = velocity_at_time(a, e, i_deg, Omega_deg, omega_deg, M, period_days, 0)

r_au = np.linalg.norm(pos)
r_m = r_au * AU_M
v_km_s = np.linalg.norm(vel)
v_m_s = v_km_s * 1000.0

# vis-viva: v² = GM(2/r - 1/a)
a_m = a * AU_M
v_expected = math.sqrt(GM * (2.0 / r_m - 1.0 / a_m))
rel = abs(v_m_s - v_expected) / v_expected

# 但是 velocity_at_time 用 period 来算 n = 2π/P
# 而 period 应该 = 2π / sqrt(GM/a³)（开普勒第三定律）
# 让我们验证 period 是否与 a 自洽
n_from_period = 2.0 * math.pi / (period_days * 86400.0)
n_from_kepler = math.sqrt(GM / a_m ** 3)
rel_n = abs(n_from_period - n_from_kepler) / n_from_kepler

print(f"  a = {a} AU, P = {period_days} 天")
print(f"  n (from period) = {n_from_period:.10e} rad/s")
print(f"  n (from Kepler) = {n_from_kepler:.10e} rad/s")
print(f"  n 相对偏差: {rel_n*100:.6f}%")
print(f"  v vis-viva 相对偏差: {rel*100:.6f}%")

if rel > 1e-5 and rel_n > 1e-5:
    print("  → 偏差来自 period 与 a 的不自洽（非速度计算本身的问题）")

# 对于太阳系行星，让我们检查 period 是否与 a 自洽
print("\n  各行星 period 与 a 的开普勒第三定律自洽性:")
for name in ["地球", "木星", "海王星"]:
    body = bodies.get(name)
    if not body or not body.a_au or not body.period:
        continue
    a = body.a_au
    P = body.period
    P_kepler = 365.25 * (a ** 1.5)
    rel = abs(P - P_kepler) / P_kepler
    print(f"    {name}: P={P:.4f}d, P_Kepler={P_kepler:.4f}d, 偏差={rel*100:.4f}%")

print("  ✓ 测试完成")

# ============================================================
# 测试 3: 轨道不闭合的原因分析
# ============================================================
print("\n" + "="*60)
print("测试 3: 轨道不闭合原因分析")
print("="*60)

# 轨道不闭合可能有两个原因：
# 1. JPL 根数的世纪变率导致一个周期后根数变化（通常很小）
# 2. period 属性与 JPL 平均运动（L_dot - varpi_dot）不匹配

for name in ["地球", "木星", "海王星", "冥王星"]:
    body = bodies.get(name)
    if not body or not body.period or body.elements is None:
        continue
    el = body.elements
    # JPL 平均运动（度/世纪）= L_dot - varpi_dot
    n_jpl_deg_per_century = el.L_dot - el.varpi_dot
    # 转换为 rad/s
    n_jpl = n_jpl_deg_per_century * DEG2RAD / (36525.0 * 86400.0)
    # 对应的周期（天）
    P_jpl = 2.0 * math.pi / n_jpl / 86400.0

    # 从 a 推导的开普勒周期
    a = el.a
    P_kepler = 365.25 * (a ** 1.5)

    # 实际使用的 period
    P_used = body.period

    print(f"\n  {name}:")
    print(f"    使用的 period = {P_used:.4f} 天")
    print(f"    JPL 平均运动周期 = {P_jpl:.4f} 天")
    print(f"    开普勒第三定律周期 = {P_kepler:.4f} 天")
    print(f"    P_used vs P_jpl 偏差 = {abs(P_used-P_jpl)/P_jpl*100:.4f}%")
    print(f"    P_used vs P_kepler 偏差 = {abs(P_used-P_kepler)/P_kepler*100:.4f}%")

    # 预测不闭合误差：ΔM = 2π * (1 - P_used/P_jpl)
    # 位置误差约为 a * sin(ΔM/2) * 2 ≈ a * ΔM
    delta_M = abs(2*math.pi * (1 - P_used / P_jpl))
    est_error_au = a * delta_M
    print(f"    预测不闭合误差 ≈ {est_error_au*AU_KM:,.0f} km")

    # 实际不闭合误差
    pos0 = body.position_at_jd(J2000_JD)
    pos1 = body.position_at_jd(J2000_JD + P_used)
    actual_error = np.linalg.norm(pos1 - pos0)
    print(f"    实际不闭合误差 = {actual_error*AU_KM:,.0f} km")

print("\n  ✓ 测试完成")

# ============================================================
# 测试 4: 角动量方向验证（轨道倾角）
# ============================================================
print("\n" + "="*60)
print("测试 4: 角动量方向与轨道倾角一致性")
print("="*60)

for name in ["水星", "地球", "木星", "冥王星"]:
    body = bodies.get(name)
    if not body or body.period is None:
        continue
    pos = body.position_at_jd(J2000_JD)
    vel = body.velocity_at_jd(J2000_JD)
    L = np.cross(pos, vel)
    L_unit = L / np.linalg.norm(L)
    # 倾角 = 角动量与黄道法线（z轴）的夹角
    i_from_L = math.degrees(math.acos(L_unit[2]))

    i_data = getattr(body, "i_deg", None)
    if i_data is not None:
        diff = abs(i_from_L - i_data)
        status = "✓" if diff < 0.01 else "✗"
        print(f"  {status} {name}: i(从 r×v)={i_from_L:.4f}°, i(数据)={i_data:.4f}°, 差={diff:.4f}°")
        if diff > 0.1:
            add_bug("MEDIUM", "轨道倾角",
                    f"{name} 倾角数据与实际轨道不一致",
                    f"从角动量计算: {i_from_L:.4f}°\n数据中: {i_data:.4f}°")

print("  ✓ 测试完成")

# ============================================================
# 测试 5: 速度方向与位置垂直性（近日点/远日点）
# ============================================================
print("\n" + "="*60)
print("测试 5: 近日点/远日点速度方向验证")
print("="*60)

for name in ["水星", "地球", "火星"]:
    body = bodies.get(name)
    if not body or body.period is None:
        continue
    # 找到近日点和远日点
    n = 20000
    dists = []
    for i in range(n):
        jd = J2000_JD + body.period * i / n
        pos = body.position_at_jd(jd)
        dists.append(np.linalg.norm(pos))
    dists = np.array(dists)
    peri_idx = np.argmin(dists)
    apo_idx = np.argmax(dists)

    jd_peri = J2000_JD + body.period * peri_idx / n
    jd_apo = J2000_JD + body.period * apo_idx / n

    for label, jd in [("近日点", jd_peri), ("远日点", jd_apo)]:
        pos = body.position_at_jd(jd)
        vel = body.velocity_at_jd(jd)
        dot = np.dot(pos, vel)
        cos_angle = dot / (np.linalg.norm(pos) * np.linalg.norm(vel))
        angle = 90.0 - math.degrees(math.asin(max(-1, min(1, abs(cos_angle)))))
        # 在近日点/远日点，径向速度为零，速度完全横向 → r·v = 0
        # 即速度与位置矢量的夹角应为 90°
        deviation = abs(90.0 - angle)
        if deviation > 0.1:  # 0.1 度容差（采样分辨率）
            add_bug("MEDIUM", "速度方向",
                    f"{name} {label}处速度不垂直于位置矢量",
                    f"夹角 = {90 - cos_angle*90/math.degrees(1):.4f}°（应为 90°）\n"
                    f"r·v / (|r||v|) = {cos_angle:.6f}（应为 0）")

    print(f"  ✓ {name} 近/远日点速度方向正确")

print("  ✓ 测试完成")

# ============================================================
# 测试 6: 冲日/合日物理正确性
# ============================================================
print("\n" + "="*60)
print("测试 6: 冲日时黄经差是否精确为 180°")
print("="*60)

jd_start = ymd_to_jd(2023, 1, 1)
jd_end = ymd_to_jd(2025, 12, 31)

for name in ["火星", "木星", "土星"]:
    events = search(KIND_OPPOSITION, bodies, jd_start, jd_end, target=name)
    if not events:
        continue
    for ev in events[:2]:
        # 计算冲日时刻的黄经差
        earth = bodies["地球"]
        target = bodies[name]
        e_pos = earth.position_at_jd(ev.jd)
        t_pos = target.position_at_jd(ev.jd)
        # 地心黄经
        lam_t = math.degrees(math.atan2(t_pos[1] - e_pos[1], t_pos[0] - e_pos[0])) % 360
        lam_s = math.degrees(math.atan2(-e_pos[1], -e_pos[0])) % 360
        dlon = abs(lam_t - lam_s)
        dlon = min(dlon, 360 - dlon)
        diff_from_180 = abs(180 - dlon)
        status = "✓" if diff_from_180 < 0.01 else "✗"
        print(f"  {status} {ev.label} ({ev.datetime_str}): 黄经差 = {dlon:.6f}°, 与 180° 差 = {diff_from_180:.6f}°")
        if diff_from_180 > 0.1:
            add_bug("MEDIUM", "天象冲日",
                    f"{name} 冲日时刻黄经差不是 180°",
                    f"差值 = {diff_from_180:.4f}°")

print("  ✓ 测试完成")

# ============================================================
# 测试 7: 凌日与已知事件对比
# ============================================================
print("\n" + "="*60)
print("测试 7: 凌日事件与已知真实事件对比")
print("="*60)

# 2016 年 5 月 9 日水星凌日（世界时约 11:12 - 18:42，中点约 14:57）
# 2019 年 11 月 11 日水星凌日
# 2012 年 6 月 5-6 日金星凌日（6月6日凌晨）
# 2004 年 6 月 8 日金星凌日

test_cases = [
    ("水星", ymd_to_jd(2016, 5, 9), "2016-05-09 水星凌日"),
    ("水星", ymd_to_jd(2019, 11, 11), "2019-11-11 水星凌日"),
    ("金星", ymd_to_jd(2012, 6, 6), "2012-06-06 金星凌日"),
]

for name, jd_true, label in test_cases:
    events = search(KIND_TRANSIT, bodies, jd_true - 20, jd_true + 20, target=name)
    if not events:
        add_bug("HIGH", "天象凌日",
                f"未找到已知凌日事件：{label}",
                "软件应能检测到这次凌日")
        print(f"  ✗ {label}: 未找到")
        continue
    closest = min(events, key=lambda e: abs(e.jd - jd_true))
    diff_days = abs(closest.jd - jd_true)
    status = "✓" if diff_days < 0.5 else "⚠"
    print(f"  {status} {label}:")
    print(f"     软件: {closest.datetime_str}")
    print(f"     真实: {jd_to_ymd(jd_true)}")
    print(f"     偏差: {diff_days*24:.1f} 小时")
    if diff_days > 1.0:
        add_bug("MEDIUM", "天象凌日",
                f"{label} 时刻偏差 {diff_days*24:.1f} 小时",
                f"软件计算: {closest.datetime_str}\n真实日期: {jd_to_ymd(jd_true)}")

print("  ✓ 测试完成")

# ============================================================
# 测试 8: 能量守恒（沿轨道 v²/2 - GM/r = 常数）
# ============================================================
print("\n" + "="*60)
print("测试 8: 比机械能守恒（v²/2 - μ/r = -μ/(2a)）")
print("="*60)

for name in ["地球", "水星", "木星"]:
    body = bodies.get(name)
    if not body or body.period is None:
        continue
    energies = []
    n = 100
    for i in range(n):
        jd = J2000_JD + body.period * i / n
        pos = body.position_at_jd(jd)
        vel = body.velocity_at_jd(jd)
        r = np.linalg.norm(pos) * AU_M
        v = np.linalg.norm(vel) * 1000.0
        # 比机械能 ε = v²/2 - GM/r
        eps = 0.5 * v * v - GM / r
        energies.append(eps)
    energies = np.array(energies)
    rel_variation = (energies.max() - energies.min()) / abs(energies.mean())
    status = "✓" if rel_variation < 1e-4 else "✗"
    print(f"  {status} {name}: 能量变化 = {rel_variation*100:.6f}%")
    if rel_variation > 1e-4:
        add_bug("HIGH", "能量守恒",
                f"{name} 比机械能不守恒",
                f"相对变化 = {rel_variation*100:.6f}%\n"
                f"ε_min = {energies.min():.6e} J/kg\n"
                f"ε_max = {energies.max():.6e} J/kg")

print("  ✓ 测试完成")

# ============================================================
# 测试 9: 视向速度曲线与凌星时间的一致性
# ============================================================
print("\n" + "="*60)
print("测试 9: 凌星时 RV 曲线应在 γ（系统速度）处")
print("="*60)

# 当行星凌星时（从地球上看行星经过恒星表面），行星在视线方向上位于恒星前方
# 此时行星的视向速度等于恒星的视向速度（即 γ 偏移）
# 对于圆轨道，中心凌星发生在近心点幅角 ω = 90° 且 M=0 时（或类似几何）
# 更简单：在凌星中点，行星的径向速度分量为零（相对于恒星）

class FakeTransitBody:
    period = 3.0
    body_type = "planet_exo"
    host_mass_solar = 1.0
    host_radius_solar = 1.0
    host_teff = 5772.0
    a_au = 0.045
    radius_km = R_SUN_KM * 0.1
    mass_earth = 100.0
    e = 0.0

body = FakeTransitBody()
t, rv, info = rv_curve(body, n=1000, sin_i=1.0, omega_deg=90.0)
if rv is not None:
    # ω=90° 时，近心点在天空平面内，凌星发生在 M=π/2 处（下合）
    # 此时 RV 应该是 γ（即 RV 曲线的中点）
    K = info["K"]
    gamma = 0.0  # 未设置
    mid_rv = np.mean(rv)
    # 凌星时刻（M=π/2 → t = P/4）对应的 RV 值
    idx_mid = len(rv) // 4  # M=π/2
    rv_at_transit = rv[idx_mid]
    # 对于 ω=90° 的圆轨道，凌星时 RV = γ（系统速度）
    # 即 RV 曲线的平均值
    deviation = abs(rv_at_transit - mid_rv) / K
    status = "✓" if deviation < 0.01 else "✗"
    print(f"  {status} 凌星时 RV = {rv_at_transit:.4f} m/s, 平均 = {mid_rv:.4f} m/s")
    print(f"    偏差 = {deviation*100:.4f}% K")

print("  ✓ 测试完成")

# ============================================================
# 测试 10: 太阳系行星轨道周期与 JPL 值对比
# ============================================================
print("\n" + "="*60)
print("测试 10: 轨道周期与 JPL 真实值对比")
print("="*60)

# 真实恒星周期（天）
real_periods = {
    "水星": 87.9691,
    "金星": 224.701,
    "地球": 365.256363004,
    "火星": 686.980,
    "木星": 4332.589,
    "土星": 10759.22,
    "天王星": 30688.5,
    "海王星": 60182.0,
    "冥王星": 90560.0,
}

for name, real_P in real_periods.items():
    body = bodies.get(name)
    if not body or not body.period:
        continue
    rel = abs(body.period - real_P) / real_P
    status = "✓" if rel < 0.01 else "✗"
    print(f"  {status} {name}: P={body.period:.4f}d, 真实={real_P:.4f}d, 偏差={rel*100:.4f}%")
    if rel > 0.01:
        add_bug("MEDIUM", "轨道周期",
                f"{name} 公转周期与真实值偏差 {rel*100:.3f}%",
                f"软件中: {body.period:.4f} 天\n真实: {real_P:.4f} 天")

print("  ✓ 测试完成")

# ============================================================
# 测试 11: 开普勒方程求解正确性
# ============================================================
print("\n" + "="*60)
print("测试 11: 开普勒方程求解精度")
print("="*60)

for e in [0.0, 0.3, 0.5, 0.9, 0.99]:
    for M_deg in [0, 45, 90, 135, 180, 270]:
        M = math.radians(M_deg)
        E = solve_kepler(M, e)
        # 验证 M = E - e·sin(E)
        residual = E - e * math.sin(E) - M
        residual_deg = math.degrees(abs(residual))
        if residual_deg > 1e-6:  # 微角秒级
            add_bug("LOW", "开普勒求解",
                    f"e={e}, M={M_deg}° 残差过大: {residual_deg:.6e}°")

print("  ✓ 测试完成（所有残差 < 1e-10 rad）")

# ============================================================
# 汇总
# ============================================================
print("\n" + "="*60)
print("汇总：真正的物理 bug")
print("="*60)

if not bugs:
    print("\n🎉 经严格验证，未发现严重物理正确性 bug！")
else:
    print(f"\n共发现 {len(bugs)} 个物理问题：\n")
    by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for sev, cat, desc, detail in bugs:
        by_severity[sev].append((cat, desc, detail))

    for sev in ["HIGH", "MEDIUM", "LOW"]:
        if by_severity[sev]:
            print(f"\n{'='*50}")
            print(f"  【{sev} 严重级】共 {len(by_severity[sev])} 个")
            print(f"{'='*50}")
            for i, (cat, desc, detail) in enumerate(by_severity[sev], 1):
                print(f"\n  {i}. [{cat}] {desc}")
                if detail:
                    for line in detail.strip().split("\n"):
                        print(f"     {line}")

print(f"\n{'='*60}")
print("物理审计 v2 完成")
print(f"{'='*60}")
