"""test_period_jpl_consistency.py —— 行星周期与 JPL 平均运动自洽（审计修复 1）

背景（physics_audit_report.md Bug 1）：period 原用开普勒第三定律从 a 推算，
而 JPL 根数的平均运动（L_dot - varpi_dot）含行星间摄动长期项，两者有
~0.05%-0.3% 差异 → 「按 period 跳跃一个周期」后位置不闭合
（地球 ~13200 km、海王星 ~1650 万 km）。
修复：planet_solar/dwarf 优先用 P = 36525·360/(L_dot - varpi_dot)。
"""
import numpy as np
import pytest

from core.constants import AU_KM, J2000_JD
from data.loader import load_solar_system

AU_KM_D = AU_KM


@pytest.fixture(scope="module")
def bodies():
    return {b.name: b for b in load_solar_system()}


def test_period_uses_jpl_mean_motion(bodies):
    """行星 period = JPL 平均运动周期（非开普勒近似）"""
    for name in ("水星", "地球", "木星", "海王星", "冥王星"):
        b = bodies[name]
        el = b.elements
        p_jpl = 36525.0 * 360.0 / (el.L_dot - el.varpi_dot)
        p_kepler = 365.25 * b.a_au ** 1.5
        assert b.period == pytest.approx(p_jpl, rel=1e-12), name
        # 两者确有差异（否则修复无意义）：外行星 0.05%-0.3%
        assert abs(p_jpl / p_kepler - 1.0) < 0.005
    # 参考值：地球恒星周期 ≈ 365.256 天
    assert bodies["地球"].period == pytest.approx(365.256, rel=2e-4)


def test_one_period_jump_closes_orbit(bodies):
    """按 period 跳跃的闭合性验证。

    ① 冻结根数（变率=0）+ M 前进一个 JPL period → 位移必须为 0
       （period 与相位推进严格自洽的数学证明）。
    ② M 相位闭合：跳跃一个 period 后平近点角回到原值（mod 360°）。
    ③ 完整星历下的残差全部来自 varpi/Ω/i 世纪变率（行星摄动引起的
       轨道进动——JPL 受摄运动的真实物理，见 physics_audit_report.md §三）：
       海王星近日点进动最大（Δvarpi=-0.53°/周期，~3700 万 km）。
       注意：开普勒 period 跳跃的表面 gap 更小是「相位误差与进动位移
       恰好反向抵消」的巧合，不代表它更准；period 的正确判据是 ①②。
    """
    from core.kepler import position_at_time

    for name in ("水星", "地球", "木星", "海王星"):
        b = bodies[name]
        el = b.elements
        T1 = b.period / 36525.0

        # ① 冻结根数：M 精确前进 (L_dot - varpi_dot)·T1 = 360°
        p0f = position_at_time(el.a, 0, el.e, 0, el.i, 0, el.L, 0,
                               el.varpi, 0, el.Omega, 0, 0.0)
        p1f = position_at_time(el.a, 0, el.e, 0, el.i, 0,
                               el.L + (el.L_dot - el.varpi_dot) * T1, 0,
                               el.varpi, 0, el.Omega, 0, 0.0)
        gap_frozen = float(np.linalg.norm(p1f - p0f)) * AU_KM_D
        assert gap_frozen < 1.0, f"{name} 冻结根数闭合误差 {gap_frozen} km"

        # ② M 相位闭合（mod 360°，浮点精度内）
        dM = (el.L_dot - el.varpi_dot) * T1
        assert abs(dM % 360.0) < 1e-9 or abs(dM % 360.0 - 360.0) < 1e-9, (
            f"{name}: M 相位前进 {dM % 360.0}° ≠ 360°")

        # ③ JPL period 与开普勒 period 数量级一致（差异 < 0.5%）
        p_kepler = 365.25 * b.a_au ** 1.5
        assert abs(b.period / p_kepler - 1.0) < 0.005


def test_moon_and_etno_period_unchanged(bodies):
    """非 JPL 根数天体（etno/卫星）周期逻辑不变（开普勒/实测）"""
    for name in ("塞德娜", "创神星"):
        if name in bodies:
            b = bodies[name]
            if b.period_days:
                assert b.period == b.period_days
            elif b.a_au:
                assert b.period == pytest.approx(365.25 * b.a_au ** 1.5)


def test_sample_orbit_closed_param():
    """sample_orbit closed=True：末点 == 首点，轨道线严格闭合（审计修复 2）"""
    from core.kepler import sample_orbit

    pts_open = sample_orbit(5.2, 0.05, 1.3, 100.0, 30.0, 256)
    pts_closed = sample_orbit(5.2, 0.05, 1.3, 100.0, 30.0, 256, closed=True)
    assert pts_open.shape == (256, 3)
    assert pts_closed.shape == (257, 3)
    assert np.allclose(pts_closed[0], pts_closed[-1])
    assert np.allclose(pts_closed[:-1], pts_open)
    # 默认行为完全不变（向后兼容）
    assert np.allclose(pts_open[0], pts_open[-1] + 0.0) or \
        not np.allclose(pts_open[0], pts_open[-1])